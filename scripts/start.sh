#!/usr/bin/env bash

# See Dockerfile for how and where this is intended to be run.
./prestart.sh && exec uvicorn rctab:app --host 0.0.0.0 --port 80 --workers 4 \
    --proxy-headers --forwarded-allow-ips='*'
