# Single-service image: builds the React frontend and bundles it into the
# FastAPI backend, which serves both the API and the static SPA. Used for the
# Render deploy (see DEPLOY.md). Local development still uses docker-compose,
# which runs the frontend and backend as separate services.
#
# Build context is the repo root:  docker build -t deepfield .

# ---- Stage 1: build the React frontend ----
FROM node:20-alpine AS frontend
WORKDIR /web
# Empty API base → the bundle uses same-origin (relative) URLs, since the
# backend serves it. See frontend/src/api.js.
ENV VITE_API_URL=""
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: backend + bundled frontend ----
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Only runtime deps (httpx ships transitively with the anthropic SDK).
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
# Bundle the built SPA so main.py mounts it at "/".
COPY --from=frontend /web/dist ./static

EXPOSE 8000
# Hosts like Render inject $PORT; default to 8000 locally.
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
