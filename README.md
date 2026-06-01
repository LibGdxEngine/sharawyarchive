# Full-Stack Dockerized Boilerplate (Next.js + Django)

A production-ready template incorporating a modern frontend, powerful backend, caching, task worker queues, and an automated HTTPS proxy. Built to work out of the box with Docker.

## Tech Stack
*   **Frontend**: [Next.js](https://nextjs.org/) (React, TypeScript, Tailwind CSS v4)
*   **Backend**: [Django](https://www.djangoproject.com/) (REST Framework, WhiteNoise)
*   **Database**: [PostgreSQL](https://www.postgresql.org/)
*   **Caching & Broker**: [Redis](https://redis.io/)
*   **Task Queue**: [Celery](https://docs.celeryq.dev/en/stable/)
*   **Reverse Proxy**: [Caddy](https://caddyserver.com/)

---

## Project Structure

```text
starter_project/
├── backend/                  # Django backend
│   ├── api/                  # Django App (endpoints & tasks)
│   ├── core/                 # Django settings configuration
│   │   ├── settings/
│   │   │   ├── base.py       # Shared settings
│   │   │   ├── dev.py        # Development settings
│   │   │   └── prod.py       # Production-hardened settings
│   ├── Dockerfile            # Dev Backend image configuration
│   ├── Dockerfile.prod       # Prod Backend image configuration
│   ├── entrypoint.sh         # Startup check & database migrations script
│   └── requirements.txt      # Python dependencies
├── frontend/                 # Next.js frontend
│   ├── src/                  # Next.js app pages (App Router)
│   ├── Dockerfile            # Dev Frontend image configuration
│   ├── Dockerfile.prod       # Prod Frontend image configuration (multi-stage)
│   └── next.config.ts        # Next.js config (standalone build mode enabled)
├── caddy/                    # Web server reverse proxy configuration
│   ├── Caddyfile             # Production Caddy routing (SSL active)
│   └── Caddyfile.dev         # Development Caddy routing
├── docker-compose.yml        # Development Docker Compose
├── docker-compose.prod.yml   # Production Docker Compose
├── .env.dev                  # Dev environment variables
└── .env.prod                 # Prod environment variables (with placeholders)
```

---

## Quick Start (Development)

### 1. Prerequisites
Ensure you have Docker and Docker Compose installed:
*   [Docker Engine](https://docs.docker.com/engine/install/)
*   [Docker Compose](https://docs.docker.com/compose/install/)

### 2. Run the Development Server
From the root of the project, execute:
```bash
make up
```
Or to build and launch from scratch:
```bash
make build && make up
```
This starts PostgreSQL (`db`), Redis (`redis`), Django (`backend`), Celery (`celery_worker`), Next.js (`frontend`), and Caddy (`caddy`) in the background.

To watch all logs:
```bash
make logs
```

### 3. Verify
Open your browser and navigate to:
*   **Web Dashboard**: [http://localhost](http://localhost)
*   **Interactive API Docs (Swagger)**: [http://localhost/api/docs/](http://localhost/api/docs/)
*   **Django API Status**: [http://localhost/api/status/](http://localhost/api/status/)
*   **Django Admin Console**: [http://localhost/admin/](http://localhost/admin/)

### 4. Create a Superuser
To create a superuser for dashboard authentication, run:
```bash
make createsuperuser
```

---

## Deployment (Production)

To spin up the production environment:

1.  **Configure environment variables**: Copy or rename `.env.prod` and configure your credentials, database password, secret keys, domain name, and trusted origins.
2.  **Run the production stack**:
    ```bash
    make prod-build && make prod-up
    ```
3.  **Logs verification**:
    ```bash
    docker compose -f docker-compose.prod.yml logs -f
    ```

### Production Best Practices Implemented:
*   **Security Policies**: Django is run under a non-root system user (`django`) and Next.js under a non-root node user (`nextjs`).
*   **Django Hardening**: SECURE COOKIES, HSTS, SSL redirects, and strict CORS/CSRF configurations are loaded dynamically in `core.settings.prod`.
*   **Next.js Standalone**: Docker builds utilize multi-stage caching and output `standalone` folder tracking, yielding production images under 150MB.
*   **Caddy Routing**: Automated HTTPS management, SSL redirection, static compression (gzip and zstd), and logging to file.
*   **WhiteNoise**: Compresses and creates unique hashes for Django static files (`CompressedManifestStaticFilesStorage`) to leverage browser caching.

---

## Service Verification Endpoints

### 1. Hello World API
Route: `GET /api/hello/`
Returns a simple JSON payload showing backend connection success.

### 2. Health & Connections API
Route: `GET /api/status/`
Performs dynamic, runtime connection validation:
1.  **Database Connection**: Attempts a raw check to ensure PostgreSQL is up.
2.  **Redis Connection**: Sets and gets a temporary cache key to verify Redis is operational.
3.  **Celery Worker Integration**: Fires an async Celery task (`test_celery_task.delay(4, 5)`) to verify background queue processing.
