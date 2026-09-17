# The frontend is built here rather than committed, so the deployed bundle always matches
# the source in the repository.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /srv

COPY api/pyproject.toml api/uv.lock* api/README.md /srv/api/
WORKDIR /srv/api
RUN uv sync --frozen --no-dev || uv sync --no-dev

WORKDIR /srv
COPY api/src /srv/api/src
# About 5 MB of Parquet. Small enough to ship inside the image, which keeps the deployment
# to a single service with no attached disk and no database to provision.
COPY data /srv/data
COPY --from=web /web/dist /srv/web/dist

ENV VALID_DATA_DIR=/srv/data \
    VALID_WEB_DIR=/srv/web/dist \
    PATH="/srv/api/.venv/bin:$PATH"

EXPOSE 8000
# Render supplies $PORT; the default keeps `docker run` working locally.
CMD ["sh", "-c", "uvicorn overture_api.main:app --app-dir /srv/api/src --host 0.0.0.0 --port ${PORT:-8000}"]
