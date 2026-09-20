# One image for the Warden API, the Workspaces demo and the seed job: they share the
# SDK and the seed script imports both packages.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY sdk/pyproject.toml sdk/
COPY sdk/src sdk/src
COPY backend/pyproject.toml backend/alembic.ini backend/
COPY backend/src backend/src
COPY backend/migrations backend/migrations
COPY demo-app/pyproject.toml demo-app/
COPY demo-app/src demo-app/src
COPY scripts/seed.py scripts/

RUN pip install ./sdk[fastapi] ./backend ./demo-app \
    && useradd --create-home --uid 10001 warden

USER warden

ENV WARDEN_HOST=0.0.0.0 \
    WARDEN_ENV=production \
    WORKSPACES_HOST=0.0.0.0

EXPOSE 8106 27106

CMD ["warden"]
