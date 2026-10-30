# llm_gateway image: the OpenAI-compatible gateway (upstream proxy, or stub without a key).
# Build from the repository root: docker build -f docker/gateway.Dockerfile .
# Dependencies come from uv.lock: the semanticseams-gateway workspace member's
# locked set, without the dev group, installed into /opt/venv.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app
# uv checks the whole workspace against the lock, so every member's pyproject.toml
# is needed; no member is installed (--no-install-workspace).
COPY pyproject.toml uv.lock .python-version /app/
COPY packages/seams/pyproject.toml packages/seams/README.md /app/packages/seams/
COPY seams_runtime/pyproject.toml /app/seams_runtime/
COPY seams_gen/pyproject.toml /app/seams_gen/
COPY seams_gateway/pyproject.toml /app/seams_gateway/
COPY viewer/pyproject.toml /app/viewer/
RUN uv sync --locked --no-dev --package semanticseams-gateway --no-install-workspace

COPY seams_gateway /app/seams_gateway

EXPOSE 8000
CMD ["python", "-m", "seams_gateway"]
