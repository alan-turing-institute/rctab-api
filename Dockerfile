FROM docker.io/tiangolo/uvicorn-gunicorn-fastapi:python3.11-slim

# Install dependencies
RUN apt-get update
RUN apt-get --yes install curl \
    build-essential \
    libffi-dev \
    shared-mime-info \
    libpq-dev \
    python3-dev \
    git \
    wget \
    unzip
#RUN rm -rf /var/lib/apt/lists/*

# Install Redis
# See https://redis.io/docs/install/install-redis/install-redis-on-linux/
RUN apt-get --yes install lsb-release gpg
RUN curl -fsSL https://packages.redis.io/gpg | gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg

RUN echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/redis.list

RUN apt-get update
RUN apt-get --yes install redis

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
RUN ~/.local/share/pypoetry/venv/bin/poetry config virtualenvs.create false

WORKDIR /app

COPY rctab ./rctab
COPY alembic ./alembic
COPY scripts/prestart.sh ./
COPY alembic.ini ./
COPY pyproject.toml poetry.lock ./
COPY redis.conf ./

RUN ~/.local/share/pypoetry/venv/bin/poetry install --only main

ENV APP_MODULE="rctab:app"
