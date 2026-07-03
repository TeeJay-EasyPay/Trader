FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV AI_TRADER_API_HOST=0.0.0.0
ENV AI_TRADER_DB_PATH=/data/audit.sqlite3
ENV AI_TRADER_OUTPUT_DIR=/data
ENV AI_TRADER_TRADING_LOG_PATH=/data/TRADING_LOG.md

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY governance ./governance

RUN pip install --no-cache-dir .

RUN mkdir -p /data

EXPOSE 8765

CMD ["python", "-m", "ai_trader.cli", "serve-api"]
