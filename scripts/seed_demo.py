"""Seed the synthetic demo into PostgreSQL and (optionally) run extraction.

  python scripts/generate_documents.py          # creates demo_data/ (already committed)
  cd backend && alembic upgrade head && cd ..
  python scripts/seed_demo.py --extract         # registers docs and runs the REAL extraction jobs

Without an AI key (GEMINI_API_KEY or ANTHROPIC_API_KEY), jobs finish as AI_UNAVAILABLE: documents are parsed and viewable,
but no values are extracted (nothing is fabricated).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import engine, session_scope  # noqa: E402
from app.services.rfx_service import run_job, snapshot_normalized  # noqa: E402
from app.services.seed import DEMO_EMAIL, DEMO_PASSWORD, seed  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true", help="Run extraction jobs now (sequentially)")
    ap.add_argument("--reset", action="store_true", help="DROP all tables and recreate (dev only)")
    ap.add_argument("--if-empty", action="store_true", help="Do nothing if the demo RFx already exists (container start)")
    a = ap.parse_args()
    if a.if_empty:
        from sqlalchemy import select
        from app.db.models import Rfx
        with session_scope() as db:
            if db.scalar(select(Rfx.id).limit(1)):
                print("Demo already seeded; skipping.")
                return
    if a.reset:
        Base.metadata.drop_all(engine())
        Base.metadata.create_all(engine())
    with session_scope() as db:
        rfx, jobs = seed(db, ROOT / "demo_data")
        rfx_id = rfx.id
    print(f"Seeded {rfx_id} with {len(jobs)} extraction jobs queued.")
    if a.extract:
        if not get_settings().ai_enabled:
            print("No AI key set: jobs will complete as AI_UNAVAILABLE (parsed, nothing extracted).")
        for j in jobs:
            run_job(j)
            print(f"  job {j} done")
    with session_scope() as db:
        snapshot_normalized(db, rfx_id)
    print(f"\nLogin: {DEMO_EMAIL} / {DEMO_PASSWORD}   (approver: vp@kaveri.example / {DEMO_PASSWORD})")


if __name__ == "__main__":
    main()
