FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    BREAD_CACHE=/app/.cache/llm.sqlite
WORKDIR /app

COPY pyproject.toml README.md ./
COPY bread ./bread
RUN pip install ".[dev]"

COPY tests ./tests
RUN useradd --create-home bread && mkdir -p /app/runs /app/.cache && chown -R bread /app
USER bread

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/healthz')"
CMD ["python", "-m", "bread"]
