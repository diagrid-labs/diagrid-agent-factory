# Diagrid Agent Factory

Two LLM agents turn GitHub issues into pull requests and review pull requests.
A workflow runs every step around them: it checks their changes, runs the tests,
and waits for a person to reply `/approve` before it opens a pull request.
People choose the issues and do the merging.

It runs on [Dapr Workflows](https://docs.dapr.io/developing-applications/building-blocks/workflow/),
[Dapr Agents](https://github.com/dapr/dapr-agents) and
[Diagrid](https://www.diagrid.io/catalyst). Diagrid runs coding agents on its own
repositories the same way; this is a smaller version of that setup.

## Who does what

| | People | Workflow | Agents |
|---|---|---|---|
| Start work on an issue or a PR (a label) | yes | | |
| Change code and add tests | | | implementer, inside one directory |
| Decide the change is done | | yes, from git and the test run | |
| Review a diff | yes | | reviewer |
| Approve opening a pull request (`/approve`) | yes | | |
| Hold the token, push, open the PR, set labels | | yes | |
| Merge | yes | | |

## How work moves

Label an issue `agent:implement` and the factory works on it. With
`AUTO_PICKUP=true` it starts as soon as an owner, member or collaborator opens
the issue. The factory:

1. claims the issue and clones the repository,
2. runs an **implementer agent** that changes the code and adds a test,
3. checks the work itself: which files changed, and whether the tests pass,
4. runs a separate **reviewer agent** on the diff, and sends its findings back to the implementer (up to 2 rounds),
5. asks a person to reply `/approve` on the issue, with the diff attached,
6. pushes a branch and opens the pull request.

Label a pull request `agent:review`, whoever opened it, and the reviewer agent
posts a review on it.

Every step leaves a comment on the issue, so the thread is the record of what
happened and why. When a limit runs out (no change, no approved change after 2
rounds, a `/reject`, or no answer in 24 hours), the issue is labelled
`agent:needs-human` with the agent's last summary.

![Architecture: which steps are plain code, which call an LLM, and which wait for a person](docs/architecture.png)

The two agent steps are the only ones that call an LLM. Each runs as a child
workflow; every other step is a workflow activity in plain code.

## The rules, and where they live

| Rule | Where |
|---|---|
| **The workflow owns the process.** The order of steps, the review loop, the round limit and the approval gate are plain code. The agents never decide whether they are done. | [`factory/workflows.py`](factory/workflows.py) |
| **The workflow checks the agent's work.** After the implementer finishes, the workflow lists the changed files and runs the tests itself. | `verify_workspace` in [`factory/activities.py`](factory/activities.py) |
| **A fresh reviewer.** A second agent with no shared context reviews the diff and ends with `VERDICT: APPROVE` or `REQUEST_CHANGES`. | [`agents/reviewer.md`](agents/reviewer.md) |
| **Least privilege.** Agents get five tools: list, read, search, write (inside one directory only) and run tests. They never see the GitHub token and cannot run git, push, label or merge. With the Claude backend, Claude's own shell and edit tools are switched off. | [`factory/tools.py`](factory/tools.py) |
| **Only trusted people count.** Only `/approve` and `/reject` from owners, members and collaborators count, and `AUTO_PICKUP` only picks up issues they opened. The review bot comments; it never approves, so it does not count toward branch protection. | [`factory/github.py`](factory/github.py) |
| **Agents are configuration.** Each agent's role, goal, tools, iteration limit and instructions live in one file. Add a file to add an agent. | [`agents/`](agents) |
| **One run per work item.** An issue or a PR head commit is one workflow instance with a stable id, so the same item is never worked on twice. | `_start_once` in [`factory/activities.py`](factory/activities.py) |

Each of these is a policy you can change in a few lines: open the PR without
asking, ask two people, auto-merge when the tests and the reviewer pass, or allow
more rounds.

## Extending it

The same pattern covers more of the pull request lifecycle. Diagrid's own setup
also has agents that fix failing CI, answer review comments and rebase
conflicting pull requests. Each is one more workflow that reuses the activities
here, plus one more file in `agents/`.

To use GitLab instead of GitHub, replace [`factory/github.py`](factory/github.py).
The workflows only call it through the activities, and need the same few calls
against the GitLab API: list issues by label, comment, set labels, open a merge
request, post a review note.

## Why workflows

Each step runs on Diagrid as a durable workflow step, so the rules hold across
restarts. An agent run, a review round or a day-long wait for approval survives a
restart of the worker and continues from its last completed step, without
repeating work. Start more workers with the same app id
and Diagrid spreads the runs across them. Every run, step and agent run shows
in the Diagrid console.

## Run it

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), the [Diagrid CLI](https://docs.diagrid.io/catalyst/references/cli-reference/intro/), a Diagrid organization, and a GitHub repository you can push to (a fork of this one works: the agents only change `sample-app/`).

```bash
git clone https://github.com/diagrid-labs/diagrid-agent-factory && cd diagrid-agent-factory
uv sync
cp .env.example .env        # set TARGET_REPO to your fork
diagrid login
diagrid project create agent-factory --enable-managed-workflow --deploy-managed-kv
```

Pick how the agents think (`AGENT_BACKEND` in `.env`):

- `claude` (default): the Claude Agent SDK, using this machine's Claude login, or `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY`. Nothing to create in Diagrid.
- `conversation`: any LLM behind a Dapr Conversation component (OpenAI, Anthropic, Bedrock, Azure OpenAI, Ollama, ...). Create it with:

  ```bash
  OPENAI_API_KEY=... scripts/setup_diagrid.sh agent-factory      # or ANTHROPIC_API_KEY=...
  ```

Start the worker, connected to Diagrid:

```bash
diagrid dev run --project agent-factory --file dev-diagrid.yaml --approve
```

The first run creates the `agent:*` labels on the repository. Then open the demo
issues and hand them to the implementer:

```bash
uv run python scripts/seed_issues.py --label
```

Follow along on the issues (each review round is posted as a comment), in the
worker's log, and in the Diagrid console's workflow view. Reply `/approve` on an
issue when asked, and a pull request opens. Then label it `agent:review` to have
the reviewer agent review it.

Comments, pull requests and reviews appear under the GitHub account whose token
the worker uses. Give it a bot account's token to keep them apart from yours.

### Run it again

`scripts/reset_demo.py` puts everything back where it started: it terminates the
agents' running workflows, closes their PRs and deletes the `agent/*` branches,
closes the demo issues, restores `sample-app/` from the `demo-baseline` tag (so
the bugs are back even after you merged fixes), clears `.work/`, and opens the
demo issues again.

```bash
uv run python scripts/reset_demo.py                  # dry run: shows what it would do
uv run python scripts/reset_demo.py --yes --label    # reset and start the agents
```

The fixes differ a little from run to run, since the agents are LLMs. The
workflow's checks and the review loop keep the outcome the same.

## Layout

```
agents/              agent definitions (the factory's input)
factory/
  main.py            worker: builds the agents, registers workflows and activities
  workflows.py       issue_watch, implement_issue, review_pull_request
  activities.py      every side effect: GitHub, git, tests
  agents.py          agents/*.md -> DurableAgent (Claude or Dapr Conversation)
  tools.py           the tools agents may call, held to the checkout
  github.py          the GitHub calls; swap for GitLab merge requests
  prompts.py         task text and verdict parsing (pure functions)
sample-app/          the code the agents work on, with tests
scripts/             seed_issues.py, reset_demo.py, setup_diagrid.sh
dev-diagrid.yaml     run file for `diagrid dev run`
```
