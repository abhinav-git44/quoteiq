"""Auth (stdlib HMAC tokens + PBKDF2), audit logging, safe file storage."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AuditLog

TOKEN_TTL = 12 * 3600


# ------------------------------------------------------------------ passwords & tokens
def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000)
    return hmac.compare_digest(dk.hex(), h)


def make_token(user_id: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": user_id, "exp": int(time.time()) + TOKEN_TTL}).encode()).decode()
    sig = hmac.new(get_settings().jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_token(token: str) -> Optional[str]:
    try:
        payload, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    good = hmac.new(get_settings().jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, sig):
        return None
    data = json.loads(base64.urlsafe_b64decode(payload.encode()))
    return data["sub"] if data.get("exp", 0) > time.time() else None


# ------------------------------------------------------------------ audit
def audit(db: Session, action: str, entity_type: str, entity_id: Optional[str] = None, user_id: Optional[str] = None,
          before: Any = None, after: Any = None, meta: Optional[dict] = None, document_id: Optional[str] = None,
          org_id: Optional[str] = None) -> AuditLog:
    e = AuditLog(action=action, entity_type=entity_type, entity_id=entity_id, user_id=user_id, before=before, after=after,
                 meta=meta, document_id=document_id, org_id=org_id)
    db.add(e)
    return e


# ------------------------------------------------------------------ storage
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str) -> str:
    name = Path(name).name                      # strip any path components
    stem, dot, ext = name.rpartition(".")
    stem = _SAFE.sub("_", stem or name)[:80].strip("._") or "file"
    return f"{stem}.{_SAFE.sub('', ext)[:8].lower()}" if dot else stem


def store_file(src: Path | bytes, rfx_id: str, vendor_id: str, filename: str) -> Path:
    root = get_settings().storage_path.resolve()
    d = root / "rfx" / rfx_id / vendor_id
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{uuid.uuid4().hex[:12]}_{safe_name(filename)}"
    if not str(dest.resolve()).startswith(str(root)):
        raise ValueError("Invalid storage path")
    if isinstance(src, (bytes, bytearray)):
        dest.write_bytes(src)
    else:
        shutil.copyfile(src, dest)
    return dest
