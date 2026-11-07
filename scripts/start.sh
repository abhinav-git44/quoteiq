#!/bin/sh
# Container entrypoint: migrate, start the API, and seed + extract the demo once (in the background).
set -e
cd /app/backend
alembic upgrade head
python /app/scripts/restore_files.py || echo "restore_files skipped"
( sleep 5 && python /app/scripts/seed_demo.py --if-empty --extract || echo "Seeding failed — see logs" ) &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
