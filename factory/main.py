"""Entry point: one worker process hosting the agents and the workflows.

    uv run python -m factory.main

Run several copies and Diagrid spreads the workflow and activity work across
them; kill any of them at any point and the runs carry on where they stopped.
"""

from __future__ import annotations

import os

import certifi

# python.org builds of Python on macOS ship without root certificates; use certifi's
# so the HTTPS calls to the Diagrid endpoints verify. Must run before dapr is imported.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

import json  # noqa: E402
import logging  # noqa: E402
import signal  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from dapr.ext import workflow as wf  # noqa: E402

from factory import activities, agents, config, tools, workflows  # noqa: E402

log = logging.getLogger("factory")


def _wait_for_sidecar(client: wf.DaprWorkflowClient) -> None:
    for _ in range(60):
        try:
            client.get_workflow_state("startup-probe", fetch_payloads=False)
            return
        except Exception as exc:  # noqa: BLE001
            if "not found" in str(exc).lower() or "no such instance" in str(exc).lower():
                return
            time.sleep(2)


def _start_watch(client: wf.DaprWorkflowClient, settings: dict) -> None:
    try:
        state = client.get_workflow_state(workflows.WATCH_INSTANCE, fetch_payloads=True)
    except Exception:  # noqa: BLE001
        state = None
    if state is not None and state.runtime_status.name in {"RUNNING", "PENDING"}:
        # continue_as_new carries the settings forward, so a changed setting only
        # takes effect if the watcher starts again.
        if json.loads(state.serialized_input or "null") == settings:
            log.info("issue-watch already running; it carries on from its last checkpoint")
            return
        log.info("settings changed: restarting issue-watch")
        client.terminate_workflow(workflows.WATCH_INSTANCE)
        client.wait_for_workflow_completion(workflows.WATCH_INSTANCE, timeout_in_seconds=60)
    if state is not None:
        client.purge_workflow(workflows.WATCH_INSTANCE)
    client.schedule_new_workflow("issue_watch", input=settings, instance_id=workflows.WATCH_INSTANCE)
    log.info("started issue-watch on %s every %ss", settings["repo"], settings["poll_seconds"])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "mcp", "claude_agent_sdk", "dapr_agents", "durabletask-client", "durabletask-worker", "WorkflowRuntime"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    rt = config.load()
    tools.configure(rt.work_root, rt.settings.scope, rt.settings.test_command)
    activities.configure(rt)

    runtime = wf.WorkflowRuntime()
    team = agents.build(
        config.ROOT / "agents",
        runtime,
        backend=rt.backend,
        llm_component=rt.llm_component,
        claude_model=rt.claude_model,
        state_store=rt.state_store,
        registry_store=rt.registry_store,
    )
    for name, fn in workflows.build({n: a.agent_workflow_name for n, a in team.items()}).items():
        runtime.register_workflow(fn, name=name)
    for fn in activities.ALL:
        runtime.register_activity(fn, name=fn.__name__)

    # Every agent's start() also starts the shared runtime; after the first, that is
    # a harmless "already running" error, kept out of the log.
    for i, agent in enumerate(team.values()):
        quiet = [logging.getLogger(n) for n in ("WorkflowRuntime", "dapr_agents.agents.durable")] if i else []
        levels = [q.level for q in quiet]
        for q in quiet:
            q.setLevel(logging.CRITICAL)
        agent.start(runtime, auto_register=False)
        for q, level in zip(quiet, levels):
            q.setLevel(level)
    log.info("agents: %s", ", ".join(team))

    client = wf.DaprWorkflowClient()
    _wait_for_sidecar(client)
    activities.ensure_labels(None)
    _start_watch(client, rt.settings.to_dict())

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    log.info("ready: label an issue '%s' or a PR '%s' on %s", config.LABEL_IMPLEMENT, config.LABEL_REVIEW, rt.settings.repo)
    stop.wait()
    log.info("shutting down")

    def _stop() -> None:
        for agent in team.values():
            try:
                agent.stop()  # also removes it from the agent registry
            except Exception:  # noqa: BLE001
                pass

    # Nothing is lost by stopping hard: every run continues from its last
    # checkpoint when a worker comes back. So do not wait long.
    t = threading.Thread(target=_stop, daemon=True)
    t.start()
    t.join(timeout=5)
    os._exit(0)


if __name__ == "__main__":
    main()
