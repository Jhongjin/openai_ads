from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app


class AccessAllowlistTests(unittest.TestCase):
    def test_access_is_open_when_allowlist_is_not_configured(self) -> None:
        client = TestClient(app)
        with patch.dict(os.environ, {"ACCESS_ALLOWED_IPS": ""}, clear=False):
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)

    def test_access_allows_forwarded_ip_in_configured_network(self) -> None:
        client = TestClient(app)
        with patch.dict(os.environ, {"ACCESS_ALLOWED_IPS": "203.0.113.0/24"}, clear=False):
            response = client.get("/health", headers={"x-vercel-forwarded-for": "203.0.113.12"})

        self.assertEqual(response.status_code, 200)

    def test_access_denies_forwarded_ip_outside_configured_network(self) -> None:
        client = TestClient(app)
        with patch.dict(os.environ, {"ACCESS_ALLOWED_IPS": "203.0.113.0/24"}, clear=False):
            response = client.get("/health", headers={"x-forwarded-for": "198.51.100.12"})

        self.assertEqual(response.status_code, 403)
        self.assertIn("사내 네트워크", response.text)


if __name__ == "__main__":
    unittest.main()
