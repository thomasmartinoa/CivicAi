# Python 3.14 to match development. The project is built and tested on 3.14 — the
# previous version of this file pinned 3.12, so the image ran a different interpreter
# from every test that had ever passed. bcrypt is used directly rather than through
# passlib for this reason, and faiss-cpu ships cp314 wheels.
FROM python:3.14-slim

WORKDIR /app

# Build tooling for any wheel without a cp314 build, removed in the same layer so it
# does not ship.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y build-essential || true

COPY . .

# /data holds the SQLite database and the FAISS index; docker-compose mounts a volume
# here so neither is lost when the container is replaced.
RUN mkdir -p /data

# Migrations run on every start, not at build time: the database lives in a volume
# that does not exist yet when the image is built. Alembic is idempotent, so a
# restart against an up-to-date database is a no-op.
# Migrate, then seed, then serve. Seeding is idempotent — seed_database returns early
# when a tenant already exists — so this is a no-op after the first start. Without it a
# fresh container has no tenant and no admin user, and the HTTP seed endpoint is gated
# on ENVIRONMENT=development, so there would be no way to create either.
CMD ["sh", "-c", "python -m alembic upgrade head && python -m app.services.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
