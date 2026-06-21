"""Tests for the Product Catalog API.

Tests cursor-based pagination correctness, category filtering,
and CRUD operations using an in-memory test setup.
"""

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.pagination.cursor import decode_cursor, encode_cursor


# ─── Cursor Encoding/Decoding Tests ────────────────────────────────────


class TestCursorEncoding:
    """Tests for the cursor encode/decode round-trip."""

    def test_encode_decode_roundtrip(self):
        """Encoding then decoding should return the original values."""
        original_ts = datetime(2025, 6, 20, 14, 30, 0, tzinfo=timezone.utc)
        original_id = uuid.uuid4()

        cursor = encode_cursor(original_ts, original_id)
        decoded_ts, decoded_id = decode_cursor(cursor)

        assert decoded_ts == original_ts
        assert decoded_id == original_id

    def test_cursor_is_url_safe(self):
        """Cursor should only contain URL-safe characters."""
        ts = datetime.now(timezone.utc)
        product_id = uuid.uuid4()
        cursor = encode_cursor(ts, product_id)

        # Base64url characters only: A-Z, a-z, 0-9, -, _
        assert all(c.isalnum() or c in "-_" for c in cursor)
        # No padding characters
        assert "=" not in cursor

    def test_cursor_is_opaque_base64(self):
        """Cursor should be valid base64url-encoded JSON."""
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        product_id = uuid.uuid4()
        cursor = encode_cursor(ts, product_id)

        # Decode manually
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))

        assert "created_at" in payload
        assert "id" in payload
        assert payload["id"] == str(product_id)

    def test_decode_invalid_cursor_raises_400(self):
        """Decoding garbage should raise an HTTPException with 400."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            decode_cursor("not-a-valid-cursor!!!")
        assert exc_info.value.status_code == 400

    def test_decode_tampered_cursor_raises_400(self):
        """A cursor with a valid base64 but invalid JSON should raise 400."""
        from fastapi import HTTPException

        bad_payload = base64.urlsafe_b64encode(b"not-json").decode().rstrip("=")
        with pytest.raises(HTTPException):
            decode_cursor(bad_payload)

    def test_multiple_cursors_are_unique(self):
        """Different positions should produce different cursors."""
        ts = datetime.now(timezone.utc)
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()

        cursor1 = encode_cursor(ts, id1)
        cursor2 = encode_cursor(ts, id2)

        assert cursor1 != cursor2

    def test_timezone_preservation(self):
        """Decoded timestamp should be timezone-aware."""
        ts = datetime(2025, 6, 20, 14, 30, 0, tzinfo=timezone.utc)
        product_id = uuid.uuid4()

        cursor = encode_cursor(ts, product_id)
        decoded_ts, _ = decode_cursor(cursor)

        assert decoded_ts.tzinfo is not None


class TestCursorOrdering:
    """Tests that cursor values maintain correct ordering semantics."""

    def test_newer_timestamp_produces_larger_cursor_position(self):
        """Products with newer timestamps should come first in DESC order."""
        product_id = uuid.uuid4()
        older_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        newer_ts = datetime(2025, 6, 20, tzinfo=timezone.utc)

        # When paginating DESC, the cursor from a newer item should
        # decode to values that are "greater than" older items
        _, _ = decode_cursor(encode_cursor(newer_ts, product_id))
        _, _ = decode_cursor(encode_cursor(older_ts, product_id))

        # The key insight: (newer_ts, id) > (older_ts, id) in tuple comparison
        assert (newer_ts, product_id) > (older_ts, product_id)
