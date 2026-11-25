# Deploy

A persistent copy of this demo runs on `demo-production-catalyst`, namespace `agent-factory`,
against the Diagrid project `agent-factory` in the Demo Production Catalyst org. It watches
`diagrid-labs/diagrid-agent-factory` and works on issues opened there by org members.

Merging to `main` deploys it. The **Publish** workflow runs the tests, builds the worker image,
pushes it to `public.ecr.aws/d3f9w4q8/agent-factory/worker:<commit>` (GitHub OIDC, role
`github-actions-ecr-push` in account `214575257891`, as the other demos do), and commits the new
tag to `deploy/kustomization.yaml`. Argo CD (Application `agent-factory`,
`deploy/argocd/application.yaml`) syncs `deploy/` and rolls it out. It also reverts manual
changes to anything in `deploy/`, so change the files instead. Secrets stay out of git and Argo
CD: create them by hand as below.

| Piece | Where |
|---|---|
| Worker (`deployment.yaml`) | Deployment `agent-factory`: the three workflows and both agents in one pod |
| Diagrid | project `agent-factory`, App ID `agent-factory`, managed workflow store and `kvstore` |
| GitHub | repo `diagrid-labs/diagrid-agent-factory`, comments and PRs as the bot account |
| LLM | Dapr Conversation component `llm-provider` (OpenAI `gpt-4.1`), with the OpenAI key the other demos use |

Only one worker may watch a repository. Stop any local `diagrid dev run` pointed at the same
`TARGET_REPO` before this one starts, or both pick up the same issues.

## Deploy

First-time setup only. Run everything from the repository root.

### 1. Registry

Create the ECR Public repository `agent-factory/worker` in account `214575257891`, and make sure
the `github-actions-ecr-push` role's trust policy allows `repo:diagrid-labs/diagrid-agent-factory:*`.

### 2. Diagrid project

```bash
diagrid login                 # production, then pick the Demo Production Catalyst org
diagrid project create agent-factory --enable-managed-workflow --deploy-managed-kv --wait
diagrid appid create agent-factory --project agent-factory --wait

# The LLM: the same OpenAI key as verifiable-execution-demo, read from its secret, never printed.
diagrid component create llm-provider --type conversation.openai --project agent-factory \
  --metadata key="$(kubectl --context demo-production-catalyst -n verifiable-execution-demo \
    get secret openai -o jsonpath='{.data.apiKey}' | base64 -d)" \
  --metadata model=gpt-4.1 --wait
```

### 3. Secrets

```bash
# kubectl scoped to this demo. A function, because zsh would not split a variable into arguments.
kaf() { kubectl --context demo-production-catalyst -n agent-factory "$@"; }
kubectl --context demo-production-catalyst create namespace agent-factory

kaf create secret generic catalyst-agent-factory \
  --from-literal=apiToken="$(diagrid appid get agent-factory -p agent-factory -o json | jq -r .status.apiToken)" \
  --from-literal=grpcEndpoint="$(diagrid project get agent-factory -o json | jq -r .status.endpoints.grpc.url)" \
  --from-literal=httpEndpoint="$(diagrid project get agent-factory -o json | jq -r .status.endpoints.http.url)"

# The bot account's fine-grained token on diagrid-labs/diagrid-agent-factory:
# contents, issues and pull requests read/write, metadata read.
kaf create secret generic github-bot --from-literal=token="$GITHUB_BOT_TOKEN"
```

Keep the token in 1Password, never in this repo.

### 4. Hand it to Argo CD

Argo CD reads this private repo with a read-only deploy key: public half in the repo's
Settings › Deploy keys, private half in the `repo-diagrid-agent-factory` Secret in the `argocd`
namespace (label `argocd.argoproj.io/secret-type=repository`). Then:

```bash
kubectl --context demo-production-catalyst apply -f deploy/argocd/application.yaml
kaf logs deploy/agent-factory | grep -E "agents:|ready:"
```

The log ends with `ready: label an issue 'agent:implement' ...` once the worker is connected.

## Run the demo

Open an issue on `diagrid-labs/diagrid-agent-factory` as an org member. Within 30 seconds the
worker labels it and comments with its workflow run. The rest is in the [README](../README.md).
Run `scripts/reset_demo.py --project agent-factory` with the production CLI login to reset it.

## Tear down

```bash
kubectl --context demo-production-catalyst -n argocd delete application agent-factory
kubectl --context demo-production-catalyst delete namespace agent-factory
diagrid project delete agent-factory
```

Delete the Application first, or Argo CD recreates everything.

## Don't

- Run two replicas with different settings: the watcher keeps the settings it started with
  until a worker restarts it.
- Widen `.dockerignore`. The image is public, so it allowlists only the files the build needs.
