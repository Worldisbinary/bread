FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/app/.models
WORKDIR /app

COPY pyproject.toml README.md ./
COPY rlife ./rlife
# Install with the embedding model baked into the image, so containers start offline.
RUN pip install ".[embeddings,dev]" \
    && python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/.models')"

COPY tests ./tests
RUN useradd --create-home rlife && mkdir -p /app/runs /app/.cache && chown -R rlife /app
USER rlife

EXPOSE 8000 9101
ENTRYPOINT ["python", "-m", "rlife"]
CMD ["serve", "runs/ranking/new.db", "runs/ranking/hot.db", "runs/ranking/engagement.db"]
