# VisionSpark: one container serving the API and the built frontend.
#
# Build: docker build -t visionspark .
# Run:   docker run --rm -e MODEL_API_KEY -p 8000:8000 visionspark
#
# The image never contains a key: MODEL_API_KEY comes from the host's
# secret environment variables.

# Stage 1: build the frontend.
FROM node:24-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: backend + static frontend.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
COPY backend/app ./app
RUN uv sync --frozen --no-dev
COPY --from=frontend-build /app/frontend/dist /app/frontend-dist
ENV FRONTEND_DIST=/app/frontend-dist
ENV PORT=8000
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["sh", "-c", ".venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
