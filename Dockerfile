# Multi-stage Dockerfile for schemadrift (pg-schema-diff)
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY schemadrift/ ./schemadrift/

RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY schemadrift/ ./schemadrift/

RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

ENTRYPOINT ["schemadrift"]
CMD ["--help"]
