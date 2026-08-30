FROM python:3.12-slim

# Use uv for dependency resolution and the isolated application environment.
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

WORKDIR /app
RUN mkdir -p /app/reference/crawlers/douyin/web /app/state /app/downloads
COPY yt-dlp /app/yt-dlp
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/uv.lock /app/backend/uv.lock
RUN uv sync --project /app/backend --no-install-project
COPY backend /app/backend
COPY Douyin_TikTok_Download_API/crawlers/douyin/web/abogus.py /app/reference/crawlers/douyin/web/abogus.py
ENV VIRTUAL_ENV=/app/backend/.venv PATH="/app/backend/.venv/bin:$PATH" PYTHONPATH=/app:/app/yt-dlp REFERENCE_REPO_DIR=/app/reference
CMD ["uv", "run", "--project", "/app/backend", "python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
