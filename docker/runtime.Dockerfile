# chat_api image: seams_runtime serving the committed generated route module and templates.
# Build from the repository root: docker build -f docker/runtime.Dockerfile .
# The model (chat-app.trig, chat_process.bpmn, routing.dmn) is not baked in; the
# generated compose.yaml bind-mounts it read-only at /model.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY seams_runtime/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY seams_runtime /app/seams_runtime
COPY examples/chat-app/generated/chat_api.py /app/chat_api.py
COPY examples/chat-app/generated/templates /app/templates
COPY examples/chat-app/seed.json /app/seed.json

# SEAMS_DB lives on the /data volume so process instances survive a restart.
ENV SEAMS_TEMPLATES=/app/templates \
    SEAMS_ROUTES=/app/chat_api.py \
    SEAMS_DB=/data/seams.sqlite
RUN mkdir -p /data
VOLUME /data

EXPOSE 8000
CMD ["python", "-m", "seams_runtime.host"]
