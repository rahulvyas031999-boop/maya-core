FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user for basic container hardening, and pre-create the
# workspace dir so the app doesn't need root to create it at runtime.
RUN useradd -m appuser && \
    mkdir -p /app/workspace && \
    chown -R appuser:appuser /app

USER appuser

# NOTE ON PERSISTENCE: maya_jobs.db, maya_state.json, and /app/workspace
# live inside the container filesystem by default, which is WIPED on every
# redeploy/restart on platforms like Render. If you need tasks/memory/files
# to survive redeploys, attach a persistent disk on your host platform and
# mount it at a path, then point these env vars at it, e.g.:
#   DB_PATH=/data/maya_jobs.db
#   STATE_FILE_PATH=/data/maya_state.json
#   WORKSPACE_PATH=/data/workspace
ENV DB_PATH=maya_jobs.db
ENV STATE_FILE_PATH=maya_state.json
ENV WORKSPACE_PATH=workspace

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
