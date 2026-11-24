"""Activities: every side effect the workflows have (GitHub, git, tests).

Activities run at least once. Each one is written so a retry after a crash
does no harm: it re-clones instead of reusing a half-made checkout, skips a
commit when there is nothing to commit, and reuses a PR that already exists.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from dapr.ext import workflow as wf

from factory import config
from factory.config import Runtime
from factory.github import TRUSTED, GitHub
from factory.tools import run_test_command

log = logging.getLogger("factory")

MAX_DIFF = 30_000
APPROVAL_MARKER = "<!-- agent-factory:awaiting-approval -->"

_rt: Runtime | None = None
_gh: GitHub | None = None


def configure(rt: Runtime) -> None:
    global _rt, _gh
    _rt, _gh = rt, GitHub(rt.github_token, rt.settings.repo)


def gh() -> GitHub:
    assert _gh is not None, "activities.configure() was not called"
    return _gh


def issue_instance_id(repo: str, number: int) -> str:
    return f"issue-{repo.replace('/', '-')}-{number}"


def review_instance_id(repo: str, number: int, sha: str) -> str:
    return f"review-{repo.replace('/', '-')}-{number}-{sha[:7]}"


# Git ------------------------------------------------------------------------


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and out.returncode != 0:
        # Never log the token, even if git echoes the URL.
        err = out.stderr.replace(_rt.github_token, "***") if _rt else out.stderr
        raise RuntimeError(f"git {args[0]} failed: {err.strip()}")
    return out.stdout


def _authed_url(repo: str) -> str:
    return f"https://x-access-token:{_rt.github_token}@github.com/{repo}.git"


def prepare_workspace(ctx: wf.WorkflowActivityContext, inp: dict) -> dict:
    """Fresh clone at a ref, on a working branch. The token is not left in .git/config."""
    name = re.sub(r"[^A-Za-z0-9._-]", "-", inp["name"])
    path = _rt.work_root / name
    if path.exists():
        shutil.rmtree(path)
    repo = inp["repo"]
    _git(_rt.work_root, "clone", "--quiet", _authed_url(repo), str(path))
    if inp.get("fetch"):  # e.g. pull/12/head, so PRs from forks can be checked out
        _git(path, "fetch", "--quiet", "origin", inp["fetch"])
    _git(path, "remote", "set-url", "origin", f"https://github.com/{repo}.git")
    _git(path, "checkout", "--quiet", inp["ref"])
    if inp.get("branch"):
        _git(path, "checkout", "--quiet", "-B", inp["branch"])
    base = _git(path, "rev-parse", "HEAD").strip()
    return {"path": str(path), "base": base, "branch": inp.get("branch", "")}


def verify_workspace(ctx: wf.WorkflowActivityContext, inp: dict) -> dict:
    """The workflow's own check of the agent's work: what changed, and do the tests pass."""
    path = Path(inp["path"])
    scope = inp.get("scope") or ""
    _git(path, "add", "--all")
    changed = [f for f in _git(path, "diff", "--cached", "--name-only", inp["base"]).splitlines() if f]
    outside = [f for f in changed if scope and not f.startswith(scope + "/")]
    if outside:
        # The write tool already refuses these; this is the backstop.
        _git(path, "reset", "--quiet", inp["base"], "--", *outside)
        _git(path, "checkout", "--quiet", inp["base"], "--", *outside, check=False)
        _git(path, "clean", "-fdq", "--", *outside, check=False)
        _git(path, "add", "--all")
        changed = [f for f in changed if f not in outside]
    diff = _git(path, "diff", "--cached", inp["base"])
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + "\n... (diff truncated)"
    passed, output = run_test_command(path)
    return {
        "changed": changed,
        "reverted_outside_scope": outside,
        "diff": diff,
        "tests_passed": passed,
        "test_output": output,
    }


# Issues ---------------------------------------------------------------------


def claim_issue(ctx: wf.WorkflowActivityContext, inp: dict) -> dict:
    number = inp["number"]
    issue = gh().issue(number)
    if issue["state"] != "open":
        return {"skip": True, "reason": "issue is closed"}
    gh().add_labels(number, config.LABEL_IN_PROGRESS)
    gh().remove_label(number, config.LABEL_IMPLEMENT)
    gh().comment(
        number,
        f"Picked up by the implementer agent. Workflow run `{inp['instance_id']}` on Diagrid Catalyst.",
    )
    return {
        "skip": False,
        "number": number,
        "title": issue["title"],
        "body": issue.get("body") or "",
        "default_branch": gh().default_branch(),
    }


def comment(ctx: wf.WorkflowActivityContext, inp: dict) -> None:
    gh().comment(inp["number"], inp["body"])


def set_labels(ctx: wf.WorkflowActivityContext, inp: dict) -> None:
    if inp.get("add"):
        gh().add_labels(inp["number"], *inp["add"])
    for label in inp.get("remove", []):
        gh().remove_label(inp["number"], label)


def request_approval(ctx: wf.WorkflowActivityContext, inp: dict) -> None:
    number = inp["number"]
    gh().comment(
        number,
        "\n".join(
            [
                APPROVAL_MARKER,
                f"The change passed review and tests. Files: {', '.join(inp['files'])}",
                "",
                "<details><summary>Diff</summary>",
                "",
                "```diff",
                inp["diff"],
                "```",
                "</details>",
                "",
                "Reply `/approve` to open the pull request, or `/reject` to stop.",
                "The workflow waits durably for your answer: the worker can be stopped and restarted meanwhile.",
            ]
        ),
    )
    gh().add_labels(number, config.LABEL_AWAITING_APPROVAL)


def open_pull_request(ctx: wf.WorkflowActivityContext, inp: dict) -> dict:
    path = Path(inp["path"])
    branch = inp["branch"]
    _git(path, "add", "--all")
    if _git(path, "status", "--porcelain").strip():
        _git(
            path,
            "-c", "user.name=Catalyst Agent Factory",
            "-c", "user.email=agent-factory@users.noreply.github.com",
            "commit", "--quiet", "-m", f"{inp['title']}\n\nResolves #{inp['number']}.",
        )
    _git(path, "push", "--quiet", "--force", _authed_url(inp["repo"]), f"HEAD:refs/heads/{branch}")
    pr = gh().find_pr(branch) or gh().open_pr(
        head=branch, base=inp["base_branch"], title=inp["title"], body=inp["body"]
    )
    return {"number": pr["number"], "url": pr["html_url"]}


# Pull requests --------------------------------------------------------------


def fetch_pr(ctx: wf.WorkflowActivityContext, inp: dict) -> dict:
    pr = gh().pr(inp["number"])
    diff = gh().pr_diff(inp["number"])
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + "\n... (diff truncated)"
    return {
        "number": pr["number"],
        "title": pr["title"],
        "body": pr.get("body") or "",
        "head_sha": pr["head"]["sha"],
        "head_repo": pr["head"]["repo"]["full_name"],
        "diff": diff,
    }


def post_review(ctx: wf.WorkflowActivityContext, inp: dict) -> None:
    gh().review(inp["number"], inp["commit_id"], inp["body"])
    gh().remove_label(inp["number"], config.LABEL_REVIEW)
    gh().add_labels(inp["number"], config.LABEL_REVIEWED)


# The watcher's poll ---------------------------------------------------------


def _start_once(client: wf.DaprWorkflowClient, workflow: str, instance_id: str, inp: dict) -> bool:
    """Start a workflow unless one with this id is still running. Returns True if started."""
    try:
        state = client.get_workflow_state(instance_id, fetch_payloads=False)
    except Exception:  # noqa: BLE001 - not found surfaces as an error on some runtimes
        state = None
    if state is not None:
        status = state.runtime_status.name
        if status in {"RUNNING", "PENDING", "SUSPENDED"}:
            return False
        client.purge_workflow(instance_id)  # an earlier, finished run: start again
    client.schedule_new_workflow(workflow, input=inp, instance_id=instance_id)
    return True


def _approval_answer(number: int) -> str | None:
    """The newest /approve or /reject from a trusted person, after the approval request."""
    answer = None
    seen_marker = False
    for c in gh().comments(number):
        body = (c.get("body") or "").strip()
        if APPROVAL_MARKER in body:
            seen_marker, answer = True, None
            continue
        if not seen_marker or c.get("author_association") not in TRUSTED:
            continue
        # Accept a full-width slash too (／approve), as some keyboards type it.
        first = body.split()[0].lower().replace("／", "/") if body else ""
        if first in ("/approve", "/reject"):
            answer = first[1:]
    return answer


def poll(ctx: wf.WorkflowActivityContext, settings: dict) -> dict:
    repo = settings["repo"]
    client = wf.DaprWorkflowClient()
    started, approvals = [], []

    for issue in gh().issues_with_label(config.LABEL_IMPLEMENT):
        iid = issue_instance_id(repo, issue["number"])
        if _start_once(client, "implement_issue", iid, {"number": issue["number"], "settings": settings}):
            started.append(iid)

    for pr in gh().prs_with_label(config.LABEL_REVIEW):
        sha = gh().pr(pr["number"])["head"]["sha"]
        iid = review_instance_id(repo, pr["number"], sha)
        if _start_once(client, "review_pull_request", iid, {"number": pr["number"], "settings": settings}):
            started.append(iid)

    for issue in gh().issues_with_label(config.LABEL_AWAITING_APPROVAL):
        answer = _approval_answer(issue["number"])
        if answer:
            client.raise_workflow_event(
                issue_instance_id(repo, issue["number"]), "approval", data={"decision": answer}
            )
            approvals.append(f"#{issue['number']}:{answer}")

    if started or approvals:
        log.info("poll: started %s, approvals %s", started, approvals)
    return {"started": started, "approvals": approvals}


def ensure_labels(ctx: wf.WorkflowActivityContext, _: dict | None = None) -> None:
    for name, color, desc in [
        (config.LABEL_IMPLEMENT, "1d76db", "Ask the implementer agent to resolve this issue"),
        (config.LABEL_IN_PROGRESS, "fbca04", "An agent is working on this"),
        (config.LABEL_AWAITING_APPROVAL, "d93f0b", "Reply /approve or /reject"),
        (config.LABEL_DONE, "0e8a16", "The agent opened a pull request"),
        (config.LABEL_NEEDS_HUMAN, "b60205", "The agent stopped and needs a person"),
        (config.LABEL_REVIEW, "5319e7", "Ask the reviewer agent to review this PR"),
        (config.LABEL_REVIEWED, "c5def5", "The reviewer agent posted a review"),
    ]:
        gh().ensure_label(name, color, desc)


ALL = [
    prepare_workspace,
    verify_workspace,
    claim_issue,
    comment,
    set_labels,
    request_approval,
    open_pull_request,
    fetch_pr,
    post_review,
    poll,
    ensure_labels,
]
