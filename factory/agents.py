"""The agent factory: one DurableAgent per file in agents/.

Each agents/<name>.md has YAML front matter (name, role, goal, tools,
max_iterations) and the instructions as its body. Adding an agent is adding a
file; every agent runs on the same workflow runtime, registers itself in the
Diagrid agent registry and can be called from any workflow as a child workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from dapr.ext import workflow as wf
from dapr_agents import DurableAgent
from dapr_agents.agents.configs import (
    AgentExecutionConfig,
    AgentRegistryConfig,
    AgentStateConfig,
)
from dapr_agents.llm import DaprChatClient
from dapr_agents.storage.daprstores.stateservice import StateStoreService

from factory import tools as agent_tools

TEAM = "agent-factory"


@dataclass(frozen=True)
class Spec:
    name: str
    role: str
    goal: str
    tools: list[str]
    max_iterations: int
    instructions: str


def read_spec(path: Path) -> Spec:
    text = path.read_text()
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing front matter")
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front) or {}
    unknown = set(meta.get("tools", [])) - set(agent_tools.ALL)
    if unknown:
        raise ValueError(f"{path}: unknown tools {sorted(unknown)}")
    return Spec(
        name=meta["name"],
        role=meta.get("role", meta["name"]),
        goal=meta.get("goal", ""),
        tools=list(meta.get("tools", [])),
        max_iterations=int(meta.get("max_iterations", 20)),
        instructions=body.strip(),
    )


def _brain(spec: Spec, backend: str, llm_component: str, claude_model: str, store: StateStoreService) -> dict:
    """How the agent thinks: the Claude Agent SDK, or any LLM behind a Dapr Conversation component."""
    if backend == "conversation":
        # Every LLM call and every tool call is its own workflow activity.
        return {"llm": DaprChatClient(component_name=llm_component)}
    if backend != "claude":
        raise SystemExit(f"AGENT_BACKEND must be claude or conversation, not {backend!r}")
    # Claude Code as the agent loop, run inside a workflow activity. It uses the
    # machine's Claude login, or CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY.
    # builtin_tools stays empty: Claude gets only the tools in the agent file,
    # never its own Bash, Edit or Read. The session transcript is kept in the
    # Diagrid state store, so a run picks up where it stopped on any host.
    from dapr_agents.agents.executors import (
        ClaudeAgentExecutor,
        ClaudeAgentExecutorConfig,
        DaprSessionStore,
        DaprSessionStoreConfig,
    )

    config = ClaudeAgentExecutorConfig(
        model=claude_model or None,
        max_turns=spec.max_iterations,
        permission_mode="bypassPermissions",
        session_store=DaprSessionStore(
            store, config=DaprSessionStoreConfig(key_prefix=f"claude-{spec.name}", ttl_in_seconds=14 * 86400)
        ),
    )
    return {"executor": ClaudeAgentExecutor(config)}


def build(
    folder: Path,
    runtime: wf.WorkflowRuntime,
    *,
    backend: str,
    llm_component: str,
    claude_model: str,
    state_store: str,
    registry_store: str,
) -> dict[str, DurableAgent]:
    agents: dict[str, DurableAgent] = {}
    for path in sorted(folder.glob("*.md")):
        spec = read_spec(path)
        store = StateStoreService(store_name=state_store)
        agent = DurableAgent(
            name=spec.name,
            role=spec.role,
            goal=spec.goal,
            instructions=[spec.instructions],
            tools=[agent_tools.ALL[t] for t in spec.tools],
            **_brain(spec, backend, llm_component, claude_model, store),
            state=AgentStateConfig(store=store),
            # Listed in the Diagrid agent registry, each in a team of its own: agents in
            # one team become each other's tools, and here the workflow, not the
            # implementer, decides when the reviewer runs.
            registry=AgentRegistryConfig(
                store=StateStoreService(store_name=registry_store), team_name=f"{TEAM}-{spec.name}"
            ),
            execution=AgentExecutionConfig(max_iterations=spec.max_iterations),
            runtime=runtime,
        )
        agent.register(runtime)
        agents[spec.name] = agent
    if not agents:
        raise SystemExit(f"no agent definitions in {folder}")
    return agents
