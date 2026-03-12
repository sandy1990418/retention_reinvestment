#!/usr/bin/env python3
"""Scrape stock data from retention & reinvestment table and store in Supabase.

This script is designed to run in GitHub Actions where stocks.ddns.net is reachable.
It collects all stock IDs from user watchlists, scrapes their cheap/expensive prices,
and upserts the results into the stock_cache table.

Usage:
  python scripts/scrape_to_supabase.py
  python scripts/scrape_to_supabase.py --stock-id 2330 --stock-id 2317
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from utils.watchlist import get_all_users_with_stocks
from utils.stock_cache import upsert_stocks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def collect_stock_ids() -> list[str]:
    """Get all unique stock IDs from user watchlists."""
    users = get_all_users_with_stocks()
    all_ids = set()
    for stock_ids in users.values():
        all_ids.update(stock_ids)
    return sorted(all_ids)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-id", action="append", help="額外指定股票代號")
    args = parser.parse_args()

    # Collect stock IDs from watchlists
    stock_ids = collect_stock_ids()
    logger.info("Watchlist stocks: %s", stock_ids)

    # Add any extra stock IDs from CLI args
    if args.stock_id:
        extra = set(args.stock_id) - set(stock_ids)
        if extra:
            stock_ids.extend(sorted(extra))
            logger.info("Extra stocks from CLI: %s", sorted(extra))

    if not stock_ids:
        logger.info("No stocks to scrape.")
        return

    logger.info("Scraping %d stocks: %s", len(stock_ids), stock_ids)

    # Import search_batch (requires Playwright)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "search",
        str(Path(__file__).resolve().parents[1] / "skills" / "search-stock" / "scripts" / "search.py"),
    )
    search_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(search_mod)

    results = await search_mod.search_batch(stock_ids)

    # Log results
    success = []
    errors = []
    for sid, result in zip(stock_ids, results):
        if isinstance(result, dict) and result.get("status") == "error":
            errors.append(f"{sid}: {result.get('message', '?')}")
        else:
            success.append(sid)

    if success:
        logger.info("Scrape succeeded for %d stocks: %s", len(success), success)
    if errors:
        logger.warning("Scrape failed for %d stocks:\n  %s", len(errors), "\n  ".join(errors))

    # Upsert successful results to Supabase
    upsert_stocks(results)
    logger.info("Done. %d/%d stocks updated in cache.", len(success), len(stock_ids))


if __name__ == "__main__":
    asyncio.run(main())
