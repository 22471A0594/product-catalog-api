import pytest
import uuid
from datetime import datetime, timezone, timedelta
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.config import get_settings
from app.database import get_db
from app.models.product import Product

settings = get_settings()

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_session():
    """Create a local session and engine tied to the active test loop.
    
    Overrides FastAPI get_db dependency.
    """
    test_engine = create_async_engine(settings.DATABASE_URL)
    test_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async def _get_db_override():
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
                
    app.dependency_overrides[get_db] = _get_db_override
    
    async with test_session_factory() as session:
        yield session
        
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.fixture(autouse=True)
async def cleanup_test_products(db_session):
    """Ensure any test products created during tests are deleted."""
    yield
    # Clean up test products at teardown
    await db_session.execute(
        delete(Product).where(Product.category.like("Test%"))
    )
    await db_session.commit()


async def test_health_endpoints():
    """Verify health check endpoints return 200 OK."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response1 = await ac.get("/")
        response2 = await ac.get("/health")
        
    assert response1.status_code == 200
    assert response1.json()["status"] == "healthy"
    assert response2.status_code == 200
    assert response2.json()["status"] == "healthy"


async def test_crud_operations(db_session):
    """Test full CRUD lifecycle for a product."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Create Product
        payload = {
            "name": "Test Gizmo Deluxe",
            "category": "TestGizmos",
            "price": 49.99
        }
        create_resp = await ac.post("/api/v1/products", json=payload)
        assert create_resp.status_code == 201
        product_data = create_resp.json()
        assert product_data["name"] == "Test Gizmo Deluxe"
        assert product_data["category"] == "TestGizmos"
        assert product_data["price"] == 49.99
        assert "id" in product_data
        product_id = product_data["id"]

        # 2. Get Product
        get_resp = await ac.get(f"/api/v1/products/{product_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Test Gizmo Deluxe"

        # 3. Update Product (Partial)
        update_payload = {
            "price": 39.99,
            "name": "Test Gizmo Ultra"
        }
        update_resp = await ac.patch(f"/api/v1/products/{product_id}", json=update_payload)
        assert update_resp.status_code == 200
        updated_data = update_resp.json()
        assert updated_data["price"] == 39.99
        assert updated_data["name"] == "Test Gizmo Ultra"
        assert updated_data["category"] == "TestGizmos"  # Unchanged

        # 4. Delete Product
        delete_resp = await ac.delete(f"/api/v1/products/{product_id}")
        assert delete_resp.status_code == 204

        # 5. Verify Deletion
        get_deleted_resp = await ac.get(f"/api/v1/products/{product_id}")
        assert get_deleted_resp.status_code == 404


async def test_get_nonexistent_product_returns_404():
    """Verify requesting a missing UUID returns 404."""
    random_uuid = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get(f"/api/v1/products/{random_uuid}")
    assert response.status_code == 404


async def test_list_categories(db_session):
    """Verify distinct categories endpoint retrieves test category."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create a test product to ensure category exists
        await ac.post("/api/v1/products", json={
            "name": "Cat Test Item",
            "category": "TestCategoryList",
            "price": 10.00
        })

        response = await ac.get("/api/v1/products/categories")
        assert response.status_code == 200
        categories = response.json()
        assert "TestCategoryList" in categories


async def test_keyset_pagination_ordering_and_traversal(db_session):
    """Test cursor-based keyset pagination with multiple items."""
    base_time = datetime.now(timezone.utc)
    
    # Seed 5 items with distinct creation dates (descending order is newest-first)
    for i in range(5):
        p = Product(
            id=uuid.uuid4(),
            name=f"Paginated Item {i}",
            category="TestPagination",
            price=10.00 + i,
            created_at=base_time - timedelta(hours=(4 - i)),
            updated_at=base_time - timedelta(hours=(4 - i))
        )
        db_session.add(p)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Query with limit=2 (expecting first page to return Item 4 and Item 3)
        response = await ac.get("/api/v1/products?category=TestPagination&limit=2")
        assert response.status_code == 200
        page1 = response.json()
        
        # Verify page 1 items (newest first: Item 4 then Item 3)
        assert len(page1["data"]) == 2
        assert page1["data"][0]["name"] == "Paginated Item 4"
        assert page1["data"][1]["name"] == "Paginated Item 3"
        assert page1["pagination"]["has_next"] is True
        assert page1["pagination"]["next_cursor"] is not None

        # Fetch page 2 (expecting Item 2 and Item 1) using next_cursor
        cursor = page1["pagination"]["next_cursor"]
        response2 = await ac.get(f"/api/v1/products?category=TestPagination&limit=2&cursor={cursor}")
        assert response2.status_code == 200
        page2 = response2.json()

        assert len(page2["data"]) == 2
        assert page2["data"][0]["name"] == "Paginated Item 2"
        assert page2["data"][1]["name"] == "Paginated Item 1"
        assert page2["pagination"]["has_next"] is True
        assert page2["pagination"]["next_cursor"] is not None

        # Fetch page 3 (expecting Item 0) using next_cursor from page 2
        cursor2 = page2["pagination"]["next_cursor"]
        response3 = await ac.get(f"/api/v1/products?category=TestPagination&limit=2&cursor={cursor2}")
        assert response3.status_code == 200
        page3 = response3.json()

        assert len(page3["data"]) == 1
        assert page3["data"][0]["name"] == "Paginated Item 0"
        assert page3["pagination"]["has_next"] is False
        assert page3["pagination"]["next_cursor"] is None
