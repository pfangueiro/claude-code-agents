---
name: docker-deployment
description: Production-ready Docker configurations, multi-stage builds, and deployment best practices
---

# Docker Deployment Skill

Provides production-ready Docker configurations, multi-stage builds, and deployment best practices.

## Purpose

This skill provides:
- Optimized Dockerfile patterns for different tech stacks
- Multi-stage build strategies
- Docker Compose configurations
- Container security best practices
- Docker registry integration
- Health checks and monitoring

## When to Use

- "Create a Dockerfile for Node.js app"
- "Optimize Docker image size"
- "Set up Docker Compose for microservices"
- "Implement Docker health checks"
- "Deploy with Docker Swarm/Kubernetes"

## Node.js Dockerfile (Multi-Stage Build)

```dockerfile
# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies (including dev dependencies for build)
RUN npm ci

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Prune dev dependencies
RUN npm prune --production

# Production stage
FROM node:20-alpine AS production

# Add non-root user for security
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nodejs -u 1001

WORKDIR /app

# Copy built artifacts and production dependencies
COPY --from=builder --chown=nodejs:nodejs /app/dist ./dist
COPY --from=builder --chown=nodejs:nodejs /app/node_modules ./node_modules
COPY --from=builder --chown=nodejs:nodejs /app/package*.json ./

# Use non-root user
USER nodejs

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health', (r) => {process.exit(r.statusCode === 200 ? 0 : 1)})"

# Start application
CMD ["node", "dist/index.js"]
```

## Next.js Dockerfile

**Prerequisite — `output: 'standalone'`.** Next.js only emits `.next/standalone` when the app
opts into standalone output. On a default Next app that directory does not exist and the
`COPY /app/.next/standalone` below fails the build with
`"/app/.next/standalone": not found`. Set this in `next.config.js` **before** building:

```js
// next.config.js
module.exports = {
  output: 'standalone',
}
```

```dockerfile
FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NEXT_TELEMETRY_DISABLED 1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV production
ENV NEXT_TELEMETRY_DISABLED 1

RUN addgroup -g 1001 -S nodejs && \
    adduser -S nextjs -u 1001

COPY --from=builder /app/public ./public
# Requires `output: 'standalone'` in next.config.js — see prerequisite above
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000
ENV PORT 3000

CMD ["node", "server.js"]
```

## Python FastAPI Dockerfile

```dockerfile
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Install into a virtualenv, NOT `pip install --user`.
# `--user` installs to /root/.local, and /root is mode 0700 — after the runtime
# stage switches to a non-root USER the interpreter cannot even traverse it, and
# the container dies on startup with "Permission denied" on the entrypoint.
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Copy requirements
COPY requirements.txt .

# Install Python dependencies into the virtualenv
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Create the non-root user first, so everything below is copied in already owned by it
RUN useradd -m -u 1001 appuser

# Copy the virtualenv from builder, owned by the user that will actually run it
COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv

# Copy application code
COPY --chown=appuser:appuser . .

# Put the virtualenv first on PATH so `python` / `uvicorn` resolve to it
ENV PATH=/opt/venv/bin:$PATH

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Docker Compose - Full Stack Application

Two things this template does deliberately, because the checklist below demands them:
credentials are mounted as **secret files** under `/run/secrets/` rather than passed as
environment variables, and **every service declares CPU/memory limits**
(`deploy.resources.limits` is honoured by `docker compose up` in Compose v2, not just Swarm).

Before `docker compose up`, create the secret file — keep it `chmod 0600`, gitignored, and
never bake it into an image. Also create the non-secret env file the `api` service declares:
Compose resolves `env_file` eagerly and **aborts the whole stack** if the path is missing, so
an absent `api/.env` fails `docker compose config` before a single container starts.

```bash
mkdir -p secrets && openssl rand -base64 32 > secrets/postgres_password.txt
chmod 0600 secrets/postgres_password.txt

# Non-secret config for the api service. Empty is fine; the file just has to exist.
mkdir -p api && touch api/.env
```

```yaml
services:
  # Frontend (Next.js)
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://api:4000
    depends_on:
      api:
        condition: service_healthy
    networks:
      - app-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 512M
        reservations:
          memory: 256M

  # Backend API (Node.js)
  api:
    build:
      context: ./api
      dockerfile: Dockerfile
    ports:
      - "4000:4000"
    # Non-secret config only. Keep this file gitignored and .dockerignore'd.
    env_file:
      - ./api/.env
    environment:
      - REDIS_URL=redis://redis:6379
      - NODE_ENV=production
      # No credentials in the DSN. The app reads the password from the mounted
      # secret file and assembles the connection string at startup.
      - DATABASE_HOST=postgres
      - DATABASE_PORT=5432
      - DATABASE_NAME=myapp
      - DATABASE_USER=postgres
      - DATABASE_PASSWORD_FILE=/run/secrets/postgres_password
    secrets:
      - postgres_password
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "node", "-e", "require('http').get('http://localhost:4000/health')"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 30s
    networks:
      - app-network
    restart: unless-stopped
    volumes:
      - ./api/uploads:/app/uploads
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 1G
        reservations:
          memory: 512M

  # PostgreSQL Database
  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_DB=myapp
      # The official image reads the password from this file instead of POSTGRES_PASSWORD
      - POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password
    secrets:
      - postgres_password
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./init-db.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - app-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 2G
        reservations:
          memory: 1G

  # Redis Cache
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - app-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M
        reservations:
          memory: 256M

  # Nginx Reverse Proxy
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - frontend
      - api
    networks:
      - app-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 256M
        reservations:
          memory: 128M

networks:
  app-network:
    driver: bridge

volumes:
  postgres-data:
  redis-data:

secrets:
  # Local/dev: a gitignored file, mounted read-only at /run/secrets/postgres_password.
  # Swarm or a managed platform: swap for `external: true` and a real secret store
  # (Vault, AWS Secrets Manager, SOPS) — never commit the value.
  postgres_password:
    file: ./secrets/postgres_password.txt
```

## Docker Security Best Practices

### Minimal Base Image

```dockerfile
# Use distroless for minimal attack surface
FROM gcr.io/distroless/nodejs20-debian12

WORKDIR /app

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules

CMD ["dist/index.js"]
```

### Multi-Layer Security

```dockerfile
FROM node:20-alpine

# Security: Run as non-root
RUN addgroup -g 1001 app && \
    adduser -D -u 1001 -G app app

WORKDIR /app

# Security: Use specific versions
COPY package*.json ./
RUN npm ci --only=production && \
    npm cache clean --force

# Security: Set file permissions
COPY --chown=app:app . .

# Security: Drop capabilities
USER app

# Security: Read-only filesystem
# (mount volumes for writable areas)
VOLUME ["/app/data"]

EXPOSE 3000

CMD ["node", "index.js"]
```

### .dockerignore

```
# Dependencies
node_modules
npm-debug.log

# Testing
coverage
.jest
*.test.js

# Environment & secrets
.env
.env.local
.env.*.local
secrets/

# Git
.git
.gitignore

# CI/CD
.github
.gitlab-ci.yml

# Documentation
README.md
docs/

# Build artifacts
dist
build
*.log

# IDE
.vscode
.idea
*.swp
```

## Docker Registry & CI/CD

### GitHub Container Registry

```yaml
# .github/workflows/docker-publish.yml
name: Docker Build & Push

on:
  push:
    branches: [ main ]
    tags: [ 'v*' ]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Log in to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=ref,event=pr
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

## Health Checks

### Node.js Health Endpoint

```typescript
// health.ts
export function setupHealthCheck(app: Express) {
  app.get('/health', async (req, res) => {
    const checks = {
      uptime: process.uptime(),
      timestamp: Date.now(),
      database: await checkDatabase(),
      redis: await checkRedis(),
      memory: process.memoryUsage(),
    }

    const isHealthy = checks.database && checks.redis

    res.status(isHealthy ? 200 : 503).json(checks)
  })
}

async function checkDatabase(): Promise<boolean> {
  try {
    await db.raw('SELECT 1')
    return true
  } catch {
    return false
  }
}

async function checkRedis(): Promise<boolean> {
  try {
    await redis.ping()
    return true
  } catch {
    return false
  }
}
```

## Monitoring & Logging

### Docker Compose with Logging

```yaml
services:
  app:
    image: myapp:latest
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    labels:
      - "prometheus.scrape=true"
      - "prometheus.port=9090"
```

### Prometheus Metrics Endpoint

```typescript
// metrics.ts
import promClient from 'prom-client'

const register = new promClient.Registry()

promClient.collectDefaultMetrics({ register })

const httpRequestDuration = new promClient.Histogram({
  name: 'http_request_duration_ms',
  help: 'Duration of HTTP requests in ms',
  labelNames: ['method', 'route', 'status_code'],
  buckets: [10, 50, 100, 500, 1000, 5000],
})

register.registerMetric(httpRequestDuration)

export function setupMetrics(app: Express) {
  app.get('/metrics', async (req, res) => {
    res.set('Content-Type', register.contentType)
    res.end(await register.metrics())
  })
}
```

## Best Practices Checklist

- ✅ Use multi-stage builds to minimize image size
- ✅ Run containers as non-root user
- ✅ Use specific base image versions (not `latest`)
- ✅ Implement health checks
- ✅ Set resource limits (CPU/memory)
- ✅ Use `.dockerignore` to exclude unnecessary files
- ✅ Scan images for vulnerabilities (Snyk, Trivy)
- ✅ Use secrets management (not env vars for sensitive data)
- ✅ Implement proper logging
- ✅ Add monitoring and metrics

## Integration with Agents

Works best with:
- **devops-automation** agent - Generates Docker configs
- **security-auditor** agent - Scans for container vulnerabilities
- **performance-optimizer** agent - Optimizes image size and startup time

## Tools & Resources

- **Docker**: Official container platform
- **Docker Compose**: Multi-container orchestration
- **Trivy**: Vulnerability scanner
- **Dive**: Image layer analyzer
- **Hadolint**: Dockerfile linter

## References

- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Node.js Docker Guide](https://nodejs.org/en/docs/guides/nodejs-docker-webapp/)
- [Docker Security](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
