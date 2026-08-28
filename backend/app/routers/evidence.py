"""Authenticated evidence proxy.

The evidence bucket is PRIVATE - objects are never exposed by a public URL.
The browser loads them via <img src="/api/evidence/<key>?t=<jwt>">; a signed
token in the query is required because image tags cannot send an Authorization
header. The token is the same JWT issued at login, so evidence access is gated
by the same identity as the rest of the API.
"""
from fastapi import APIRouter, HTTPException, Query, Response

from .. import auth, storage

router = APIRouter(prefix="/api", tags=["evidence"])


@router.get("/evidence/{key:path}")
def get_evidence(key: str, t: str = Query(default="")):
    if auth.verify_token(t) is None:
        raise HTTPException(status_code=401, detail="valid access token required")
    data = storage.load(key)
    if data is None:
        raise HTTPException(status_code=404, detail="evidence not found")
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )
