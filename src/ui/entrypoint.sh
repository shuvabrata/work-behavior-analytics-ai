#!/bin/bash
set -e
# No migrations, no index creation, no RabbitMQ initialisation: the UI holds no
# database driver and no transport. It serves Dash and calls the API over HTTP.

# Tuning: --worker-class gthread + --threads is deliberate. Dash callbacks are
# synchronous `requests` calls, and gunicorn's default `sync` worker with 1
# thread would SERIALIZE every callback in a worker — a real behaviour change
# from the Starlette threadpool (~40 threads) that served these callbacks
# before the split. Raise --workers/--threads for a larger host; the concurrency
# gate in this plan's Step 12 is what verifies they are not serializing.
cd /app && exec gunicorn ui_main:server \
    --bind 0.0.0.0:8000 \
    --worker-class gthread \
    --workers 4 \
    --threads 8 \
    --preload
