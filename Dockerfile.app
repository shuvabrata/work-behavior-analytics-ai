# Use Python 3.14.2 slim image as base (matches local development environment)
FROM python:3.14.2-slim

# Install PostgreSQL client for database readiness check
RUN apt-get update && apt-get install -y postgresql-client curl && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.app.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Fail the build loudly if PyYAML was compiled without libyaml (i.e. no
# CSafeLoader). The query catalog loader falls back to the ~10x slower
# pure-Python parser in that case; a silent slowdown in production is worse
# than a failed build. See src/app/query_catalog/loader.py.
RUN python -c "import yaml; assert hasattr(yaml, 'CSafeLoader'), 'PyYAML built without libyaml: CSafeLoader is missing'"

# Copy app code (includes alembic/, alembic.ini, entrypoint.sh)
COPY src/app/ ./app/

# Copy shared common package (logger, etc.)
COPY src/common/ ./common/

# Copy shipped query catalog used by the graph query workbench
COPY queries_catalog/ ./queries_catalog/

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash appuser && \
    mkdir -p /var/log/app && \
    # Pre-create the user-defined catalog dir owned by appuser so the named
    # volume mounted at /app/queries_catalog/user_defined inherits writable
    # ownership on first mount (Docker copies the image dir's ownership).
    mkdir -p /app/queries_catalog/user_defined && \
    chown -R appuser:appuser /var/log/app /app && \
    # Lock down the shipped system catalog: root-owned and read-only so the
    # app cannot modify it. Only the user_defined/ subtree stays writable by
    # appuser (it is overlaid by a named volume at runtime). The chmod/chown
    # on user_defined/ must run AFTER the read-only pass so the volume root
    # inherits writable ownership on first mount.
    chown -R root:root /app/queries_catalog && \
    chmod -R a-w /app/queries_catalog && \
    chown -R appuser:appuser /app/queries_catalog/user_defined && \
    chmod -R u+w /app/queries_catalog/user_defined

# Expose port
EXPOSE 8000

# Switch to non-root user
USER appuser

# Use entrypoint script
ENTRYPOINT ["app/entrypoint.sh"]
