# ---- build the web app ----
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- run the match room (API + WebSocket + MCP + static web) ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
COPY pyproject.toml README.md ./
COPY packages ./packages
COPY services ./services
RUN pip install --no-cache-dir ".[azure]"
COPY --from=web /web/dist ./web/dist
ENV WEB_DIST=/app/web/dist
WORKDIR /app/services
EXPOSE 8000
USER 1000
CMD ["sh", "-c", "uvicorn match_room.app:app --host 0.0.0.0 --port ${PORT}"]
