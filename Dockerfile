# The worker: three workflows and the two agents in one Python process.
# Base images come from the ECR Public mirror of Docker Official Images, not Docker Hub.
FROM public.ecr.aws/docker/library/python:3.12-slim

# git: the activities clone, commit and push. The Claude CLI ships inside the
# claude-agent-sdk wheel, so no Node.js is needed.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project

COPY factory ./factory
COPY agents ./agents

# The agents' test runs use `python -m pytest`, so the venv goes first on PATH.
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app \
    WORK_ROOT=/work

RUN useradd --uid 10001 --create-home --home-dir /home/app app \
 && mkdir -p /work && chown app /work
USER 10001

CMD ["python", "-m", "factory.main"]
