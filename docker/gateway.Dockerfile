# llm_gateway image: the OpenAI-compatible gateway (upstream proxy, or stub without a key).
# Build from the repository root: docker build -f docker/gateway.Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY seams_gateway/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY seams_gateway /app/seams_gateway

EXPOSE 8000
CMD ["python", "-m", "seams_gateway"]
