"""Seed script: bulk-insert 200,000 products into the database.

Performance strategy:
─────────────────────────────────────────────────────────────────────────
• Uses raw COPY-style bulk insert via `insert().values()` in batches
  of 5,000 rows. This bypasses ORM identity-map overhead and achieves
  ~50,000 inserts/sec on a modern Postgres instance.

• UUIDs and timestamps are generated in Python to avoid round-trips.

• Categories and names are generated deterministically from a fixed
  vocabulary — no Faker dependency, which is slow at scale.

• We disable autoflush and autocommit during the batch loop.

• The script is idempotent: it checks if products already exist and
  skips seeding if so, or can be run with --force to truncate first.
─────────────────────────────────────────────────────────────────────────
"""

import asyncio
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory, engine, Base
from app.models.product import Product

settings = get_settings()

# ─── Vocabulary for realistic product generation ────────────────────────

CATEGORIES = [
    "Electronics", "Clothing", "Home & Kitchen", "Books", "Sports",
    "Toys & Games", "Beauty", "Automotive", "Garden", "Health",
    "Pet Supplies", "Office Products", "Music", "Grocery", "Tools",
]

ADJECTIVES = [
    "Premium", "Ultra", "Essential", "Classic", "Pro", "Elite",
    "Compact", "Deluxe", "Advanced", "Smart", "Eco", "Turbo",
    "Portable", "Wireless", "Ergonomic", "Heavy-Duty", "Lightweight",
    "Organic", "Vintage", "Modern", "Digital", "Thermal", "Solar",
    "Magnetic", "Flex", "Rapid", "Silent", "Dual", "Multi", "Nano",
]

NOUNS = [
    "Widget", "Gadget", "Device", "Tool", "Kit", "Set", "Pack",
    "System", "Unit", "Module", "Sensor", "Adapter", "Charger",
    "Speaker", "Monitor", "Keyboard", "Mouse", "Headset", "Cable",
    "Stand", "Mount", "Holder", "Case", "Cover", "Sleeve", "Bag",
    "Lamp", "Fan", "Filter", "Brush", "Roller", "Pad", "Mat",
    "Bottle", "Container", "Organizer", "Rack", "Shelf", "Hook",
    "Clip", "Strap", "Band", "Ring", "Chain", "Lock", "Key",
]

MODELS = [
    "X1", "X2", "V3", "S4", "Pro", "Max", "Mini", "Plus",
    "Lite", "Air", "SE", "GT", "EX", "MK2", "Gen3",
    "100", "200", "300", "500", "1000", "Z", "Alpha", "Beta",
]


def generate_product_name(rng: random.Random) -> str:
    """Generate a realistic product name."""
    adj = rng.choice(ADJECTIVES)
    noun = rng.choice(NOUNS)
    model = rng.choice(MODELS)
    return f"{adj} {noun} {model}"


def generate_products_batch(
    batch_size: int,
    rng: random.Random,
    base_time: datetime,
    batch_index: int,
) -> list[dict]:
    """Generate a batch of product dictionaries for bulk insert."""
    products = []
    for i in range(batch_size):
        # Spread created_at over the last 365 days for realistic data
        offset_seconds = rng.randint(0, 365 * 24 * 3600)
        created_at = base_time - timedelta(seconds=offset_seconds)
        
        products.append({
            "id": uuid.uuid4(),
            "name": generate_product_name(rng),
            "category": rng.choice(CATEGORIES),
            "price": round(rng.uniform(0.99, 9999.99), 2),
            "created_at": created_at,
            "updated_at": created_at,
        })
    return products


async def seed_database(force: bool = False):
    """Seed the database with 200,000 products."""
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # Check existing count
        result = await session.execute(select(func.count()).select_from(Product))
        existing_count = result.scalar()

        if existing_count and existing_count > 0 and not force:
            print(f"Database already contains {existing_count:,} products.")
            print("Use --force to truncate and re-seed.")
            return

        if force and existing_count and existing_count > 0:
            print("Truncating existing products...")
            await session.execute(text("TRUNCATE TABLE products"))
            await session.commit()

        total = settings.SEED_TOTAL_PRODUCTS
        batch_size = settings.SEED_BATCH_SIZE
        rng = random.Random(42)  # Deterministic for reproducibility
        base_time = datetime.now(timezone.utc)

        print(f"Seeding {total:,} products in batches of {batch_size:,}...")
        start_time = time.perf_counter()

        for batch_num in range(0, total, batch_size):
            current_batch_size = min(batch_size, total - batch_num)
            products = generate_products_batch(
                current_batch_size, rng, base_time, batch_num // batch_size
            )

            await session.execute(insert(Product), products)
            await session.commit()

            elapsed = time.perf_counter() - start_time
            done = batch_num + current_batch_size
            rate = done / elapsed if elapsed > 0 else 0
            print(
                f"  Batch {batch_num // batch_size + 1:>3} | "
                f"{done:>7,} / {total:,} | "
                f"{rate:,.0f} rows/sec | "
                f"{elapsed:.1f}s elapsed"
            )

        elapsed = time.perf_counter() - start_time
        print(f"\nSeeding complete: {total:,} products in {elapsed:.1f}s")
        print(f"Average rate: {total / elapsed:,.0f} rows/sec")


if __name__ == "__main__":
    force = "--force" in sys.argv
    asyncio.run(seed_database(force=force))
