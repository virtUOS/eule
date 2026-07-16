# Gateway image — FastAPI SSE gateway (docs/07-deployment.md).
# Config is NOT baked in: it is mounted at /config (CONFIG_DIR) so config changes are a
# restart, not a rebuild. Secrets arrive via env (*_env references), never in the image.
FROM python:3.14-slim

# uv for fast, reproducible installs.
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
# Install the project + runtime deps into the system environment (no dev extras).
RUN uv pip install --system --no-cache .

ENV CONFIG_DIR=/config
EXPOSE 8000

# Boot fails fast on invalid config (golden rule 4). One worker: sessions are in-memory
# and single-instance for v1 (see docs/00 §Scaling ceiling).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
