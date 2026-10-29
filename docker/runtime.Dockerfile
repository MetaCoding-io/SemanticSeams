# Runtime image: seams_runtime serving one app's committed generated route module and templates.
# Build from the repository root: docker build -f docker/runtime.Dockerfile .
# The build args choose which app's generated code is baked in (default: the chat app):
#   docker build -f docker/runtime.Dockerfile \
#     --build-arg SEAMS_APP_DIR=examples/other-app --build-arg SEAMS_ROUTES_FILE=other_api.py .
# The second app is the expense tutorial's last checkpoint: its
# examples/expenses/chapter-08/compose.override.yaml builds this image with
# SEAMS_APP_DIR=examples/expenses/chapter-08 and SEAMS_ROUTES_FILE=expense_api.py.
# The app dir must hold generated/<routes file>, generated/templates/ and seed.json;
# the seed file is required, so an app without seed data commits a seed.json of `{}`.
# The model (the TriG plus its BPMN/DMN payloads) is not baked in: the generated
# compose file bind-mounts it read-only at /model and SEAMS_MODEL names the TriG
# the runtime loads.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY seams_runtime/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# Declared before the COPY and ENV lines that use them.
ARG SEAMS_APP_DIR=examples/chat-app
ARG SEAMS_ROUTES_FILE=chat_api.py

COPY seams_runtime /app/seams_runtime
COPY ${SEAMS_APP_DIR}/generated/${SEAMS_ROUTES_FILE} /app/${SEAMS_ROUTES_FILE}
COPY ${SEAMS_APP_DIR}/generated/templates /app/templates
COPY ${SEAMS_APP_DIR}/seed.json /app/seed.json

# SEAMS_DB lives on the /data volume so process instances survive a restart.
ENV SEAMS_TEMPLATES=/app/templates \
    SEAMS_ROUTES=/app/${SEAMS_ROUTES_FILE} \
    SEAMS_DB=/data/seams.sqlite
RUN mkdir -p /data
VOLUME /data

EXPOSE 8000
CMD ["python", "-m", "seams_runtime.host"]
