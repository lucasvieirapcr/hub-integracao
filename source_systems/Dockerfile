# Imagem das três APIs simuladas (o command do compose define qual sobe).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/db /app/data/chaos /app/chaos \
    && chown -R app /app

COPY pyproject.toml README.md ./
COPY simulator ./simulator
COPY source_systems ./source_systems
RUN pip install .

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"
