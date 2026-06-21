"""Product API endpoints with cursor-based pagination.

Key design decisions:
─────────────────────────────────────────────────────────────────────────
• Keyset pagination via composite (created_at DESC, id DESC) ordering.
  Unlike OFFSET, this is O(1) seek time regardless of page depth and
  is immune to phantom reads (new inserts don't shift the window).

• The category filter uses an equality predicate that sits before the
  range predicate in our composite index, allowing Postgres to perform
  an index-only scan with no filesort.

• We fetch limit+1 rows to detect whether a next page exists, then
  slice to limit. This avoids a separate COUNT query.
─────────────────────────────────────────────────────────────────────────
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.product import Product
from app.pagination.cursor import decode_cursor, encode_cursor
from app.schemas.product import (
    PaginatedResponse,
    PaginationMeta,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("", response_model=PaginatedResponse)
async def list_products(
    cursor: Optional[str] = Query(
        None, description="Opaque cursor for the next page"
    ),
    limit: int = Query(
        20, ge=1, le=100, description="Items per page (1-100)"
    ),
    category: Optional[str] = Query(
        None, description="Filter by category (exact match)"
    ),
    db: AsyncSession = Depends(get_db),
):
    """List products with cursor-based keyset pagination.
    
    Returns products ordered by created_at DESC, id DESC.
    Supports optional category filtering.
    
    Pagination contract:
    - First request: omit `cursor` to get the first page.
    - Subsequent requests: pass `next_cursor` from the previous response.
    - When `has_next` is false, you've reached the end.
    """
    query = select(Product)

    # Apply category filter
    if category:
        query = query.where(Product.category == category)

    # Apply cursor-based keyset condition
    if cursor:
        cursor_created_at, cursor_id = decode_cursor(cursor)
        # Row-value comparison: (created_at, id) < (cursor_created_at, cursor_id)
        # This leverages the composite index for an efficient seek.
        query = query.where(
            tuple_(Product.created_at, Product.id)
            < tuple_(cursor_created_at, cursor_id)
        )

    # Order by composite key (must match the index)
    query = query.order_by(Product.created_at.desc(), Product.id.desc())

    # Fetch one extra to determine if there's a next page
    query = query.limit(limit + 1)

    result = await db.execute(query)
    products = list(result.scalars().all())

    # Determine if there are more pages
    has_next = len(products) > limit
    if has_next:
        products = products[:limit]  # Trim the extra row

    # Build next cursor from the last item
    next_cursor = None
    if has_next and products:
        last = products[-1]
        next_cursor = encode_cursor(last.created_at, last.id)

    return PaginatedResponse(
        data=[ProductResponse.model_validate(p) for p in products],
        pagination=PaginationMeta(
            next_cursor=next_cursor,
            has_next=has_next,
            page_size=len(products),
        ),
    )


@router.get("/categories", response_model=list[str])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """List all distinct product categories, sorted alphabetically."""
    result = await db.execute(
        select(Product.category)
        .distinct()
        .order_by(Product.category)
    )
    return list(result.scalars().all())


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single product by ID."""
    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found",
        )
    return ProductResponse.model_validate(product)


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new product."""
    product = Product(
        name=payload.name,
        category=payload.category,
        price=payload.price,
    )
    db.add(product)
    await db.flush()
    await db.refresh(product)
    return ProductResponse.model_validate(product)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Partially update a product."""
    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    await db.flush()
    await db.refresh(product)
    return ProductResponse.model_validate(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a product."""
    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found",
        )
    await db.delete(product)
