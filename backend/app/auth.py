"""Self-contained auth: signed JWTs + salted password hashing, stdlib only.

Replaces the previous spoofable X-User / X-Role headers. Identity and role are
carried in a JWT signed with a server-side secret (HS256), so a client cannot
forge a role - the signature won't verify. No external dependency is required
(hmac + hashlib.pbkdf2_hmac), so the backend image needs no rebuild.

For production the secret must be a strong per-deployment value in NETRA_JWT_SECRET
and users would come from the department IdP; the verification/authorization path
is identical either way.
"""
import base64
import hashlib
import hmac
import json
import os
import time

JWT_SECRET = os.getenv("NETRA_JWT_SECRET", "dev-insecure-change-me").encode()
JWT_TTL_SECONDS = int(os.getenv("NETRA_JWT_TTL", "43200"))  # 12h
PBKDF2_ITERATIONS = 240_000


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


# ---- password hashing (pbkdf2-hmac-sha256) ----
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2${PBKDF2_ITERATIONS}${_b64u(salt)}${_b64u(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt_b64, hash_b64 = stored.split("$")
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), _b64u_decode(salt_b64), int(iters)
        )
        return hmac.compare_digest(dk, _b64u_decode(hash_b64))
    except (ValueError, TypeError):
        return False


# ---- JWT (HS256) ----
def issue_token(*, sub: str, role: str, scope: str | None, name: str | None = None) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": sub, "role": role, "scope": scope, "name": name,
        "iat": now, "exp": now + JWT_TTL_SECONDS, "iss": "netra",
    }
    segments = [
        _b64u(json.dumps(header, separators=(",", ":")).encode()),
        _b64u(json.dumps(payload, separators=(",", ":")).encode()),
    ]
    signing_input = ".".join(segments).encode()
    signature = hmac.new(JWT_SECRET, signing_input, hashlib.sha256).digest()
    segments.append(_b64u(signature))
    return ".".join(segments)


def verify_token(token: str) -> dict | None:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        return None
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected = hmac.new(JWT_SECRET, signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64u_decode(sig_b64)):
        return None
    try:
        payload = json.loads(_b64u_decode(payload_b64))
    except (ValueError, TypeError):
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    return payload


# ---- seeding ----
DEFAULT_USERS = [
    {"username": "commissioner", "full_name": "State Commissioner",
     "role": "state_admin", "scope": None, "password": os.getenv("SEED_ADMIN_PASSWORD", "netra-admin")},
    {"username": "ahmedabad.dcp", "full_name": "DCP Ahmedabad",
     "role": "district_officer", "scope": "Ahmedabad", "password": os.getenv("SEED_OFFICER_PASSWORD", "netra-officer")},
    {"username": "control.viewer", "full_name": "Control Room Viewer",
     "role": "viewer", "scope": None, "password": os.getenv("SEED_VIEWER_PASSWORD", "netra-viewer")},
]


def seed_users(db):
    from . import models
    for spec in DEFAULT_USERS:
        existing = (
            db.query(models.User)
            .filter(models.User.username == spec["username"])
            .first()
        )
        if existing:
            continue
        db.add(models.User(
            username=spec["username"], full_name=spec["full_name"],
            role=spec["role"], scope=spec["scope"], active=True,
            password_hash=hash_password(spec["password"]),
        ))
    db.commit()
