"""Stock cache persistence via Supabase.

Stores cheap/expensive prices scraped from the retention & reinvestment table.
Data is written by GitHub Actions and read by the Render app.
"""

import logging
from datetime import datetime, timezone

from utils.watchlist import get_client

logger = logging.getLogger(__name__)


def get_cached_stocks(stock_ids: list[str]) -> dict[str, dict]:
    """Fetch cached stock data for given IDs. Returns {stock_id: row_dict}."""
    if not stock_ids:
        return {}
    client = get_client()
    try:
        result = (
            client.table("stock_cache")
            .select("*")
            .in_("stock_id", stock_ids)
            .execute()
        )
        return {row["stock_id"]: row for row in result.data}
    except Exception as e:
        logger.error("get_cached_stocks failed: %s", e)
        return {}


def upsert_stock(data: dict):
    """Upsert a single stock's cached data."""
    client = get_client()
    row = {
        "stock_id": data["stock_id"],
        "name": data.get("name", ""),
        "exchange": data.get("exchange", ""),
        "expected_return": data.get("expected_return", ""),
        "cheap_price": data.get("cheap_price", ""),
        "expensive_price": data.get("expensive_price", ""),
        "nav": data.get("nav", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        client.table("stock_cache").upsert(row).execute()
    except Exception as e:
        logger.error("upsert_stock failed for %s: %s", data.get("stock_id"), e)
        raise


def upsert_stocks(data_list: list[dict]):
    """Upsert multiple stocks' cached data."""
    if not data_list:
        return
    client = get_client()
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for data in data_list:
        if data.get("status") == "error":
            continue
        if not data.get("cheap_price") and not data.get("expensive_price"):
            continue
        rows.append({
            "stock_id": data["stock_id"],
            "name": data.get("name", ""),
            "exchange": data.get("exchange", ""),
            "expected_return": data.get("expected_return", ""),
            "cheap_price": data.get("cheap_price", ""),
            "expensive_price": data.get("expensive_price", ""),
            "nav": data.get("nav", ""),
            "updated_at": now,
        })
    if not rows:
        return
    try:
        client.table("stock_cache").upsert(rows).execute()
        logger.info("upserted %d stocks to cache", len(rows))
    except Exception as e:
        logger.error("upsert_stocks failed: %s", e)
        raise
