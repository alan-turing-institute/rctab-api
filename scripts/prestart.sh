#!/usr/bin/env bash
# todo remove logfiles

# For background tasks, we need Redis and Celery running
redis-server ./redis.conf &
celery -A rctab.tasks worker --detach --concurrency 1 --loglevel=info --logfile=celery.log
celery -A rctab.tasks beat --detach --loglevel=info --logfile=beat.log

# Give Postgres, Redis and Celery a few seconds to start
sleep 5

# Run migrations
alembic upgrade head
