#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be ready..."

# Wait for PostgreSQL to be ready
until PGPASSWORD=$POSTGRES_PASSWORD psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\q'; do
  >&2 echo "PostgreSQL is unavailable - sleeping"
  sleep 1
done

>&2 echo "PostgreSQL is up - executing migrations"

# Run database migrations
cd /app/app && alembic upgrade head

>&2 echo "Migrations complete - initializing RabbitMQ"

# Initialize RabbitMQ exchanges and queues for the ActivitySignal pipeline
cd /app && python app/scripts/init_rabbitmq.py

>&2 echo "RabbitMQ initialization complete - creating Neo4j indexes"

# Create Neo4j indexes (idempotent)
cd /app && python app/scripts/create_neo4j_indexes.py

>&2 echo "Neo4j indexes ready - creating Elasticsearch indexes"

# Create Elasticsearch indexes and wba_all alias (idempotent)
cd /app && python app/scripts/create_es_indexes.py
>&2 echo "Elasticsearch indexes ready - starting application"

# Start the application
#
# The trusted-peer flag below tells uvicorn which peers may set
# X-Forwarded-Proto / X-Forwarded-For. uvicorn's ProxyHeadersMiddleware honours
# those headers only from trusted hosts, and the default is "127.0.0.1,::1" —
# which does NOT include nginx's container IP, so the external scheme would be
# lost.
#
# "*" (trust any peer) is safe ONLY because the app publishes no host port
# (docker-compose.yml removed the 8000:8000 mapping), so the only reachable
# peers are nginx and the other compose services. Re-publishing a host port
# would make this a spoofing hole — keep the two in sync.
cd /app && uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --forwarded-allow-ips="*"
