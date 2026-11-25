# Diagrid Agent Factory

Two LLM agents turn GitHub issues into pull requests and review pull requests.
A workflow runs every step around them: it checks their changes, runs the tests,
and waits for a person to reply `/approve` before it opens a pull request.
People choose the issues and do the merging.

It runs on [Dapr Workflows](https://docs.dapr.io/developing-applications/building-blocks/workflow/),
[Dapr Agents](https://github.com/dapr/dapr-agents) and
[Diagrid](https://www.diagrid.io/catalyst). Diagrid runs coding agents on its own
repositories the same way; this is a smaller version of that setup.

## What runs

The demo runs all the time, so there is nothing to start.

| Piece | What it is |
|---|---|
| Worker | One pod on Diagrid's demo Kubernetes cluster, namespace `agent-factory`: the three workflows and both agents. Argo CD deploys it from `deploy/` on every merge to `main`. |
| Diagrid | Project `agent-factory`. It runs the workflows and keeps their state, so a run survives a restart of the pod. |
| GitHub | This repository. The worker watches its issues and pull requests, and comments and pushes as a bot account. |
| LLM | OpenAI `gpt-4.1`, through the Dapr Conversation component `llm-provider` in the Diagrid project. |

How it is deployed, and its secrets: [deploy/README.md](deploy/README.md).

## Run the demo

1. **Reset.** Open **Actions → [Reset demo](https://github.com/diagrid-labs/diagrid-agent-factory/actions/workflows/reset-demo.yaml) → Run workflow**.
   It stops the agents' running workflows, closes their issues and pull requests,
   deletes their `agent/*` branches and puts the bugs back in `sample-app/`. The
   run's summary lists what it closed.
2. **Open a demo issue** as an org member: **New issue**, then one of the three
   Demo templates below. No label needed.
3. **Watch the issue.** Within 30 seconds the worker claims it and comments with
   a link to its run. Each implementer and reviewer round is posted as a comment.
4. **Show the run.** The link opens the run in the Diagrid console: each step,
   the two agent runs, and the wait for approval.
5. **Approve.** When the issue asks, reply `/approve` as an org member, and the
   workflow opens the pull request. `/reject` stops it.
6. **Review bot.** Label any pull request `agent:review` and the reviewer agent
   posts a review on it.

### Demo issues

Each one is a bug or a small feature in `sample-app/pricing.py` with one clear
fix, so you know what the pull request will change. The code differs a little
between runs, since the agents are LLMs.

| Open it | The issue | The pull request you get |
|---|---|---|
| [Demo 1](https://github.com/diagrid-labs/diagrid-agent-factory/issues/new?template=demo-1-short-pnl.md) | Short positions show the wrong sign in P&L | `position_pnl` returns a loss for a losing short, plus a test |
| [Demo 2](https://github.com/diagrid-labs/diagrid-agent-factory/issues/new?template=demo-2-jpy-pips.md) | Spread and pip value are 100x off for JPY pairs | a 0.01 pip for JPY pairs in `spread_in_pips` and `pip_value`, plus tests |
| [Demo 3](https://github.com/diagrid-labs/diagrid-agent-factory/issues/new?template=demo-3-margin.md) | Add `margin_required(units, price, leverage)` | the new function with its checks, plus tests |

Demo 1 is the quickest: one line of code and one test, about 3 minutes to the
approval request. Any other issue works too, but its result is harder to predict.

## Who does what

![One issue from label to merge: people label, approve and merge; the workflow claims, checks, asks and opens the PR; the agents change and review the code](docs/who-does-what.png)

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

![Architecture: grey steps are plain code, purple steps call an LLM, orange waits for a person](docs/architecture.png)

The two agent steps are the only ones that call an LLM. Each runs as a child
workflow; every other step is a workflow activity in plain code.

## Workflows and steps

Five workflow types run: three of ours and the two agents. Only the agents are
child workflows. `issue_watch` starts the other two as their own top-level runs,
with a fixed id per issue or PR commit, so a restart of the watcher leaves them running.

```
issue_watch  (polls every 30 s, then continue-as-new)
 ├─ starts ─► implement_issue  issue-<repo>-<N>
 │              ├─ child ─► implementer agent  …-implement-<round>
 │              ├─ child ─► reviewer agent     …-review-<round>
 │              └─ waits for "approval"  ◄─ /approve or /reject
 └─ starts ─► review_pull_request  review-<repo>-<PR>-<sha>
                └─ child ─► reviewer agent     …-review
```

**`issue_watch`** (one run, always on)

| Step | Kind |
|---|---|
| `poll`: list labelled issues and PRs, start a run for each new one, forward `/approve` and `/reject` | activity |
| wait `POLL_SECONDS` (30) | timer |
| restart with the same settings, so the history stays small | continue-as-new |

**`implement_issue`** (one run per issue)

| # | Step | Kind |
|---|---|---|
| 1 | `claim_issue`: label it, comment with a link to the run | activity |
| 2 | `prepare_workspace`: clone onto `agent/issue-N` | activity |
| 3 | implementer agent changes the code | child workflow |
| 4 | `verify_workspace`: the workflow lists the changes and runs the tests | activity |
| 5 | reviewer agent reviews the diff, then `comment` posts the round | child workflow, activity |
| | steps 3–5 again if needed, at most 2 rounds | |
| 6 | `request_approval`: post the diff, label `agent:awaiting-approval` | activity |
| 7 | the `approval` event, or a 24-hour timer, whichever comes first | event, timer |
| 8 | `open_pull_request`: commit, push, open the PR | activity |
| 9 | `set_labels` and `comment`: `agent:done` and the PR link | activities |

When a limit runs out, `set_labels` and `comment` label the issue `agent:needs-human` instead.

**`review_pull_request`** (one run per PR head commit)

| Step | Kind |
|---|---|
| `fetch_pr`: the PR and its diff | activity |
| `prepare_workspace`: check out the head commit | activity |
| reviewer agent reviews it | child workflow |
| `post_review`: a COMMENT review and the `agent:reviewed` label | activity |

**The agents** are Dapr Agents `DurableAgent` runs (`dapr.agents.implementer.workflow`,
`dapr.agents.reviewer.workflow`). Inside them each LLM call, through the
`llm-provider` component, and each tool call is its own activity. The tools are
`list_files`, `read_file`, `search_code`, `run_tests`, and `write_file` for the
implementer only.

The checkout the agents work in lives on the worker's persistent disk until
`/approve`, so a restart or redeploy mid-run loses nothing.

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

## How Diagrid runs this in production

Diagrid's own setup, agentic engineering, splits pull request work into
**lanes**. A lane is one kind of work with its own agent file, its own worker and
its own Diagrid app, named `<engineer>-<lane>`. A monitor workflow watches each
engineer's pull requests and hands an item to the right lane with a cross-app
child-workflow call; the lane runs its agent as a child workflow, checks the
result against git, and reports back.

| Lane | Takes | Does |
|---|---|---|
| implementer | a Linear issue | writes the change, runs a review loop, opens the PR |
| reviewer | a review request | reviews the PR from a read-only checkout |
| ci-fixer | a failing check | fixes it and pushes |
| pr-comment-resolver | unresolved review comments | answers them or changes the code |
| rebaser | a merge conflict | merges the base branch, resolves conflicts |
| merger | an approved PR | merges it once it is approved and green |

This demo is the implementer and reviewer lanes, cut down to run as one hosted service.

| | This demo | Production (agentic engineering) |
|---|---|---|
| Where it starts | A GitHub issue or label, polled every 30 s | Linear issues and a PR monitor |
| Apps | One worker app with both agents | One Diagrid app per lane per engineer |
| Where workers run | One pod on the demo cluster | Each engineer's own machine, with their own logins |
| Model | OpenAI `gpt-4.1` through Dapr Conversation | Claude Opus through the Claude Agent SDK, effort set per lane |
| Checkouts | A persistent disk, one clone per run | Shared repo mirrors, a checkout per item, cleaned up when it ends |
| Isolation | Five tools held to one folder | An OS sandbox per run, plus the same tool limits |
| Approval | `/approve` on the issue | The engineer approves the head before a push to a public repo |
| Merge | A person | The merger lane, once approved and green |
| Watching | The Diagrid console | The console and a board of every PR's lane and state |

The workflow rules are the same in both: the workflow owns the steps, checks the
agent's work against git and the tests, and holds the token.

## Materials

| What | Where |
|---|---|
| Portal page: run guide, code snippets, links | [demo portal](https://diagrid-demo-portal.westeurope.cloudapp.azure.com/demos/agent-factory/) |
| Diagrid console | [project `agent-factory`, Workflows](https://catalyst.diagrid.io/workflows?org=79a0006b-2ca1-4d95-a0f9-809467822799&project=agent-factory) |
| Reset the demo | [Actions → Reset demo](https://github.com/diagrid-labs/diagrid-agent-factory/actions/workflows/reset-demo.yaml) |
| Introduction and presenter guide | [Claude doc](https://claude.ai/artifact/6aZdj9w7yVX2Mr3bDqjrUi) |
| Slides (draft) | [Google Slides](https://docs.google.com/presentation/d/1k0s8I3gK07ekrm_JaMWaxDgIRj5yrtRcTGrB-sPfzOc/edit) |
| Architecture diagram, editable | [Lucid](https://lucid.app/lucidchart/b5f0bafa-5591-48df-8f2c-5dcd964cefd3/edit) |
| Diagrams in this repo | `docs/architecture.png`, `docs/who-does-what.png` (SVG beside each) |
| Deploy, secrets, teardown | [deploy/README.md](deploy/README.md) |

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
scripts/             reset_demo.py (what Reset demo runs) and the seeded demo issues
Dockerfile, deploy/  the hosted copy on Kubernetes, synced by Argo CD (deploy/README.md)
```
