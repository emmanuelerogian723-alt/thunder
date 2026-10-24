# Thunder — the full app: accounts, live video, per-user MCP, recordings, brain, Mouth (voice)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    THUNDER_HOME=/tmp/thunder

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir fastmcp fastapi "uvicorn[standard]" httpx \
        playwright pillow jinja2 piper-tts edge-tts soundfile \
    && python -m playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends espeak-ng \
    && apt-get clean \
    && pip install --no-cache-dir --no-deps .

EXPOSE 10000
CMD ["sh", "-c", "exec python -m uvicorn thunder.webapp.server:app --host 0.0.0.0 --port ${PORT:-10000}"]
