# Docker deployment

This deployment runs the existing FastAPI dashboard API and serves the existing
React production build through Nginx. The DuckDB database stays on the host and
is mounted read-only into the backend container. Nginx is the only service
published to the host; frontend API requests use its same-origin `/api` proxy.

## Requirements and database placement

Install Docker Desktop (Windows/macOS) or Docker Engine plus the Docker Compose
plugin (Linux). Before starting the stack, place the real database at:

```text
<project directory>/database/twinflame.duckdb
```

The database file is ignored by Git and is not included in Docker images or a
source checkout. Copy the complete `.duckdb` file from a trusted source without
renaming or modifying it. It is roughly 500 MB in the current checkout; allow
enough disk space for the actual copy and DuckDB query spill storage. Never
replace the source database with the small backup file unless that backup is
intended and verified.

To use a different host path, set `DUCKDB_HOST_PATH` in `.env` to that file. For
example, on Windows use `DUCKDB_HOST_PATH=C:/TwinFlame/database/twinflame.duckdb`.
The container always reads it at `/app/database/twinflame.duckdb`. The bind
mount is read-only, so stopping/recreating containers does not remove or rewrite
the host database. DuckDB may use the container's writable layer for temporary
query spill files; those files are not part of the database and do not persist
when the container is recreated. Keep enough free space in Docker's storage
location for large dashboard queries.

## Build and start

From the repository root:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose build
docker compose up -d
docker compose ps
```

If `.env` already exists, keep it and add or adjust only the Docker settings you
need; do not replace it with `.env.example`.

Open `http://localhost:8080`. Set `FRONTEND_PORT` in `.env` to use another host
port. Docker Compose checks the database on backend startup and returns a clear
error if it is absent or cannot be opened read-only. The backend health check
queries DuckDB through `/api/health`; the frontend waits for that check to pass.

### HTTPS inspection certificates during image builds

Some antivirus products and managed networks inspect HTTPS and present a
certificate signed by a local root CA. If `pip` or `npm ci` reports a certificate
verification error during `docker compose build`, export that trusted public
root certificate in PEM format to `docker/certs/avast-root.crt` (or set
`DOCKER_BUILD_CA_FILE` in `.env` to its path). The Compose build passes it only
as a BuildKit secret to dependency installation; TLS certificate verification
stays enabled, and the CA is not copied into either image. The certificate file
is ignored by Git. On another computer, use that computer/network's verified
root CA. If no TLS inspection is in use, remove both `build.secrets` entries
and the top-level `secrets` block from `docker-compose.yml`. Never export or
share a private key.

The backend port is available only inside the Compose network. The public Nginx
proxy blocks `POST /api/pipeline/run` because this deployment does not include
authentication for pipeline execution. The remaining API routes are proxied
without changing their response formats.

## Stop and restart

Stop containers and retain the database:

```powershell
docker compose down
```

Start them again:

```powershell
docker compose up -d
```

Rebuild after changing application code or Docker configuration:

```powershell
docker compose up -d --build
```

Do not use `docker compose down -v` as a routine stop command. The database is
bind-mounted from the host, but removing volumes is unnecessary and can delete
other Docker-managed state.

## Move to another computer

1. Copy or securely transfer the project source, including the Docker files.
2. Transfer the real `database/twinflame.duckdb` file separately; Git does not
   track it. Verify the copied file size and, when practical, compare SHA-256
   checksums on both computers.
3. Install Docker and Compose on the destination computer.
4. Create `.env` from `.env.example`, set `DUCKDB_HOST_PATH` if the database is
   outside the project directory, then run the build and start commands above.

## Troubleshooting

- **Database not found:** confirm the exact file name and host path. Check
  `DUCKDB_HOST_PATH` in `.env`; Compose resolves the default path relative to
  this project directory.
- **Backend unhealthy / database inaccessible:** inspect
  `docker compose logs backend`. Confirm the file is a valid DuckDB database,
  is readable by Docker, and is not being modified by another process. The
  dashboard opens it read-only.
- **Port 8080 is in use:** set `FRONTEND_PORT` to an unused port in `.env`, then
  run `docker compose up -d` again and open that port.
- **Frontend loads but API calls fail:** run `docker compose ps` and inspect
  `docker compose logs backend frontend`. Ensure the backend became healthy and
  `DOCKER_VITE_API_BASE_URL` is empty so the frontend uses Nginx's `/api` proxy.
- **Dashboard route returns 404 after refresh:** confirm Nginx is using the
  supplied `nginx.conf`; it falls back to `index.html` for React routes. Rebuild
  with `docker compose up -d --build` after config changes.
- **Overview or geospatial page reports unavailable data:** check the backend
logs and the required tables and schema for that endpoint. Dockerization does
not run ingestion or fabricate tables.

## Validation notes and limitations

The images install only the Python packages imported by the current dashboard
API (`duckdb`, `fastapi`, `uvicorn`, and `python-dotenv`); pipeline packages in
`requirements.txt` are not installed because the data pipeline is not run in
this deployment. If a future API route adds imports from pipeline or geospatial
packages, add those runtime dependencies to `Dockerfile.backend`.

No pipeline job is started automatically. The browser-facing pipeline execution
route returns HTTP 403 through Nginx. This is a single-host hackathon deployment
and does not include user authentication, TLS termination, automated database
backup, or remote database transfer. Bind and expose the frontend only on a
trusted network.
