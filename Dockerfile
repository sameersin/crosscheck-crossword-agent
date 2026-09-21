# Keep the Python patch version explicit; update it deliberately with the runtime lock.
FROM python:3.11.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install the fully pinned runtime graph without resolving extras or building packages.
COPY requirements-runtime.lock /tmp/requirements-runtime.lock
RUN python -m pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
        -r /tmp/requirements-runtime.lock \
    && rm /tmp/requirements-runtime.lock

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/artifacts/private \
    && chown 10001:10001 /app/artifacts/private

# Preserve /app/src so config.PROJECT_ROOT resolves to /app.
COPY src/crossword_agent/ ./src/crossword_agent/
COPY data/ ./data/
COPY artifacts/evaluation/report.json ./artifacts/evaluation/report.json
COPY artifacts/user-puzzles/manifest.json \
     artifacts/user-puzzles/*.puzzle.json \
     artifacts/user-puzzles/*.result.json \
     artifacts/user-puzzles/*.verification.json \
     ./artifacts/user-puzzles/

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).close()"]

CMD ["python", "-m", "uvicorn", "crossword_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
