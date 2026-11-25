import subprocess
from pathlib import Path

import pytest

from factory import agents, prompts, tools
from factory.config import ROOT


def test_verdict_takes_the_last_one():
    text = "VERDICT: REQUEST_CHANGES\n... fixed ...\nverdict: approve"
    assert prompts.verdict(text) == "APPROVE"
    assert prompts.verdict("looks fine") is None


def test_agent_text():
    assert prompts.agent_text({"role": "assistant", "content": "hi"}) == "hi"
    assert prompts.agent_text(None) == ""


def test_agent_specs_parse():
    specs = {p.stem: agents.read_spec(p) for p in (ROOT / "agents").glob("*.md")}
    assert set(specs) == {"implementer", "reviewer"}
    assert "write_file" not in specs["reviewer"].tools
    assert specs["implementer"].instructions


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "issue-1"
    (ws / "app").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    (ws / "app" / "a.py").write_text("x = 1\n")
    tools.configure(tmp_path, "app", "python -c pass")
    return ws


def test_write_is_held_to_scope(workspace: Path):
    tools.write_file(workspace=str(workspace), path="app/b.py", content="y = 2\n")
    assert (workspace / "app" / "b.py").exists()
    with pytest.raises(Exception):
        tools.write_file(workspace=str(workspace), path="README.md", content="no")
    with pytest.raises(Exception):
        tools.read_file(workspace=str(workspace), path="../../etc/passwd")


def test_only_agent_workspaces(workspace: Path, tmp_path: Path):
    with pytest.raises(Exception):
        tools.list_files(workspace=str(tmp_path))


def test_search_and_tests(workspace: Path):
    assert "app/a.py:1" in tools.search_code(workspace=str(workspace), text="x = 1")
    assert tools.run_tests(workspace=str(workspace)).startswith("PASSED")


def test_auto_pickup_only_new_trusted_issues():
    from factory.activities import needs_pickup

    assert needs_pickup({"author_association": "MEMBER", "labels": []})
    assert needs_pickup({"author_association": "OWNER", "labels": [{"name": "bug"}]})
    assert not needs_pickup({"author_association": "NONE", "labels": []})
    assert not needs_pickup({"author_association": "MEMBER", "labels": [{"name": "agent:needs-human"}]})
