"""The three workflows.

issue_watch          one long-running instance; polls GitHub, starts the others,
                     forwards /approve and /reject comments as workflow events.
implement_issue      one per issue: claim, clone, implementer agent, the workflow's
                     own verification, reviewer agent (up to N rounds), a human
                     approval gate, then push and open the pull request.
review_pull_request  one per PR head: clone, reviewer agent, post the review.

Workflow code must be deterministic: it only decides. Every side effect is an
activity, every agent run is a child workflow, and all settings come in as input.
"""

from __future__ import annotations

from datetime import timedelta

from dapr.ext import workflow as wf

from factory import activities as act
from factory import config, prompts

RETRY = wf.RetryPolicy(
    first_retry_interval=timedelta(seconds=2),
    max_number_of_attempts=5,
    backoff_coefficient=2,
    max_retry_interval=timedelta(seconds=60),
)

WATCH_INSTANCE = "issue-watch"


def build(agent_workflows: dict[str, str]):
    """Workflows bound to the agents' registered workflow names."""
    implementer = agent_workflows["implementer"]
    reviewer = agent_workflows["reviewer"]

    def issue_watch(ctx: wf.DaprWorkflowContext, settings: dict):
        yield ctx.call_activity(act.poll, input=settings, retry_policy=RETRY)
        yield ctx.create_timer(timedelta(seconds=settings["poll_seconds"]))
        # A fresh history each tick, so the watcher can run for months.
        ctx.continue_as_new(settings)

    def implement_issue(ctx: wf.DaprWorkflowContext, inp: dict):
        s = inp["settings"]
        number = inp["number"]
        iid = ctx.instance_id

        issue = yield ctx.call_activity(
            act.claim_issue, input={"number": number, "instance_id": iid}, retry_policy=RETRY
        )
        if issue["skip"]:
            return {"outcome": "skipped", "reason": issue["reason"]}

        branch = f"agent/issue-{number}"
        ws = yield ctx.call_activity(
            act.prepare_workspace,
            input={"repo": s["repo"], "name": iid, "ref": issue["default_branch"], "branch": branch},
            retry_policy=RETRY,
        )

        feedback, summary, check, approved = "", "", None, False
        for round_no in range(1, s["max_review_rounds"] + 1):
            # 1. The implementer agent changes the code (a durable child workflow:
            #    every LLM call and tool call in it is checkpointed).
            result = yield ctx.call_child_workflow(
                implementer,
                input={"task": prompts.implement_task(issue, ws["path"], s["scope"], feedback)},
                instance_id=f"{iid}-implement-{round_no}",
            )
            summary = prompts.agent_text(result) or summary

            # 2. The workflow checks the work itself instead of trusting the agent's word.
            check = yield ctx.call_activity(
                act.verify_workspace,
                input={"path": ws["path"], "base": ws["base"], "scope": s["scope"]},
                retry_policy=RETRY,
            )
            if not check["changed"]:
                return (yield from _needs_human(ctx, number, "The implementer finished without changing any file.", summary))

            # 3. A separate reviewer agent, with fresh context, reviews the diff.
            review_result = yield ctx.call_child_workflow(
                reviewer,
                input={
                    "task": prompts.review_task(
                        f"issue #{number}: {issue['title']}", issue["body"], check["diff"], ws["path"]
                    )
                },
                instance_id=f"{iid}-review-{round_no}",
            )
            review = prompts.agent_text(review_result)
            verdict = prompts.verdict(review)
            tests = "pass" if check["tests_passed"] else "FAIL"
            yield ctx.call_activity(
                act.comment,
                input={
                    "number": number,
                    "body": f"Round {round_no}: tests {tests}, reviewer says **{verdict or 'no verdict'}**.\n\n{review}",
                },
                retry_policy=RETRY,
            )
            if verdict == "APPROVE" and check["tests_passed"]:
                approved = True
                break
            feedback = prompts.feedback_for(review, check["tests_passed"], check["test_output"])

        if not approved:
            return (yield from _needs_human(
                ctx, number, f"No approved, passing change after {s['max_review_rounds']} review rounds.", summary
            ))

        # 4. Optional human gate. The workflow waits durably; nothing runs while it waits.
        if s["require_approval"]:
            yield ctx.call_activity(
                act.request_approval,
                input={"number": number, "files": check["changed"], "diff": check["diff"][:20_000]},
                retry_policy=RETRY,
            )
            answer = ctx.wait_for_external_event("approval")
            timeout = ctx.create_timer(timedelta(hours=s["approval_timeout_hours"]))
            winner = yield wf.when_any([answer, timeout])
            yield ctx.call_activity(
                act.set_labels,
                input={"number": number, "remove": [config.LABEL_AWAITING_APPROVAL]},
                retry_policy=RETRY,
            )
            if winner == timeout:
                return (yield from _needs_human(ctx, number, "Nobody approved in time.", summary))
            if (answer.get_result() or {}).get("decision") != "approve":
                return (yield from _needs_human(ctx, number, "Rejected by a reviewer.", summary))

        # 5. The workflow, not the agent, pushes and opens the PR.
        pr = yield ctx.call_activity(
            act.open_pull_request,
            input={
                "repo": s["repo"],
                "path": ws["path"],
                "branch": branch,
                "base_branch": issue["default_branch"],
                "number": number,
                "title": f"Fix #{number}: {issue['title']}",
                "body": f"Resolves #{number}.\n\n{summary}\n\n---\nOpened by the implementer agent "
                f"(workflow `{iid}`), reviewed by the reviewer agent, tests passing.",
            },
            retry_policy=RETRY,
        )
        if pr.get("missing"):
            return (yield from _needs_human(
                ctx, number, "The worker lost its checkout before it could push. Label the issue again to redo it.", summary
            ))
        yield ctx.call_activity(
            act.set_labels,
            input={"number": number, "add": [config.LABEL_DONE], "remove": [config.LABEL_IN_PROGRESS]},
            retry_policy=RETRY,
        )
        yield ctx.call_activity(
            act.comment, input={"number": number, "body": f"Opened {pr['url']}"}, retry_policy=RETRY
        )
        return {"outcome": "pr_opened", "pr": pr["url"]}

    def _needs_human(ctx: wf.DaprWorkflowContext, number: int, reason: str, summary: str):
        yield ctx.call_activity(
            act.set_labels,
            input={"number": number, "add": [config.LABEL_NEEDS_HUMAN], "remove": [config.LABEL_IN_PROGRESS]},
            retry_policy=RETRY,
        )
        body = f"Stopping: {reason}"
        if summary:
            body += f"\n\nLast summary from the implementer:\n\n{summary}"
        yield ctx.call_activity(act.comment, input={"number": number, "body": body}, retry_policy=RETRY)
        return {"outcome": "needs_human", "reason": reason}

    def review_pull_request(ctx: wf.DaprWorkflowContext, inp: dict):
        s = inp["settings"]
        pr = yield ctx.call_activity(act.fetch_pr, input={"number": inp["number"]}, retry_policy=RETRY)
        ws = yield ctx.call_activity(
            act.prepare_workspace,
            input={
                "repo": s["repo"],
                "name": ctx.instance_id,
                "ref": pr["head_sha"],
                "fetch": f"pull/{pr['number']}/head",
            },
            retry_policy=RETRY,
        )
        result = yield ctx.call_child_workflow(
            reviewer,
            input={"task": prompts.review_task(f"PR #{pr['number']}: {pr['title']}", pr["body"], pr["diff"], ws["path"])},
            instance_id=f"{ctx.instance_id}-review",
        )
        review = prompts.agent_text(result)
        yield ctx.call_activity(
            act.post_review,
            input={
                "number": pr["number"],
                "commit_id": pr["head_sha"],
                "body": f"{review}\n\n---\nReview by the reviewer agent (workflow `{ctx.instance_id}`).",
            },
            retry_policy=RETRY,
        )
        return {"outcome": "reviewed", "verdict": prompts.verdict(review)}

    return {
        "issue_watch": issue_watch,
        "implement_issue": implement_issue,
        "review_pull_request": review_pull_request,
    }
