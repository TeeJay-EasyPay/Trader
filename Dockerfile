FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV AI_TRADER_API_HOST=0.0.0.0
ENV AI_TRADER_DB_PATH=/data/audit.sqlite3
ENV AI_TRADER_OUTPUT_DIR=/data
ENV AI_TRADER_TRADING_LOG_PATH=/data/TRADING_LOG.md
ENV AI_TRADER_KNOWLEDGE_DIR=/app/knowledge
# Where the readable source actually lives in this image. `pip install .` below puts the
# package in site-packages, so nothing can infer this from its own __file__ -- and without it
# every one of Claude's code lookups silently returned nothing in production while working
# locally. app_root() also detects this on its own now; this line states it outright.
ENV AI_TRADER_APP_ROOT=/app

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY governance ./governance
COPY knowledge ./knowledge

RUN pip install --no-cache-dir .

RUN mkdir -p /data

EXPOSE 8765

CMD ["python", "-m", "ai_trader.cli", "serve-api"]
