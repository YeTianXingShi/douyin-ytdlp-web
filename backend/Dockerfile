FROM node:22-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim

# Use uv for dependency resolution and the isolated application environment.
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

WORKDIR /app
RUN mkdir -p /app/state /app/downloads
COPY VERSION /app/VERSION
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/uv.lock /app/backend/uv.lock
RUN uv sync --locked --project /app/backend --no-install-project
COPY backend /app/backend
COPY --from=frontend-build /frontend/dist /app/frontend/dist
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION VIRTUAL_ENV=/app/backend/.venv PATH="/app/backend/.venv/bin:$PATH" PYTHONPATH=/app
LABEL org.opencontainers.image.version=$APP_VERSION org.opencontainers.image.source="https://github.com/YeTianXingShi/douyin-ytdlp-web"
CMD ["uv", "run", "--project", "/app/backend", "python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
