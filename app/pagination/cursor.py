"""Cursor encoding/decoding for keyset pagination.

Design decisions:
─────────────────────────────────────────────────────────────────────────
1. The cursor encodes (created_at, id) — the exact columns in our
   composite ORDER BY clause. This makes the cursor position-independent:
   inserting or deleting rows never shifts the "window" of results.

2. We use base64url encoding (URL-safe, no padding) of a JSON payload.
   This is opaque to the client but trivially debuggable by engineers.
   In a higher-security context you could HMAC-sign the cursor.

3. ISO-8601 for the timestamp preserves timezone information and is
   unambiguous across Postgres, Python, and JSON.
─────────────────────────────────────────────────────────────────────────
"""

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import HTTPException, status


def encode_cursor(created_at: datetime, product_id: uuid.UUID) -> str:
    """Encode pagination position into an opaque cursor string.
    
    Args:
        created_at: The created_at timestamp of the last item on the current page.
        product_id: The UUID of the last item on the current page.
    
    Returns:
        A URL-safe base64-encoded cursor string.
    """
    payload = json.dumps({
        "created_at": created_at.isoformat(),
        "id": str(product_id),
    })
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Tuple[datetime, uuid.UUID]:
    """Decode an opaque cursor string back into pagination position.
    
    Args:
        cursor: The base64url-encoded cursor string from the client.
    
    Returns:
        A tuple of (created_at, product_id) representing the pagination position.
    
    Raises:
        HTTPException: If the cursor is malformed or contains invalid data.
    """
    try:
        # Restore base64 padding
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        
        created_at = datetime.fromisoformat(payload["created_at"])
        # Ensure timezone awareness
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        
        product_id = uuid.UUID(payload["id"])
        return created_at, product_id
    except (json.JSONDecodeError, KeyError, ValueError, Exception) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cursor: {str(e)}",
        )
