FROM docker.io/tiangolo/uvicorn-gunicorn-fastapi:python3.10-slim

# Install dependencies
RUN apt-get update && \
    apt-get -y install curl \
    build-essential \
    libpango* \
    libffi-dev \
    shared-mime-info \
    libpq-dev \
    python3-dev \
    git \
    wget \
    unzip && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
RUN ~/.local/share/pypoetry/venv/bin/poetry config virtualenvs.create false

WORKDIR /app

COPY rctab ./rctab
COPY alembic ./alembic
COPY scripts/prestart.sh ./
COPY alembic.ini ./
COPY pyproject.toml poetry.lock ./

RUN ~/.local/share/pypoetry/venv/bin/poetry install --only main

ENV APP_MODULE="rctab:app"
