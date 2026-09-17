"""Read-only V2 API with signed pagination and a fail-closed local boundary."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from pathlib import Path

import duckdb
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from marketrank.evidence import canonical
from marketrank.replay.release import REF, verify_release
from .contracts import CustomersResponse, RecommendationsResponse, ReleasesResponse, QualityResponse


class ApiError(Exception):
    def __init__(self, code: str, status: int, message: str):
        self.code, self.status, self.message = code, status, message


def encode_cursor(key: bytes, payload: dict) -> str:
    body = canonical(payload)
    return base64.urlsafe_b64encode(body + hmac.digest(key, body, "sha256")).decode().rstrip("=")


def decode_cursor(key: bytes, value: str, binding: dict) -> int:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        body, signature = raw[:-32], raw[-32:]
        if not hmac.compare_digest(signature, hmac.digest(key, body, "sha256")):
            raise ValueError
        payload = json.loads(body)
        if set(payload) != {*binding, "position"} or any(payload.get(k) != v for k,v in binding.items()):
            raise ValueError
        if type(payload["position"]) is not int or payload["position"] < 0:
            raise ValueError
        return payload["position"]
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise ApiError("INVALID_CURSOR", 400, "The page reference is invalid for this query.") from None


def create_app(release_root: Path | None = None, *, cursor_key: bytes | None = None, host: str = "127.0.0.1") -> FastAPI:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("nonlocal startup requires a separately verified private-access deployment")
    key = cursor_key or secrets.token_bytes(32)
    if len(key) < 32:
        raise ValueError("cursor signing key must be at least 32 bytes")
    # Keep OpenAPI JSON, but do not load third-party CDN scripts on a private
    # API origin through the default interactive documentation pages.
    app = FastAPI(title="MarketRank Historical Replay", version="2.0", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173", "http://127.0.0.1:3000"], allow_methods=["GET"], allow_headers=[])
    manifest = None
    signatures = None
    def file_signatures():
        return [(p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns)
                for p in (release_root/"manifest.json",release_root/"replay.duckdb")]
    if release_root is not None:
        try:
            manifest = verify_release(release_root)
            signatures = file_signatures()
        except (OSError, ValueError, KeyError, duckdb.Error):
            # Process remains live for diagnosis, but no invalid release is served.
            manifest = None

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        return JSONResponse(status_code=422,content={"schema_version":"workbench-error.v2","error":{
            "code":"INVALID_REQUEST","message":"The request parameters are invalid.","request_id":"req_"+secrets.token_hex(8)}})

    @app.exception_handler(ApiError)
    async def safe_error(request: Request, error: ApiError):
        return JSONResponse(status_code=error.status, content={"schema_version": "workbench-error.v2", "error": {
            "code": error.code, "message": error.message, "request_id": "req_" + secrets.token_hex(8)}})

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception):
        return JSONResponse(status_code=503, content={"schema_version": "workbench-error.v2", "error": {
            "code": "RELEASE_UNAVAILABLE", "message": "The historical release is temporarily unavailable.", "request_id": "req_" + secrets.token_hex(8)}})

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def ready(release_id: str | None = None):
        if manifest is None:
            raise ApiError("NOT_READY", 503, "No validated historical release is ready.")
        try:
            if file_signatures()!=signatures:
                raise OSError("immutable artifacts changed")
        except OSError:
            raise ApiError("NOT_READY",503,"The historical release must be revalidated.") from None
        if release_id is not None and release_id != manifest["release_id"]:
            raise ApiError("RELEASE_NOT_FOUND", 404, "The historical release was not found.")
        return manifest

    def connect():
        ready()
        return duckdb.connect(str(release_root / "replay.duckdb"), read_only=True)

    @app.get("/health/live")
    def live():
        return {"status": "live"}

    @app.get("/health/ready")
    def readiness():
        meta = ready()
        return {"status": "ready", "release_id": meta["release_id"], "release_status": meta["status"]}

    @app.get("/api/v2/releases",response_model=ReleasesResponse)
    def releases():
        meta = ready()
        return {"schema_version": "workbench-releases.v2", "releases": [{k:meta[k] for k in (
            "release_id", "status", "dates", "customer_count", "ranking_mode", "score_semantics", "warning",
            "model_available_after", "calibrator_available_after")} ]}

    @app.get("/api/v2/releases/{release_id}/quality",response_model=QualityResponse)
    def quality(release_id: str):
        meta = ready(release_id)
        return {"schema_version": "workbench-quality.v2", "release_id": release_id,
                "quality": meta["quality"], "provenance": meta["provenance"], "status": meta["status"], "warning": meta["warning"]}

    @app.get("/api/v2/releases/{release_id}/customers",response_model=CustomersResponse)
    def customers(release_id: str, limit: int = Query(25, ge=1, le=100), cursor: str | None = Query(None, max_length=2048),
                  q: str = Query("", max_length=100), sort: str = "display_label_asc"):
        ready(release_id)
        if sort not in {"display_label_asc", "display_label_desc"}:
            raise ApiError("INVALID_SORT", 400, "The requested ordering is not supported.")
        binding = {"release_id": release_id, "sort": sort, "query": q}
        offset = decode_cursor(key, cursor, binding) if cursor else 0
        direction = "ASC" if sort == "display_label_asc" else "DESC"
        with connect() as db:
            rows = db.execute(f"SELECT customer_ref,display_label FROM customers WHERE contains(lower(display_label),lower(?)) OR contains(customer_ref,?) ORDER BY display_label {direction} LIMIT ? OFFSET ?", [q,q,limit+1,offset]).fetchall()
        return {"schema_version": "workbench-customers.v2", "release_id": release_id,
                "customers": [{"customer_ref": ref, "display_label": label} for ref,label in rows[:limit]],
                "next_cursor": encode_cursor(key, {**binding, "position": offset+limit}) if len(rows)>limit else None}

    @app.get("/api/v2/releases/{release_id}/customers/{customer_ref}/recommendations",response_model=RecommendationsResponse)
    def recommendations(release_id: str, customer_ref: str, as_of: str):
        meta = ready(release_id)
        if as_of not in meta["dates"]:
            raise ApiError("INVALID_REPLAY_DATE", 400, "Select an approved historical replay date.")
        if not REF.fullmatch(customer_ref):
            raise ApiError("CUSTOMER_NOT_FOUND", 404, "The historical customer reference was not found.")
        with connect() as db:
            row = db.execute("SELECT payload FROM recommendations WHERE customer_ref=? AND as_of=?", [customer_ref,as_of]).fetchone()
        if row is None:
            raise ApiError("CUSTOMER_NOT_FOUND", 404, "The historical customer reference was not found.")
        return json.loads(row[0])

    return app
