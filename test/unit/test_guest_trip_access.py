"""Verify that travel planning requires an authenticated JWT."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

import jwt
from fastapi import HTTPException
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.api.routes import trip
from backend.app.config import get_settings
from backend.app.models.schemas import TripRequest


REQUEST = TripRequest(
    city="深圳",
    start_date="2026-09-05",
    end_date="2026-09-07",
    travel_days=3,
    transportation="公共交通",
    accommodation="经济型酒店",
)


def request_with_authorization(value: str | None = None) -> Request:
    headers = [] if value is None else [(b"authorization", value.encode("utf-8"))]
    return Request({"type": "http", "headers": headers})


class GuestTripAccessTest(unittest.TestCase):
    def test_request_without_authorization_is_rejected_before_planning(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(trip.plan_trip(REQUEST, request_with_authorization()))

        self.assertEqual(raised.exception.status_code, 401)

    def test_invalid_bearer_token_is_rejected_before_planning(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(trip.plan_trip(REQUEST, request_with_authorization("Bearer local:guest")))

        self.assertEqual(raised.exception.status_code, 401)

    def test_valid_jwt_is_accepted_by_the_authentication_boundary(self) -> None:
        settings = get_settings()
        token = jwt.encode({"sub": "test-user"}, settings.jwt_secret, algorithm="HS256")

        self.assertEqual(
            trip.authenticated_user_id(request_with_authorization(f"Bearer {token}")),
            "test-user",
        )


if __name__ == "__main__":
    unittest.main()
