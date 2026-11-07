"""Free hosting has no persistent disk: on each container start, put back any demo document whose
stored file is gone (matched by sha256 against demo_data/) and rebuild perspective-corrected photos.
Extraction results live in Postgres, so nothing is re-extracted and no AI call is made."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import Document  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.extraction.parsers import parse_image, sha256_file  # noqa: E402


def main():
    by_hash = {sha256_file(p): p for p in (ROOT / "demo_data").rglob("*") if p.is_file() and p.suffix != ".json"}
    restored = rebuilt = missing = 0
    with session_scope() as db:
        for d in db.scalars(select(Document)):
            p = Path(d.stored_path)
            if not p.exists():
                src = by_hash.get(d.sha256)
                if src is None:
                    missing += 1
                    continue
                p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, p)
                restored += 1
            if d.doc_format == "image" and (not d.derived_path or not Path(d.derived_path).exists()):
                doc = parse_image(p, get_settings().storage_path / "derived" / d.id)
                d.derived_path = doc.derived_image_path
                rebuilt += 1
    print(f"restore_files: restored {restored}, rebuilt {rebuilt} corrected image(s), {missing} non-demo file(s) unavailable")


if __name__ == "__main__":
    main()
