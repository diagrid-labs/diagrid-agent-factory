# Deploy on Kubernetes

The worker runs as one pod. Diagrid hosts the workflow engine and its state, so
the pod only needs outbound access to Diagrid, GitHub and nothing else.

| File | What it is |
|---|---|
| `deployment.yaml` | The worker Deployment and a 5 GiB volume for the agents' checkouts |
| `kustomization.yaml` | The image to run; CI sets its tag |
| `argocd/application.yaml` | Optional: an Argo CD Application that keeps the cluster in sync with `deploy/` on `main` |

## 1. Diagrid project

```bash
diagrid login
diagrid project create agent-factory --enable-managed-workflow --deploy-managed-kv --wait
diagrid agent create agent-factory --project agent-factory --wait
diagrid component create llm-provider --type conversation.openai --project agent-factory \
  --metadata key="$OPENAI_API_KEY" --metadata model=gpt-4.1 --wait
```

## 2. Secrets

```bash
kubectl create namespace agent-factory

kubectl -n agent-factory create secret generic catalyst-agent-factory \
  --from-literal=apiToken="$(diagrid appid get agent-factory -p agent-factory -o json | jq -r .status.apiToken)" \
  --from-literal=grpcEndpoint="$(diagrid project get agent-factory -o json | jq -r .status.endpoints.grpc.url)" \
  --from-literal=httpEndpoint="$(diagrid project get agent-factory -o json | jq -r .status.endpoints.http.url)" \
  --from-literal=consoleUrl="https://catalyst.diagrid.io/workflows/agent-factory/{instance_id}?org=<org id>&project=agent-factory"

# A bot account's fine-grained token on TARGET_REPO:
# contents, issues and pull requests read/write, metadata read.
kubectl -n agent-factory create secret generic github-bot --from-literal=token="$GITHUB_BOT_TOKEN"
```

`consoleUrl` is optional. With it, the worker's first comment on an issue links to
the run in the Diagrid console.

## 3. Run it

Set `TARGET_REPO` in `deployment.yaml` to your repository, then:

```bash
kubectl apply -k deploy/
kubectl -n agent-factory logs deploy/agent-factory | grep ready:
```

Or let Argo CD do it: point `argocd/application.yaml` at your repository and apply it.

CI (`.github/workflows/publish.yaml`) builds the image on every pull request. On
`main`, with a repository variable `AWS_ROLE_ARN` for an OIDC role that can push to
ECR Public, it also pushes the image and commits the new tag to `kustomization.yaml`.

## Notes

- Run one replica. Two workers watching the same repository pick up the same issues.
- The rollout is `Recreate`, because the checkout volume attaches to one pod at a time.
- The image is public: `.dockerignore` lets in only the files the build needs.

## Tear down

```bash
kubectl delete namespace agent-factory
diagrid project delete agent-factory
```

With Argo CD, delete its Application first, or it recreates everything.
