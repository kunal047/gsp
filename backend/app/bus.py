"""Event bus publisher (Redis Streams in the prototype; MQTT + Redpanda in the
statewide design - see SCALABILITY.md). Non-fatal on failure."""
import json
import os

import redis

_client = None


def _redis():
    global _client
    if _client is None:
        _client = redis.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379/0"),
            decode_responses=True,
        )
    return _client


def publish_detection(payload: dict):
    try:
        _redis().xadd(
            "detections",
            {"data": json.dumps(payload, default=str)},
            maxlen=2000,
            approximate=True,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[bus] publish failed: {e}")
