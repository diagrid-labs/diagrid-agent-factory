#!/usr/bin/env bash
# Create the Catalyst project and the LLM component the agents use.
#   OPENAI_API_KEY=... scripts/setup_catalyst.sh [project]
# or ANTHROPIC_API_KEY=... to use Claude instead.
set -euo pipefail
PROJECT="${1:-agent-factory}"

diagrid project create "$PROJECT" --enable-managed-workflow --deploy-managed-kv \
  --ignore-if-exists --wait
diagrid project use "$PROJECT"

if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  diagrid component create llm-provider --type conversation.anthropic \
    --metadata key="$ANTHROPIC_API_KEY" --metadata model="${LLM_MODEL:-claude-sonnet-5-5}" \
    --ignore-if-exists --wait
elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
  diagrid component create llm-provider --type conversation.openai \
    --metadata key="$OPENAI_API_KEY" --metadata model="${LLM_MODEL:-gpt-4.1}" \
    --ignore-if-exists --wait
else
  echo "Set ANTHROPIC_API_KEY or OPENAI_API_KEY" >&2
  exit 1
fi
echo "Project $PROJECT is ready. Next: diagrid dev run --project $PROJECT --file dev-catalyst.yaml"
