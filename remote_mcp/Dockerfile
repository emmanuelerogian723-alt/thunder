# Thunder — the full app: accounts, live video, per-user MCP, recordings, brain
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    THUNDER_HOME=/tmp/thunder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && apt-get clean

COPY . .
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "thunder.webapp.server:app", "--host", "0.0.0.0", "--port", "7860"]
