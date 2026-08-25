"""Vercel Services entrypoint for the FastAPI control-plane API."""

import os

os.environ.setdefault("NETRA_SERVERLESS", "1")
os.environ.setdefault("SNAPSHOT_DIR", "/tmp/netra-snapshots")

from app.main import app  # noqa: E402,F401
