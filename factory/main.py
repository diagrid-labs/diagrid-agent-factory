"""Entry point: one worker process hosting the agents and the workflows.

    uv run python -m factory.main

Run several copies and Catalyst spreads the workflow and activity work across
them; kill any of them at any point and the runs carry on where they stopped.
"""

from __future__ import annotations

import logging
import signal
import threading
import time

from dapr.ext import workflow as wf

from factory import activities, agents, config, tools, workflows

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
        state = client.get_workflow_state(workflows.WATCH_INSTANCE, fetch_payloads=False)
    except Exception:  # noqa: BLE001
        state = None
    if state is not None and state.runtime_status.name in {"RUNNING", "PENDING"}:
        log.info("issue-watch already running; it carries on from its last checkpoint")
        return
    if state is not None:
        client.purge_workflow(workflows.WATCH_INSTANCE)
    client.schedule_new_workflow("issue_watch", input=settings, instance_id=workflows.WATCH_INSTANCE)
    log.info("started issue-watch on %s every %ss", settings["repo"], settings["poll_seconds"])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "dapr_agents", "durabletask-worker", "WorkflowRuntime"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    rt = config.load()
    tools.configure(rt.work_root, rt.settings.scope, rt.settings.test_command)
    activities.configure(rt)

    runtime = wf.WorkflowRuntime()
    team = agents.build(
        config.ROOT / "agents",
        runtime,
        llm_component=rt.llm_component,
        state_store=rt.state_store,
        registry_store=rt.registry_store,
    )
    for name, fn in workflows.build({n: a.agent_workflow_name for n, a in team.items()}).items():
        runtime.register_workflow(fn, name=name)
    for fn in activities.ALL:
        runtime.register_activity(fn, name=fn.__name__)

    for agent in team.values():
        agent.start(runtime, auto_register=False)  # the first one starts the shared runtime
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
    for agent in team.values():
        try:
            agent.stop()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
