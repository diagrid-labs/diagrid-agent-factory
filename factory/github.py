"""A small GitHub REST client: only the calls the workflows make.

Swap this module for a GitLab one (issues, merge requests, notes) and the
workflows do not change.
"""

from __future__ import annotations

from typing import Any

import httpx

API = "https://api.github.com"
# People whose /approve or /reject on an issue counts.
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}


class GitHub:
    def __init__(self, token: str, repo: str) -> None:
        self.repo = repo
        self._http = httpx.Client(
            base_url=API,
            timeout=30,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        resp = self._http.request(method, f"/repos/{self.repo}{path}", **kw)
        if resp.status_code == 404 and method == "DELETE":
            return None  # removing a label that is not there
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return None
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    # Issues -----------------------------------------------------------------

    def issues_with_label(self, label: str) -> list[dict]:
        items = self._req("GET", "/issues", params={"labels": label, "state": "open", "per_page": 50})
        return [i for i in items if "pull_request" not in i]

    def open_issues(self) -> list[dict]:
        items = self._req("GET", "/issues", params={"state": "open", "per_page": 100})
        return [i for i in items if "pull_request" not in i]

    def create_issue(self, title: str, body: str) -> dict:
        return self._req("POST", "/issues", json={"title": title, "body": body})

    def close(self, number: int) -> None:
        """Close an issue or a pull request."""
        self._req("PATCH", f"/issues/{number}", json={"state": "closed"})

    def issue(self, number: int) -> dict:
        return self._req("GET", f"/issues/{number}")

    def comments(self, number: int) -> list[dict]:
        return self._req("GET", f"/issues/{number}/comments", params={"per_page": 100})

    def comment(self, number: int, body: str) -> dict:
        return self._req("POST", f"/issues/{number}/comments", json={"body": body})

    def add_labels(self, number: int, *labels: str) -> None:
        self._req("POST", f"/issues/{number}/labels", json={"labels": list(labels)})

    def remove_label(self, number: int, label: str) -> None:
        self._req("DELETE", f"/issues/{number}/labels/{label}")

    def ensure_label(self, name: str, color: str, description: str) -> None:
        resp = self._http.post(
            f"/repos/{self.repo}/labels",
            json={"name": name, "color": color, "description": description},
        )
        if resp.status_code not in (201, 422):  # 422: already exists
            resp.raise_for_status()

    # Pull requests ----------------------------------------------------------

    def default_branch(self) -> str:
        return self._http.get(f"/repos/{self.repo}").raise_for_status().json()["default_branch"]

    def prs_with_label(self, label: str) -> list[dict]:
        return [
            i
            for i in self._req("GET", "/issues", params={"labels": label, "state": "open", "per_page": 50})
            if "pull_request" in i
        ]

    def open_prs(self) -> list[dict]:
        return self._req("GET", "/pulls", params={"state": "open", "per_page": 100})

    def branches(self, prefix: str) -> list[str]:
        refs = self._req("GET", f"/git/matching-refs/heads/{prefix}")
        return [r["ref"].removeprefix("refs/heads/") for r in refs]

    def delete_branch(self, name: str) -> None:
        self._req("DELETE", f"/git/refs/heads/{name}")

    def pr(self, number: int) -> dict:
        return self._req("GET", f"/pulls/{number}")

    def pr_diff(self, number: int) -> str:
        resp = self._http.get(
            f"/repos/{self.repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        resp.raise_for_status()
        return resp.text

    def find_pr(self, head_branch: str) -> dict | None:
        owner = self.repo.split("/")[0]
        found = self._req("GET", "/pulls", params={"head": f"{owner}:{head_branch}", "state": "open"})
        return found[0] if found else None

    def open_pr(self, head: str, base: str, title: str, body: str) -> dict:
        return self._req("POST", "/pulls", json={"head": head, "base": base, "title": title, "body": body})

    def review(self, number: int, commit_id: str, body: str) -> dict:
        # COMMENT, never APPROVE: the token may belong to the PR's author, and a bot
        # approval should not count towards branch protection anyway.
        return self._req(
            "POST",
            f"/pulls/{number}/reviews",
            json={"commit_id": commit_id, "body": body, "event": "COMMENT"},
        )
