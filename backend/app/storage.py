"""Evidence object storage.

Detection/alert evidence images live in a PRIVATE Supabase Storage bucket
(S3-class object storage), not on the container's local disk - so evidence
survives redeploys, is shared across replicas, and is served from durable
storage. Implemented with the stdlib (urllib) so the backend needs no extra
dependency. Falls back to the local `/snapshots` volume when Supabase Storage
is not configured, keeping single-host / offline runs working.

The bucket is private; objects are reached only through the backend's
authenticated `/api/evidence/{key}` proxy (see routers/evidence.py), never by a
public URL. To point at AWS S3 / Supabase Storage in another project, change the
env below - the call sites are unchanged.
"""
import os
import uuid
import urllib.error
import urllib.request

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
# Prefer a dedicated storage key; the project's publishable key works because a
# scoped RLS policy grants it insert/select on just the evidence bucket.
STORAGE_KEY = os.getenv("SUPABASE_STORAGE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
BUCKET = os.getenv("EVIDENCE_BUCKET", "evidence")
LOCAL_DIR = os.getenv("SNAPSHOT_DIR", "/snapshots")

BACKEND = os.getenv("STORAGE_BACKEND") or (
    "supabase" if (SUPABASE_URL and STORAGE_KEY) else "local"
)

EVIDENCE_PREFIX = "/api/evidence/"
LOCAL_PREFIX = "/snapshots/"


def using_supabase() -> bool:
    return BACKEND == "supabase" and bool(SUPABASE_URL and STORAGE_KEY)


def _headers(extra: dict | None = None) -> dict:
    h = {"apikey": STORAGE_KEY, "Authorization": f"Bearer {STORAGE_KEY}"}
    if extra:
        h.update(extra)
    return h


def save(raw: bytes) -> str | None:
    """Persist JPEG bytes and return the reference stored on the detection row.

    Supabase -> "/api/evidence/<key>" (served via the authenticated proxy).
    Local    -> "/snapshots/<key>"   (served via the StaticFiles mount).
    """
    key = f"{uuid.uuid4().hex}.jpg"
    if using_supabase():
        url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}"
        req = urllib.request.Request(
            url, data=raw, method="POST",
            headers=_headers({"Content-Type": "image/jpeg", "x-upsert": "true"}),
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201):
                    return EVIDENCE_PREFIX + key
                print(f"[storage] supabase upload status {resp.status}")
        except (urllib.error.URLError, OSError) as exc:
            print(f"[storage] supabase upload failed: {exc}")
        return None
    try:
        os.makedirs(LOCAL_DIR, exist_ok=True)
        with open(os.path.join(LOCAL_DIR, key), "wb") as fh:
            fh.write(raw)
        return LOCAL_PREFIX + key
    except OSError as exc:
        print(f"[storage] local write failed: {exc}")
        return None


def load(key: str) -> bytes | None:
    """Fetch object bytes for the authenticated evidence proxy."""
    key = key.lstrip("/")
    if using_supabase():
        url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}"
        req = urllib.request.Request(url, headers=_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as exc:
            print(f"[storage] supabase fetch failed: {exc}")
        return None
    try:
        path = os.path.join(LOCAL_DIR, key)
        if not os.path.abspath(path).startswith(os.path.abspath(LOCAL_DIR)):
            return None  # path traversal guard
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None
