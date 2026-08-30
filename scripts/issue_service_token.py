#!/usr/bin/env python3
"""Issue the internal analytics/gateway JWT from NETRA_JWT_SECRET."""

import base64
import hashlib
import hmac
import json
import os
import time

if not os.getenv("NETRA_JWT_SECRET"):
    raise SystemExit("NETRA_JWT_SECRET is required")
ttl = int(os.getenv("NETRA_JWT_TTL", "31536000"))


def b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


now = int(time.time())
header = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
payload = b64u(json.dumps({
    "sub": "analytics-service", "role": "state_admin", "scope": None,
    "name": "Netra internal services", "iat": now, "exp": now + ttl,
    "iss": "netra",
}, separators=(",", ":")).encode())
signing_input = f"{header}.{payload}".encode()
signature = b64u(hmac.new(os.environ["NETRA_JWT_SECRET"].encode(), signing_input, hashlib.sha256).digest())
print(f"{header}.{payload}.{signature}")
