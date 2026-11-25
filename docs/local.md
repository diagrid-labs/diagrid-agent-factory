# Run a copy on your laptop

For working on the factory itself. The demo already runs on the cluster: see the
[README](../README.md).

Only one worker may watch a repository, so point yours at a fork, not at
`diagrid-labs/diagrid-agent-factory`.

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), the [Diagrid CLI](https://docs.diagrid.io/catalyst/references/cli-reference/intro/), a Diagrid organization, and a fork of this repository (the agents only change `sample-app/`).

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

## Reset your copy

`scripts/reset_demo.py` puts everything back where it started: it terminates the
agents' running workflows, closes their PRs and deletes the `agent/*` branches,
closes the demo issues, restores `sample-app/` from the `demo-baseline` tag (so
the bugs are back even after you merged fixes), clears `.work/`, and opens the
demo issues again.

```bash
uv run python scripts/reset_demo.py                  # dry run: shows what it would do
uv run python scripts/reset_demo.py --yes --label    # reset and start the agents
uv run python scripts/reset_demo.py --yes --label --only 1   # one issue, so you know the PR to expect
```
