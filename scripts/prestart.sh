#!/usr/bin/env bash

sleep 5

# Run migrations
alembic upgrade head
