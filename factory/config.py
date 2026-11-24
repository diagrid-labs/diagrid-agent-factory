"""Settings, read once from the environment (and .env) at startup."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Labels are the whole interface: a person adds one, the agents move it along.
LABEL_IMPLEMENT = "agent:implement"
LABEL_IN_PROGRESS = "agent:in-progress"
LABEL_AWAITING_APPROVAL = "agent:awaiting-approval"
LABEL_DONE = "agent:done"
LABEL_NEEDS_HUMAN = "agent:needs-human"
LABEL_REVIEW = "agent:review"
LABEL_REVIEWED = "agent:reviewed"


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    # Fall back to the GitHub CLI's login, handy on a laptop.
    if shutil.which("gh"):
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    raise SystemExit("Set GITHUB_TOKEN, or log in with `gh auth login`.")


@dataclass(frozen=True)
class Settings:
    """What the workflows need. Passed into each workflow as input, so replays see the same values."""

    repo: str  # owner/name the agents watch and open PRs on
    scope: str  # the directory inside the repo the implementer may change
    test_command: str
    poll_seconds: int
    max_review_rounds: int
    require_approval: bool
    approval_timeout_hours: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Runtime:
    """Process-level settings that never go into workflow history."""

    settings: Settings
    github_token: str
    work_root: Path
    backend: str
    claude_model: str
    llm_component: str
    state_store: str
    registry_store: str


def load() -> Runtime:
    load_dotenv(ROOT / ".env")
    repo = os.environ.get("TARGET_REPO", "").strip()
    if repo.count("/") != 1:
        raise SystemExit("Set TARGET_REPO to owner/name, for example diagrid-labs/catalyst-agent-factory.")
    settings = Settings(
        repo=repo,
        scope=os.environ.get("TARGET_SCOPE", "sample-app").strip("/"),
        test_command=os.environ.get("TEST_COMMAND", "python -m pytest -q sample-app"),
        poll_seconds=int(os.environ.get("POLL_SECONDS", "30")),
        max_review_rounds=int(os.environ.get("MAX_REVIEW_ROUNDS", "2")),
        require_approval=_bool("REQUIRE_APPROVAL", True),
        approval_timeout_hours=int(os.environ.get("APPROVAL_TIMEOUT_HOURS", "24")),
    )
    work_root = Path(os.environ.get("WORK_ROOT", ROOT / ".work")).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    return Runtime(
        settings=settings,
        github_token=_github_token(),
        work_root=work_root,
        backend=os.environ.get("AGENT_BACKEND", "claude").strip().lower(),
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"),
        llm_component=os.environ.get("LLM_COMPONENT", "llm-provider"),
        state_store=os.environ.get("STATE_STORE", "kvstore"),
        registry_store=os.environ.get("REGISTRY_STORE", os.environ.get("STATE_STORE", "kvstore")),
    )
