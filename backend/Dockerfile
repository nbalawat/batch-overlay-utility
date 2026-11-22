# Batch Intelligence Overlay - API
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY batchiq ./batchiq
RUN pip install . && useradd --uid 10001 --create-home app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"
CMD ["uvicorn", "batchiq.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
