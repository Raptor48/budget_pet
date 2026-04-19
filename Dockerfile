# syntax=docker/dockerfile:1.7
#
# Budget Pet V2 — production image for the FastAPI service.
#
# Design notes:
#   * Multi-stage so the final image never carries pip caches or build
#     tools. Shaves >100 MB off a naive single-stage build.
#   * Runs as an unprivileged user (`app`, uid 1001).
#   * `tini` as PID 1 so APScheduler worker threads + uvicorn workers get
#     a clean SIGTERM propagation on Railway deploys / scale events.
#   * Listens on `${PORT}` (Railway injects it) with a safe default for
#     local `docker run`.
#   * The same image is used by the `FastAPI` Railway service; the
#     Telegram bot service (`telegram bot`) runs from `Procfile` via
#     nixpacks — see `docs/` and `.cursor/rules/railway-cli.mdc`.

ARG PYTHON_VERSION=3.12

# -----------------------------------------------------------------------------
# Stage 1 — build wheels for every runtime dependency.
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# `build-essential` covers any native build for deps that lack a manylinux
# wheel on a new Python release (defensive; today all our deps ship
# wheels). Kept strictly in the builder layer so it never bloats runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt ./
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2 — slim runtime image.
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_PORT=8000

# Minimal runtime OS deps:
#   * `ca-certificates` — outbound TLS to Plaid / Telegram / Stripe-style APIs.
#   * `tini`            — PID 1 init that reaps zombies and forwards signals.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home-dir /home/app \
        --create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Install Python deps from the pre-built wheels only — no network access
# needed at this stage, and no pip cache ends up in the image.
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Copy application source (see `.dockerignore` — frontend/, tests/, .env*,
# caches, and docs are excluded).
COPY --chown=app:app . /app

USER app

EXPOSE 8000

# `tini` as init so SIGTERM from Railway propagates to uvicorn cleanly and
# APScheduler's worker threads get a chance to shut down.
#
# PORT handling: Railway's HTTP proxy for this service has its target port
# pinned to 8000 (matching the original `EXPOSE 8000` contract). Changing
# the listening port without also updating the Railway service's
# networking config produced a 502 from the edge on every request — this
# broke login until we rebuilt. We therefore respect `APP_PORT` (defaults
# to 8000) rather than the Railway-injected `$PORT`, which can differ at
# runtime. Override `APP_PORT` (and `EXPOSE`) only if you also reconfigure
# Railway's target port to match.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec uvicorn web.main:app --host 0.0.0.0 --port ${APP_PORT:-8000}"]
