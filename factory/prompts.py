"""Task text for the agents, and parsing of what they send back. Pure functions:
the workflows call them during replay too."""

from __future__ import annotations

import re
from typing import Any

VERDICT = re.compile(r"VERDICT:\s*(APPROVE|REQUEST_CHANGES)", re.IGNORECASE)


def agent_text(result: Any) -> str:
    """The final assistant text from a DurableAgent run."""
    if isinstance(result, dict):
        for key in ("content", "result", "output"):
            if isinstance(result.get(key), str):
                return result[key]
    return "" if result is None else str(result)


def verdict(review: str) -> str | None:
    found = VERDICT.findall(review)
    return found[-1].upper() if found else None


def implement_task(issue: dict, workspace: str, scope: str, feedback: str = "") -> str:
    parts = [
        f"Resolve issue #{issue['number']}: {issue['title']}",
        "",
        "Issue description:",
        issue.get("body") or "(no description)",
        "",
        f"Workspace: {workspace}",
        f"Scope directory (the only place you may write): {scope}/",
        "Pass the workspace path exactly as written above to every tool.",
    ]
    if feedback:
        parts += [
            "",
            "Your previous attempt is still in the workspace. A reviewer and the test run asked for these changes:",
            feedback,
            "Address every point, run the tests again, then reply with the updated summary.",
        ]
    return "\n".join(parts)


def review_task(subject: str, description: str, diff: str, workspace: str) -> str:
    return "\n".join(
        [
            f"Review this change: {subject}",
            "",
            "What it is meant to do:",
            description or "(no description)",
            "",
            f"Workspace (the change is applied here): {workspace}",
            "Pass the workspace path exactly as written above to every tool.",
            "",
            "Diff:",
            "```diff",
            diff,
            "```",
        ]
    )


def feedback_for(review: str, tests_passed: bool, test_output: str) -> str:
    notes = [review.strip()]
    if not tests_passed:
        notes.append("The test suite fails:\n" + test_output[-4000:])
    return "\n\n".join(notes)
