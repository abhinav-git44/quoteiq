from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Rfx, User
from app.db.session import get_db
from app.services.common import read_token


def current_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    uid = read_token(authorization.split(" ", 1)[1])
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(401, "Session expired — please sign in again")
    return user


def rfx_for(rfx_id: str, user: User, db: Session) -> Rfx:
    rfx = db.get(Rfx, rfx_id)
    if not rfx or rfx.org_id != user.org_id:
        raise HTTPException(404, "RFx not found")
    return rfx
