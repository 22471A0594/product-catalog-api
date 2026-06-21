# Product Catalog API

A high-performance product catalog API built with **FastAPI**, **PostgreSQL**, and **SQLAlchemy**, featuring **cursor-based keyset pagination** that guarantees consistent results under concurrent writes.

## Architecture Overview

```
Client Request
    │
    ▼
┌──────────────┐
│   FastAPI     │  ← Async request handling
│   Uvicorn     │  ← ASGI server
├──────────────┤
│   Pydantic    │  ← Request/response validation
├──────────────┤
│  SQLAlchemy   │  ← Async ORM with connection pooling
│   asyncpg     │  ← Native PostgreSQL async driver
├──────────────┤
│  PostgreSQL   │  ← Neon (serverless) or self-hosted
└──────────────┘
```

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 14+ (or Docker)
- pip

### Local Development

```bash
# Clone and enter
git clone <repo-url> && cd product-catalog-api

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL

# Start the API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Seed 200,000 products (in another terminal)
python seed.py

# Force re-seed (truncates existing data)
python seed.py --force
```

### Docker Development

```bash
# Start PostgreSQL and API
docker-compose up -d

# Seed the database
docker-compose --profile seed up seed

# View logs
docker-compose logs -f api
```

## API Reference

### Health Check
```
GET /
GET /health
```

### List Products (Paginated)
```
GET /api/v1/products?limit=20&category=Electronics&cursor=<opaque_cursor>
```

**Query Parameters:**
| Parameter  | Type   | Default | Description                                    |
|------------|--------|---------|------------------------------------------------|
| `limit`    | int    | 20      | Items per page (1-100)                         |
| `category` | string | null    | Filter by exact category match                 |
| `cursor`   | string | null    | Opaque cursor from previous response           |

**Response:**
```json
{
  "data": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "name": "Premium Widget X1",
      "category": "Electronics",
      "price": 29.99,
      "created_at": "2025-06-20T14:30:00Z",
      "updated_at": "2025-06-20T14:30:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "eyJjcmVhdGVkX2F0IjoiMjAyNS...",
    "has_next": true,
    "page_size": 20
  }
}
```

### List Categories
```
GET /api/v1/products/categories
```

### Get Product
```
GET /api/v1/products/{product_id}
```

### Create Product
```
POST /api/v1/products
Content-Type: application/json

{
  "name": "Premium Widget X1",
  "category": "Electronics",
  "price": 29.99
}
```

### Update Product
```
PATCH /api/v1/products/{product_id}
Content-Type: application/json

{
  "price": 39.99
}
```

### Delete Product
```
DELETE /api/v1/products/{product_id}
```

## Pagination Deep Dive

### Why Cursor-Based (Keyset) Pagination?

| Aspect | OFFSET | Cursor (Keyset) |
|--------|--------|------------------|
| Performance at depth | O(n) — scans skipped rows | O(1) — index seek |
| Consistency under inserts | ❌ Duplicates/gaps | ✅ Stable window |
| Consistency under deletes | ❌ Missed items | ✅ Stable window |
| Bookmark-ability | ✅ Simple page numbers | ❌ Opaque cursors |
| Random page access | ✅ Easy | ❌ Sequential only |
| Implementation complexity | Low | Medium |

### How It Works

1. **First request** — no cursor, returns the newest `limit` products.
2. **Cursor encoding** — the `(created_at, id)` of the **last item** on the page is Base64-encoded into an opaque string.
3. **Subsequent requests** — the cursor is decoded, and the query uses `WHERE (created_at, id) < (cursor_ts, cursor_id)` to seek directly to the next page.
4. **Composite key** — `(created_at DESC, id DESC)` ensures deterministic ordering even when multiple products share the same `created_at`.

### Consistency Guarantee

If a new product is inserted while a user is paginating:
- The new product has a **newer** `created_at`, so it appears **before** the cursor position.
- The user's cursor points to a fixed `(created_at, id)` pair that is unaffected.
- **Result**: No duplicates, no missed items.

## Deployment

### Render + Neon PostgreSQL

#### 1. Set Up Neon Database
1. Create an account at [neon.tech](https://neon.tech)
2. Create a new project and database
3. Copy the connection string (use the pooled endpoint for production)
4. Convert to asyncpg format:
   ```
   # Neon gives you:
   postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require
   
   # Convert to:
   postgresql+asyncpg://user:pass@ep-xxx.region.aws.neon.tech/dbname?ssl=require
   ```

#### 2. Deploy to Render
1. Create a new **Web Service** on [render.com](https://render.com)
2. Connect your GitHub repository
3. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --workers 4 --bind 0.0.0.0:$PORT`
   - **Environment Variables**:
     - `DATABASE_URL` = your Neon connection string
     - `DEBUG` = `false`
4. Deploy!

#### 3. Seed Production Database
```bash
# From your local machine with DATABASE_URL pointing to Neon
DATABASE_URL="postgresql+asyncpg://..." python seed.py
```

## Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan, middleware
│   ├── config.py             # Pydantic settings from env vars
│   ├── database.py           # Async engine, session factory
│   ├── models/
│   │   ├── __init__.py
│   │   └── product.py        # SQLAlchemy Product model + indexes
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── product.py        # Pydantic request/response schemas
│   ├── api/
│   │   ├── __init__.py
│   │   └── products.py       # API routes (CRUD + pagination)
│   └── pagination/
│       ├── __init__.py
│       └── cursor.py         # Cursor encode/decode logic
├── seed.py                   # Bulk seeding script (200k products)
├── requirements.txt
├── Dockerfile                # Multi-stage production build
├── docker-compose.yml        # Local dev with PostgreSQL
├── .env.example
├── .dockerignore
├── .gitignore
├── ARCHITECTURE.md           # Detailed architectural decisions
└── README.md
```

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | FastAPI | Async-native, auto-docs, type-safe |
| ORM | SQLAlchemy 2.0 | Async support, mature, production-proven |
| DB Driver | asyncpg | Fastest Python PostgreSQL driver |
| Database | PostgreSQL 16 | ACID, composite indexes, row-value comparisons |
| Validation | Pydantic v2 | Rust-powered, 5-17x faster than v1 |
| Server | Gunicorn + Uvicorn | Process management + async ASGI |
| Cloud DB | Neon | Serverless Postgres, autoscaling, branching |
| Hosting | Render | Git-push deploys, auto-TLS, health checks |

## Deployment Status
Application deployed successfully on Railway.
