# work-behavior-analytics-ai

# First time dev setup
Setup python environment
```
pyenv local 3.14.2 # optional
python -m venv .venv
source .venv/bin/activate
for i in `ls requirements*.txt`
do
pip install -r $i
done
 ```

 Make a copy of .env.example to .env and update the values.

**TLS certificate prerequisite (Docker Compose workflow).** The Compose stack
serves the app over HTTPS through an `nginx` reverse proxy, which needs a
certificate at `deploy/certs/wba.pem` (+ `wba-key.pem`). Generate it once per
machine with `mkcert` — without it `docker compose up` fails on the 443 bind or
the browser shows an untrusted-certificate warning. See *Generate the TLS
certificate* and *Trust the certificate in a Windows browser (WSL2 only)* in
`USER_GUIDE.md` for the exact `mkcert` commands and the WSL2 Windows-trust-store
import; they are not duplicated here.

## Environment Configuration

### LLM Provider Selection
The system supports multiple LLM providers through an abstraction layer. Configure via the `LLM_PROVIDER` environment variable:

```bash
# Choose your LLM provider (openai or custom)
LLM_PROVIDER=openai  # Default
```

### LLM Model Configuration
Set the model to use with your selected provider:
```bash
LLM_MODEL=gpt-5  # For OpenAI: gpt-5, gpt-4, gpt-4-turbo, etc.
                         # For Custom: your custom model name (e.g., gpt-4)
MAX_TOKENS=16000  # Maximum conversation history tokens
```

### OpenAI Configuration (Default Provider)
```bash
OPENAI_API_KEY=your_openai_api_key_here
```

### Custom Provider Configuration (Optional)
For using a custom/in-house LLM provider:
```bash
LLM_PROVIDER=custom
CUSTOM_API_TOKEN=your_custom_api_token
CUSTOM_API_URL=https://api.yourcompany.com/chat  # Your custom API endpoint
```

### Neo4j Configuration (Optional)
```bash

NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_neo4j_password
```

# Start Services with Docker Compose

## Option 1: Using Docker Compose (Recommended)
Start both PostgreSQL and the application together:
```bash
docker compose up -d
```

This will:
- Start PostgreSQL database
- Build and start the application
- Automatically run database migrations
- Mount .env file and logs directory
- Start `nginx`, which terminates TLS and proxies to the app

**Access the services (Option 1 — full Compose stack behind nginx):**
- Dash UI: https://localhost/app
- FastAPI API: https://localhost/api/health

The stack is reached only through nginx on `https://localhost` (port 443).
Host port `:8000` is **no longer published** — reaching the app on `:8000` is
expected to fail in this workflow.

To stop all services:
```bash
docker compose down
```

To view logs:
```bash
docker compose logs -f api    # API service
docker compose logs -f ui     # UI service
```

## Option 2: Backing Stores in Docker, App Local (For Local Development)
The API reads Neo4j and Elasticsearch as well as PostgreSQL, so start all of the
backing services:
```bash
docker compose up -d postgres neo4j elasticsearch rabbitmq
```

Then run the API and the UI locally as two processes. Start the API first — the UI
fetches its runtime-settings snapshot from it:
```bash
# Terminal 1 — API
PYTHONPATH=src uvicorn app.api_main:app --reload

# Terminal 2 — UI (a Flask/WSGI service; needs the API's URL)
API_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=src \
  gunicorn ui_main:server --bind 127.0.0.1:8001 --reload
```

Access the services (Option 2 — API and UI running locally, plain HTTP):
- FastAPI API: http://127.0.0.1:8000/api/health
- Dash UI: http://127.0.0.1:8001/app

## Running Migrations Manually (Local Development)
If running locally, you'll need to run migrations manually:
```bash
cd src/app
alembic upgrade head
cd ../..
```
To create a new migration:
```bash
docker compose exec api bash -c "cd app && alembic revision --autogenerate -m 'description'"
```


# Run tests
- Unit tests only (no external dependencies)
```bash
pytest -m unit tests -q
```

- Integration tests that require app server
```bash
# Terminal 1 — API
PYTHONPATH=src uvicorn app.api_main:app --reload

# Terminal 2 — UI (a Flask/WSGI service; needs the API's URL)
API_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=src \
  gunicorn ui_main:server --bind 127.0.0.1:8001 --reload
```
In another window:
```bash
pytest -m "integration and server" tests -q
```

- Neo4j integration tests (requires live Neo4j)
```bash
pytest -m "integration and neo4j" tests -q
```

- Full local run (unit + integration)
```bash
pytest tests -q
```
