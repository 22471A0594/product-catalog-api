import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Product(Base):
    """Product model with composite indexes for keyset pagination.
    
    Index strategy:
    ─────────────────────────────────────────────────────────────────────
    ix_products_created_id:
        Composite index on (created_at DESC, id DESC).
        Covers the default listing query: ORDER BY created_at DESC, id DESC
        with WHERE (created_at, id) < (cursor_ts, cursor_id).
        This is THE critical index for cursor-based pagination.
    
    ix_products_category_created_id:
        Composite index on (category, created_at DESC, id DESC).
        Covers filtered queries: WHERE category = ? ORDER BY created_at DESC, id DESC.
        The leading equality predicate on category allows Postgres to seek
        directly into the matching partition of the B-tree, then scan
        the (created_at, id) suffix in order — no sort needed.
    ─────────────────────────────────────────────────────────────────────
    """

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique product identifier (UUIDv4).",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Human-readable product name.",
    )
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Product category for filtering.",
    )
    price: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Product price with 2 decimal precision.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Timestamp of product creation (UTC).",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Timestamp of last update (UTC).",
    )

    __table_args__ = (
        Index(
            "ix_products_created_id",
            created_at.desc(),
            id.desc(),
        ),
        Index(
            "ix_products_category_created_id",
            "category",
            created_at.desc(),
            id.desc(),
        ),
    )

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, name='{self.name}', category='{self.category}')>"
