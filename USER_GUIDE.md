# Work Behavior Analytics AI - User Guide

## Prerequisites

1. **Docker and Docker Compose installed** on your system
2. This project uses databases which are dockerized images in the docker-compose.yml file.
3. **Python 3** (used by the setup script to generate an encryption key)
4. **`mkcert`** — issues the local TLS certificate the app is served over. If it
   is not already installed, the commands in *Generate the TLS certificate* below
   will install it.
5. **WSL2 users only: access to the Windows certificate store.** If Docker runs
   in WSL2 but your browser runs on Windows, you must import `mkcert`'s local
   certificate authority into Windows once, or the browser will warn about the
   certificate.

> `openssl` ships with most Linux distributions and can generate a throwaway
> self-signed certificate if `mkcert` is genuinely unavailable. Treat that as a
> last resort only — a self-signed certificate is trusted by no browser, so the
> warning cannot be silenced the way `mkcert` silences it.

The app is served over HTTPS by an nginx container. The application container no
longer publishes a host port; nginx publishes 443 (HTTPS) and 80 (a redirect to
HTTPS).


## Starting the Application

### Generate the TLS certificate

nginx terminates HTTPS with a local certificate, so the certificate has to exist
before the stack starts. `mkcert` creates a local certificate authority (CA),
installs it into your trust store, and issues a certificate for `localhost` — so
your browser trusts the app and does not warn.

Run these **from the repository root**, because `deploy/certs/` is created
relative to your working directory:

```bash
# Install mkcert (skip this block if `mkcert` is already on your PATH)
sudo apt install -y libnss3-tools
curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"
chmod +x mkcert-v*-linux-amd64
sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert

# Create a local CA and install it into the trust store
mkcert -install

# Issue a certificate for the app hostname
mkdir -p deploy/certs
mkcert -cert-file deploy/certs/wba.pem -key-file deploy/certs/wba-key.pem localhost 127.0.0.1
```

After this, `ls deploy/certs/` shows `wba.pem` and `wba-key.pem`. Both files are
gitignored and never committed.

#### Trust the certificate in a Windows browser (WSL2 only)

If Docker runs in WSL2 but the browser runs on Windows, the `mkcert -install`
above only installed the CA into the **Linux** trust store, which the Windows
browser does not read — so it will still warn. Import the CA into Windows once
per machine:

1. Inside WSL, find where `mkcert` keeps its CA:

   ```bash
   mkcert -CAROOT
   ```

2. Open **PowerShell as Administrator** and import `rootCA.pem` from that
   directory. From Windows the path is
   `\\wsl.localhost\<distro>\<CAROOT with forward slashes replaced by backslashes>`.
   For a WSL distro named `Ubuntu` and a CAROOT of
   `/home/<you>/.local/share/mkcert`, that is:

   ```powershell
   Import-Certificate -FilePath "\\wsl.localhost\Ubuntu\home\<you>\.local\share\mkcert\rootCA.pem" -CertStoreLocation Cert:\LocalMachine\Root
   ```

   Substitute your own distro name and home path from the `mkcert -CAROOT`
   output. On some Windows builds the older `\\wsl$\<distro>\...` prefix works
   instead of `\\wsl.localhost\...`.

This is a one-time manual step per developer machine and cannot be automated
from the repository. Skipping it is the single most common cause of a scary
certificate warning that looks like the deployment is broken.

> **Firefox does not read the Windows certificate store.** If you use Firefox,
> either import the CA into Firefox directly, or open `about:config`, set
> `security.enterprise_roots.enabled` to `true`, and restart the browser. Chrome
> and Edge read the Windows store and need no extra step.

### Configure the environment

Run the setup wizard — it interactively configures your database, Neo4j, and
RabbitMQ credentials (each with a sensible default), **generates** the connector
encryption key and the five Keycloak credentials, and optionally prompts you for
your GitHub token and OpenAI API key:

```bash
./scripts/setup.sh
```

The script is idempotent — re-running it never overwrites values you've
already set; each prompt re-offers the current value as the default.

#### Keycloak credentials

The wizard generates five credentials, which you do not need to choose:

| Variable | What it is |
|---|---|
| `KEYCLOAK_DB_PASSWORD` | Password for the `keycloak` Postgres role |
| `KEYCLOAK_CLIENT_SECRET` | Secret for the `wba-web` browser client |
| `KEYCLOAK_SERVICE_CLIENT_SECRET` | Secret for the `wba-internal` service-account client |
| `DEV_ADMIN_PASSWORD` | Password for the seeded `dev-admin` login |
| `DEV_USER_PASSWORD` | Password for the seeded `dev-user` login |

Sign in as `dev-admin` or `dev-user` with the value in `.env`. That file is
gitignored — never commit it, and never paste these values into a committed file
or a bug report.

The browser-facing URL comes from `EXTERNAL_BASE_URL`, which already defaults to
`https://localhost`. Leave it alone for a local install — set it only if you
serve the app under a different hostname, for example:

```bash
EXTERNAL_BASE_URL=https://wba.example.com
```

### Start the stack and open the app

The wizard offers to start the application for you. If you declined, start it
now:

```bash
docker compose up -d
```

The `-d` flag runs containers in detached mode (background).

**What happens:**
- PostgreSQL database starts first
- Application waits for PostgreSQL to be healthy
- Database migrations run automatically
- nginx starts once the application is healthy and serves it over HTTPS

**Access the application:**
- Dash UI: https://localhost/app
- FastAPI API: https://localhost/api/health

> **`http://localhost:8000` is expected to fail.** Neither the `api` nor the `ui`
> container publishes a host port — that is deliberate, so all traffic is forced
> through nginx over HTTPS. A connection error there is the intended behaviour,
> not a fault to fix. `http://localhost` (port 80) redirects to HTTPS.


## Stopping the Application

### Stop All Services
```bash
docker compose down
```

This stops and removes containers, but **preserves data** in the PostgreSQL and neo4j volume.

### Stop and Remove Volumes (Clean Reset)
⚠️ **Warning**: This deletes all database data!

```bash
docker compose down -v
```

### Stop Without Removing Containers
```bash
docker compose stop
```

To restart stopped containers:
```bash
docker compose start
```

## Viewing Logs

### View All Service Logs
```bash
docker compose logs
```

### View API or UI Logs Only
```bash
docker compose logs api
docker compose logs ui
```

### View PostgreSQL Logs Only
```bash
docker compose logs postgres
```

### Follow Logs in Real-Time
```bash
docker compose logs -f api
docker compose logs -f ui
```

Press `Ctrl+C` to stop following logs.

### View Last N Lines
```bash
docker compose logs api --tail 50
```

### View Logs with Timestamps
```bash
docker compose logs -f -t api
```

## Checking Status

### Check Running Containers
```bash
docker compose ps
```

### Check Container Details
```bash
docker ps
```

### Check PostgreSQL Health
```bash
docker compose exec postgres pg_isready -U <your_postgres_user>
```

## Rebuilding the Application

### Rebuild After Code Changes
```bash
docker compose up -d --build
```

### Force Rebuild Without Cache
```bash
docker compose build --no-cache
docker compose up -d
```

## Accessing Containers

### Open a Shell in the API Container
The API service is the one with the database and migrations. Substitute `ui` for
`api` to get a shell in the UI container instead.
```bash
docker compose exec api bash
```

### Open a PostgreSQL Shell
```bash
docker compose exec postgres psql -U <your_postgres_user> -d <your_postgres_db>
```

## Troubleshooting

### HTTPS and Certificate Problems

- **The browser warns that the certificate is not trusted.**
  *Cause*: `mkcert`'s CA was not imported into the browser's trust store — on
  WSL2 this is the Windows-side import, which is easy to skip.
  *Fix*: run the Windows import in *Trust the certificate in a Windows browser*
  above. Firefox additionally needs `security.enterprise_roots.enabled` set to
  `true` in `about:config`.

- **`docker compose up` fails with `bind: address already in use` on port 80 or 443.**
  *Cause*: another process already holds the port — often a previous stack, or a
  local web server.
  *Fix*: stop whatever owns the port (for example `docker compose down`, or find
  it with `sudo ss -ltnp | grep ':443'`) and start again.

- **`https://localhost/app` returns 502 Bad Gateway.**
  *Cause*: nginx is up but the `api` or `ui` container behind it is not healthy —
  a 502 on the UI paths is usually the `ui` service.
  *Fix*: check the container logs and wait for the healthchecks to pass:

  ```bash
  docker compose logs api
  docker compose logs ui
  ```

- **`deploy/certs/` is empty.**
  *Cause*: `mkcert` was never run, or it was run from a different working
  directory than the repository root.
  *Fix*: re-run the certificate commands from the repository root — see
  *Generate the TLS certificate* above.

### Container Keeps Restarting
Check the logs:
```bash
docker compose logs api
docker compose logs ui
```

Common issues:
- **Database connection errors**: Ensure `DATABASE_URL` uses `postgres` as hostname (not `localhost`)
- **Missing environment variables**: Check your `.env` file
- **Port conflicts**: Ensure ports 5432, 80, and 443 are not in use

### View Container Resource Usage
```bash
docker stats
```

### Inspect Network Configuration
```bash
docker network inspect wba-ai_wba-ai-network
```

### Remove Everything and Start Fresh
```bash
docker compose down -v
docker compose up -d --build
```

## File Locations

### Logs Directory
Application logs are written to `./logs/` on your host machine (mounted from container).

To view log files:
```bash
ls -la logs/
cat logs/logger_*.log
```

### Environment Configuration
The `.env` file is mounted read-only into the container at `/app/.env`.

⚠️ **Note**: After changing `.env`, restart the containers. The `.env` is mounted
into the `api` service only, so restarting `ui` is only needed for its own
environment changes:
```bash
docker compose restart api
docker compose restart ui
```


## Quick Reference

| Task | Command |
|------|---------|
| First-time setup | `./scripts/setup.sh` |
| Generate TLS certificate | `mkcert -cert-file deploy/certs/wba.pem -key-file deploy/certs/wba-key.pem localhost 127.0.0.1` |
| Start services | `docker compose up -d` |
| Open the app | https://localhost/app |
| Stop services | `docker compose down` |
| View logs | `docker compose logs -f api` (or `-f ui`) |
| Check status | `docker compose ps` |
| Rebuild | `docker compose up -d --build` |
| Restart app | `docker compose restart api` (or `ui`) |
| Shell access | `docker compose exec api bash` |
| Clean reset | `docker compose down -v && docker compose up -d --build` |

## Support

For issues or questions:
1. Check the logs: `docker compose logs -f api` (or `-f ui`)
2. Review the [quick-start.md](quick-start.md) guide
3. Ensure your `.env` file is properly configured
