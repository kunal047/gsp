import time
import unittest
from unittest.mock import patch

from app import auth
from app.rbac import Principal, require_ingestor
from app.routers.detections import normalize_plate
from fastapi import HTTPException


class JwtContractTest(unittest.TestCase):
    def test_round_trip_preserves_verified_role_and_scope(self):
        token = auth.issue_token(
            sub="ahmedabad.dcp", role="district_officer",
            scope="Ahmedabad", name="DCP Ahmedabad",
        )
        claims = auth.verify_token(token)
        self.assertEqual(claims["sub"], "ahmedabad.dcp")
        self.assertEqual(claims["role"], "district_officer")
        self.assertEqual(claims["scope"], "Ahmedabad")

    def test_tampered_token_is_rejected(self):
        token = auth.issue_token(sub="viewer", role="viewer", scope=None)
        head, body, signature = token.split(".")
        replacement = "A" if signature[-1] != "A" else "B"
        self.assertIsNone(auth.verify_token(f"{head}.{body}.{signature[:-1]}{replacement}"))

    def test_expired_token_is_rejected(self):
        token = auth.issue_token(sub="viewer", role="viewer", scope=None)
        with patch.object(auth.time, "time", return_value=time.time() + auth.JWT_TTL_SECONDS + 1):
            self.assertIsNone(auth.verify_token(token))


class PlateNormalizationTest(unittest.TestCase):
    def test_normalizes_spaces_and_punctuation(self):
        self.assertEqual(normalize_plate("gj 01-ab 1234"), "GJ01AB1234")

    def test_empty_plate_stays_empty(self):
        self.assertIsNone(normalize_plate(None))


class IngestAuthorizationTest(unittest.TestCase):
    def test_service_identity_can_ingest(self):
        principal = Principal("analytics-service", "state_admin", None)
        self.assertIs(require_ingestor(principal), principal)

    def test_human_admin_cannot_impersonate_analytics(self):
        with self.assertRaises(HTTPException) as context:
            require_ingestor(Principal("commissioner", "state_admin", None))
        self.assertEqual(context.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
