"""QuoteIQ API. Run: uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes_core, routes_eval
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("quoteiq")

app = FastAPI(title="QuoteIQ API", version="0.1.0",
              description="AI procurement intelligence — synthetic demo for the Aerchain take-home.")
import os

_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_origin_regex=os.environ.get("CORS_ORIGIN_REGEX") or None,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

_hits: dict[str, deque] = defaultdict(deque)
AI_PATHS = ("/analyst/chat", "/rfx/copilot", "/extract", "/retry")


@app.middleware("http")
async def rate_limit_and_log(request: Request, call_next):
    """Simple in-memory limit on AI-backed endpoints (30/min per client) + structured access log."""
    t0 = time.time()
    if request.method == "POST" and any(p in request.url.path for p in AI_PATHS):
        key = request.client.host if request.client else "?"
        q = _hits[key]
        while q and q[0] < t0 - 60:
            q.popleft()
        if len(q) >= 30:
            return JSONResponse({"detail": "Too many AI requests — wait a minute."}, status_code=429)
        q.append(t0)
    resp = await call_next(request)
    log.info("%s %s %s %dms", request.method, request.url.path, resp.status_code, int((time.time() - t0) * 1000))
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Internal error. The incident was logged."}, status_code=500)


@app.get("/api/health")
def health():
    s = get_settings()
    return {"ok": True, "ai_enabled": s.ai_enabled, "model": s.anthropic_model if s.ai_enabled else None,
            "base_currency": s.base_currency}


app.include_router(routes_core.router)
app.include_router(routes_eval.router)
