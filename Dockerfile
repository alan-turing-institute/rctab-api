FROM python:3.14

# Install dependencies
RUN apt-get update
RUN apt-get --yes install curl \
    build-essential \
    libffi-dev \
    shared-mime-info \
    libpq-dev \
    git \
    wget \
    unzip \
    redis
RUN rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_VERSION=2.5.1
RUN curl -sSL https://install.python-poetry.org | python3 -
RUN ~/.local/share/pypoetry/venv/bin/poetry config virtualenvs.create false

WORKDIR /app

COPY pyproject.toml poetry.lock ./
COPY rctab ./rctab

RUN ~/.local/share/pypoetry/venv/bin/poetry install --only main

COPY alembic ./alembic
COPY scripts/prestart.sh ./
COPY scripts/start.sh ./
COPY alembic.ini ./
COPY redis.conf ./

CMD ["./start.sh"]
