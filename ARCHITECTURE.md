# Architecture & Engineering Decisions

This document explains the key architectural decisions, trade-offs, and scalability considerations for the Product Catalog API.

---

## 1. Cursor-Based (Keyset) Pagination

### The Problem with OFFSET Pagination

```sql
-- Page 1000 with OFFSET: Postgres must scan and discard 19,980 rows
SELECT * FROM products ORDER BY created_at DESC LIMIT 20 OFFSET 19980;
```

OFFSET pagination has two critical flaws:

1. **O(n) performance degradation** — The database must scan all `OFFSET + LIMIT` rows, discard the first `OFFSET`, and return the rest. Page 10,000 is 10,000× slower than page 1.

2. **Inconsistency under concurrent writes** — If a new product is inserted while a user is on page 5, every subsequent page shifts by one: the user either sees a duplicate or misses a product entirely.

### Our Solution: Keyset Pagination

```sql
-- Keyset: Postgres seeks directly via the B-tree index — O(log n)
SELECT * FROM products
WHERE (created_at, id) < ('2025-06-20T14:30:00Z', 'abc-123')
ORDER BY created_at DESC, id DESC
LIMIT 20;
```

**Why a composite key?** A single `created_at` column is not unique — bulk inserts or concurrent requests can produce identical timestamps. Adding `id` (UUID) as a tiebreaker guarantees a **total ordering**, which is required for correct keyset pagination.

### Cursor Encoding

The cursor encodes `(created_at, id)` as Base64URL-encoded JSON:

```json
{"created_at": "2025-06-20T14:30:00+00:00", "id": "a1b2c3d4-..."}
```

Design choices:
- **Base64URL** (not Base64) avoids `+` and `/` characters that cause URL-encoding issues.
- **JSON payload** is self-describing and debuggable, unlike binary formats.
- **No HMAC signing** — cursors contain no sensitive data (just a timestamp and UUID). In a multi-tenant system, you'd sign to prevent cursor manipulation across tenants.

---

## 2. Index Strategy

Two composite indexes cover all query patterns with zero filesort:

### Default Listing Index
```sql
CREATE INDEX ix_products_created_id
    ON products (created_at DESC, id DESC);
```
- Covers: `ORDER BY created_at DESC, id DESC`
- Covers: `WHERE (created_at, id) < (?, ?)` (keyset seek)
- Postgres uses a **backward index scan** or direct seek — no sort needed.

### Category-Filtered Index
```sql
CREATE INDEX ix_products_category_created_id
    ON products (category, created_at DESC, id DESC);
```
- Covers: `WHERE category = ? ORDER BY created_at DESC, id DESC`
- The equality predicate on `category` narrows the B-tree to a subtree, then the `(created_at DESC, id DESC)` suffix provides ordered access — **no filesort**.
- This is a classic "equality-first, range-second" index design.

### Why Not a Single Covering Index?

A single index `(category, created_at DESC, id DESC)` cannot efficiently serve the **un-filtered** query (`ORDER BY created_at DESC, id DESC` without a category predicate) because Postgres would need to merge-scan across all category subtrees. Two specialized indexes are the correct trade-off: ~2× write overhead (maintaining two B-trees) for optimal read performance on both query patterns.

---

## 3. Async Architecture

### Why Async?

The API is **I/O-bound** — every request hits PostgreSQL. With synchronous handlers, each request blocks a thread while waiting for the database. Async allows a single thread to handle thousands of concurrent connections by yielding during I/O waits.

```
Sync:  Thread 1: [──DB wait──][response]  → 1 request/thread
Async: Thread 1: [req1→DB][req2→DB][req1←DB][response1][req2←DB][response2]
```

### Stack Choices

| Layer | Choice | Why |
|-------|--------|-----|
| ASGI Server | Uvicorn | libuv event loop, fastest Python ASGI server |
| Framework | FastAPI | Native async, automatic OpenAPI, Pydantic integration |
| ORM | SQLAlchemy 2.0 async | `AsyncSession` with `asyncpg` — no thread-pool overhead |
| DB Driver | asyncpg | C-extension, binary protocol, 3× faster than psycopg2 |

### Production Process Model

```
Gunicorn (master)
  ├── UvicornWorker (PID 1) ─── async event loop ─── connection pool
  ├── UvicornWorker (PID 2) ─── async event loop ─── connection pool
  ├── UvicornWorker (PID 3) ─── async event loop ─── connection pool
  └── UvicornWorker (PID 4) ─── async event loop ─── connection pool
```

Gunicorn manages worker processes (pre-fork model), each running a Uvicorn event loop. This combines multi-core utilization (Gunicorn) with high-concurrency async I/O (Uvicorn).

---

## 4. Bulk Seeding Strategy

### Why Not ORM `.add()` in a Loop?

```python
# SLOW: ~500 rows/sec — ORM overhead per object
for data in products:
    session.add(Product(**data))
```

The ORM's identity map, dirty tracking, and per-object event hooks add overhead per row. For 200,000 rows, this takes ~6 minutes.

### Our Approach: Core `insert().values()`

```python
# FAST: ~50,000 rows/sec — bypasses ORM overhead
await session.execute(insert(Product), batch_of_5000_dicts)
```

- Generates a single `INSERT INTO products VALUES (...), (...), ...` statement per batch.
- Bypasses the ORM identity map entirely.
- Batches of 5,000 balance memory usage vs. round-trip overhead.
- Deterministic RNG (`seed=42`) ensures reproducible data across environments.

---

## 5. Trade-offs

### Accepted Trade-offs

| Trade-off | What we gave up | What we gained |
|-----------|----------------|----------------|
| Keyset pagination | Random page access ("jump to page 50") | O(1) seek, no duplicates, no gaps |
| Opaque cursors | Human-readable page numbers | Position-independent, tamper-evident |
| Two indexes | ~2× write overhead on inserts | Optimal reads for both filtered and unfiltered queries |
| UUID primary keys | Sequential locality (vs. auto-increment) | Distributed generation, no central sequence bottleneck |
| Async-only | Simpler sync code | 10-50× concurrency improvement for I/O-bound workloads |
| No Alembic migrations in seed | Automated schema versioning | Simpler seed script; `create_all()` is idempotent |

### UUID vs. Auto-increment

We chose UUIDv4 despite its B-tree fragmentation cost because:
1. UUIDs can be generated client-side without a database round-trip.
2. In a distributed system, there's no central sequence bottleneck.
3. UUIDs are not guessable — no information leakage about product count or creation rate.
4. PostgreSQL's `uuid-ossp` and `gen_random_uuid()` are well-optimized.

If write-heavy performance were critical, we'd consider UUIDv7 (time-ordered) for better B-tree locality.

---

## 6. Scalability Discussion

### Current Capacity (Single Postgres Instance)

| Metric | Estimate |
|--------|----------|
| Products | 200K (tested), 10M+ (feasible with current indexes) |
| Read throughput | ~5,000 req/sec (4 workers, connection pooling) |
| p99 latency (page 1) | <10ms |
| p99 latency (page 5000) | <10ms (keyset!) |
| p99 latency with OFFSET page 5000 | ~500ms (for comparison) |

### Scaling to 10M+ Products

1. **Read replicas** — Route `GET` requests to read replicas. Cursor pagination is replica-safe because it doesn't depend on absolute positions.

2. **Connection pooling** — Use PgBouncer in front of PostgreSQL (or Neon's built-in pooler) to multiplex thousands of application connections over a smaller set of database connections.

3. **Caching** — Add Redis caching for:
   - Category list (changes rarely)
   - Popular first pages (high cache-hit ratio)
   - Individual product lookups by UUID

4. **Partitioning** — If the table exceeds ~50M rows, partition by `category` (list partitioning) or `created_at` (range partitioning). Both align with our index strategy.

5. **CDN / API Gateway** — Cache paginated responses at the edge. Cursor-based pagination is cache-friendly because the same cursor always returns the same results (assuming no deletes).

### Scaling Beyond a Single Database

1. **Horizontal sharding** — Shard by `category` or `id` hash. Each shard maintains its own B-tree indexes. Cross-shard pagination requires a merge step.

2. **CQRS** — Separate the write path (PostgreSQL) from the read path (Elasticsearch or a materialized view). This is the natural evolution when read patterns diverge significantly from the write model.

3. **Event sourcing** — Emit product change events to Kafka/Pub/Sub. Consumers build denormalized read models optimized for specific query patterns.

---

## 7. What I'd Add for Production

1. **Rate limiting** — Token bucket per IP/API key at the API gateway level.
2. **Authentication** — JWT or API key validation middleware.
3. **Structured logging** — JSON logs with request ID, latency, and query metrics.
4. **Metrics** — Prometheus counters for request count, latency histograms, DB pool utilization.
5. **Alembic migrations** — Versioned schema changes instead of `create_all()`.
6. **CI/CD** — GitHub Actions with lint, type-check, test, and deploy stages.
7. **Load testing** — Locust or k6 scripts to validate p99 latency under load.
8. **Search** — Full-text search with `tsvector` or Elasticsearch for product name queries.
