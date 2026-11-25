"""Put the demo back to its starting point, so it can be run again.

The Reset demo action runs this.

What it does, in order:
1. terminates the agents' running workflows on Diagrid (the watcher keeps running),
2. closes the agents' open pull requests and deletes their agent/* branches,
3. closes the open demo issues: any with an agent:* label or a seeded title,
4. restores the scope directory (sample-app/) on the default branch from the
   `demo-baseline` tag, so the seeded bugs are there again,
5. opens the demo issues again.

Only TARGET_REPO is touched. Pass --project if your Diagrid project is not
called agent-factory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory import config  # noqa: E402
from factory.github import GitHub  # noqa: E402
from seed_issues import ISSUES, seed  # noqa: E402

BASELINE = "demo-baseline"
APP_ID = "agent-factory"
RUNNING = {"running", "pending", "suspended"}


def step(msg: str) -> None:
    print(f"\n== {msg}")


def running_workflows(project: str, repo: str) -> list[str]:
    """The agents' runs on Diagrid that are still going. Not the watcher."""
    if not shutil.which("diagrid"):
        print("   diagrid CLI not found: skipping")
        return []
    out = subprocess.run(
        ["diagrid", "workflow", "list", "--project", project, "--limit", "250", "-o", "json"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        print(f"   could not list workflows: {out.stderr.strip()[:200]}")
        return []
    slug = repo.replace("/", "-")
    prefixes = (f"issue-{slug}-", f"review-{slug}-")
    return [
        w["workflowId"]
        for w in json.loads(out.stdout or "[]")
        if w.get("status", "").lower() in RUNNING and w["workflowId"].startswith(prefixes)
    ]


def restore_scope(rt: config.Runtime, gh: GitHub, apply: bool) -> None:
    repo, scope = rt.settings.repo, rt.settings.scope
    with tempfile.TemporaryDirectory() as tmp:
        url = f"https://x-access-token:{rt.github_token}@github.com/{repo}.git"
        git = lambda *a, check=True: subprocess.run(  # noqa: E731
            ["git", "-C", tmp, *a], capture_output=True, text=True, check=check
        )
        subprocess.run(["git", "clone", "--quiet", url, tmp], capture_output=True, check=True)
        if git("rev-parse", "--verify", "--quiet", f"refs/tags/{BASELINE}", check=False).returncode != 0:
            print(f"   no '{BASELINE}' tag on {repo}: skipping. Tag the commit with the original {scope}/ to enable this.")
            return
        git("checkout", "--quiet", BASELINE, "--", scope)
        # Files the agents added (new tests, say) are not in the baseline: remove them.
        for path in git("ls-files", scope).stdout.split():
            if git("cat-file", "-e", f"{BASELINE}:{path}", check=False).returncode != 0:
                git("rm", "--quiet", path)
        changed = git("status", "--porcelain").stdout.strip()
        if not changed:
            print(f"   {scope}/ already matches {BASELINE}")
            return
        print("   " + "\n   ".join(changed.splitlines()))
        if apply:
            git(
                "-c", "user.name=Diagrid Agent Factory",
                "-c", "user.email=agent-factory@users.noreply.github.com",
                "commit", "--quiet", "-am", f"Reset {scope}/ for the demo",
            )
            git("push", "--quiet", "origin", f"HEAD:{gh.default_branch()}")
            print(f"   pushed: {scope}/ restored from {BASELINE}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="do it (default: only show what would happen)")
    parser.add_argument("--no-seed", action="store_true", help="do not open fresh issues")
    parser.add_argument("--label", action="store_true", help="label the fresh issues agent:implement")
    parser.add_argument("--only", type=int, action="append", choices=range(1, len(ISSUES) + 1),
                        help="open only this issue (1-based, repeatable)")
    parser.add_argument("--project", default="agent-factory", help="Diagrid project name")
    args = parser.parse_args()

    rt = config.load()
    gh = GitHub(rt.github_token, rt.settings.repo)
    apply = args.yes
    print(f"Resetting the demo on {rt.settings.repo}" + ("" if apply else "  (dry run: add --yes to do it)"))

    step("Running agent workflows on Diagrid")
    for wid in running_workflows(args.project, rt.settings.repo):
        print(f"   terminate {wid}")
        if apply:
            subprocess.run(
                ["diagrid", "workflow", "terminate", "--project", args.project, "--id", APP_ID, "--instance-id", wid],
                capture_output=True,
            )

    step("Agent pull requests and branches")
    for pr in gh.open_prs():
        if pr["head"]["ref"].startswith("agent/"):
            print(f"   close PR #{pr['number']} {pr['title']}")
            if apply:
                gh.comment(pr["number"], "Closed by the demo reset.")
                gh.close(pr["number"])
    for branch in gh.branches("agent/"):
        print(f"   delete branch {branch}")
        if apply:
            gh.delete_branch(branch)

    step("Demo issues")
    titles = {t for t, _ in ISSUES}
    for issue in gh.open_issues():
        labels = [label["name"] for label in issue["labels"]]
        if issue["title"] in titles or any(name.startswith("agent:") for name in labels):
            print(f"   close #{issue['number']} {issue['title']}")
            if apply:
                gh.comment(issue["number"], "Closed by the demo reset.")
                gh.close(issue["number"])
                for name in labels:
                    if name.startswith("agent:"):
                        gh.remove_label(issue["number"], name)

    step(f"{rt.settings.scope}/ on the default branch")
    restore_scope(rt, gh, apply)

    if args.no_seed:
        return
    step("Fresh issues")
    if apply:
        seed(gh, args.label, args.only)
    else:
        for i, (title, _) in enumerate(ISSUES, start=1):
            if args.only and i not in args.only:
                continue
            print(f"   open: {title}" + ("  [agent:implement]" if args.label else ""))


if __name__ == "__main__":
    main()
