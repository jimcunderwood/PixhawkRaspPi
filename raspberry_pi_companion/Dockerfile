FROM python:3.11-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/raspberry_pi_companion

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      build-essential \
      libgl1 \
      libglib2.0-0 \
      libsm6 \
      libxext6 \
      libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY raspberry_pi_companion/requirements.txt /tmp/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r /tmp/requirements.txt

COPY raspberry_pi_companion/ ./

FROM base AS runtime

EXPOSE 8000

CMD ["python", "main.py"]

FROM runtime AS test

CMD ["python", "-m", "pytest", "-q"]
