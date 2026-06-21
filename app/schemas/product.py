import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCreate(BaseModel):
    """Schema for creating a new product."""
    name: str = Field(..., min_length=1, max_length=255, description="Product name")
    category: str = Field(..., min_length=1, max_length=100, description="Product category")
    price: float = Field(..., gt=0, le=999999.99, description="Product price")

    @field_validator("name", "category")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class ProductUpdate(BaseModel):
    """Schema for partial product updates."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    price: Optional[float] = Field(None, gt=0, le=999999.99)

    @field_validator("name", "category")
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else v


class ProductResponse(BaseModel):
    """Schema for product API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    price: float
    created_at: datetime
    updated_at: datetime


class CursorParams(BaseModel):
    """Query parameters for cursor-based pagination."""
    cursor: Optional[str] = Field(
        None,
        description="Opaque cursor token for the next page. Omit for the first page.",
    )
    limit: int = Field(
        20,
        ge=1,
        le=100,
        description="Number of items per page (1-100).",
    )
    category: Optional[str] = Field(
        None,
        description="Filter products by category (exact match).",
    )


class PaginationMeta(BaseModel):
    """Metadata about the current page of results."""
    next_cursor: Optional[str] = Field(
        None,
        description="Cursor to fetch the next page. null if this is the last page.",
    )
    has_next: bool = Field(
        description="Whether more results exist after this page.",
    )
    page_size: int = Field(
        description="Number of items returned in this page.",
    )


class PaginatedResponse(BaseModel):
    """Paginated API response with cursor-based navigation."""
    data: list[ProductResponse]
    pagination: PaginationMeta
