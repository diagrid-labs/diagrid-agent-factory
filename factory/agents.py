"""The agent factory: one DurableAgent per file in agents/.

Each agents/<name>.md has YAML front matter (name, role, goal, tools,
max_iterations) and the instructions as its body. Adding an agent is adding a
file; every agent runs on the same workflow runtime, registers itself in the
Catalyst agent registry and can be called from any workflow as a child workflow.
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


def build(
    folder: Path,
    runtime: wf.WorkflowRuntime,
    *,
    llm_component: str,
    state_store: str,
    registry_store: str,
) -> dict[str, DurableAgent]:
    agents: dict[str, DurableAgent] = {}
    for path in sorted(folder.glob("*.md")):
        spec = read_spec(path)
        agent = DurableAgent(
            name=spec.name,
            role=spec.role,
            goal=spec.goal,
            instructions=[spec.instructions],
            tools=[agent_tools.ALL[t] for t in spec.tools],
            llm=DaprChatClient(component_name=llm_component),
            state=AgentStateConfig(store=StateStoreService(store_name=state_store)),
            registry=AgentRegistryConfig(
                store=StateStoreService(store_name=registry_store), team_name=TEAM
            ),
            execution=AgentExecutionConfig(max_iterations=spec.max_iterations),
            runtime=runtime,
        )
        agent.register(runtime)
        agents[spec.name] = agent
    if not agents:
        raise SystemExit(f"no agent definitions in {folder}")
    return agents
