FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app
COPY pyproject.toml README.md ./
COPY thunder ./thunder
RUN pip install --no-cache-dir . curl_cffi && \
    python -m playwright install chromium

# Thunder needs no keys to run; envs below are optional pairings
ENV THUNDER_HOME=/data
VOLUME /data

CMD ["python", "-m", "thunder.mcp_server"]
