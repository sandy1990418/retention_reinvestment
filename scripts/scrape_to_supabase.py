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
import os
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

    # Check for cookies expiration and notify via LINE
    cookies_expired = any("Cookies 已過期" in e or "所有網址均無法連線" in e for e in errors)
    if cookies_expired:
        logger.warning("Cookies may be expired! Sending LINE notification.")
        _notify_cookies_expired()


def _notify_cookies_expired():
    """Send LINE push notification when cookies expire."""
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        logger.warning("No LINE_CHANNEL_ACCESS_TOKEN, cannot send notification.")
        return

    # Notify all users who have tracked stocks
    users = get_all_users_with_stocks()
    if not users:
        return

    import httpx
    msg = (
        "⚠️ 盈再表 cookies 已過期，stock cache 無法更新。\n"
        "請在本地執行：\n"
        "1. uv run python scripts/login_save_cookies.py\n"
        "2. uv run python scripts/refresh_secret.py"
    )
    for user_id in users:
        try:
            httpx.post(
                "https://api.line.me/v2/bot/message/push",
                headers={"Authorization": f"Bearer {token}"},
                json={"to": user_id, "messages": [{"type": "text", "text": msg}]},
            )
            logger.info("Notified user %s about cookie expiry", user_id)
        except Exception as e:
            logger.error("Failed to notify user %s: %s", user_id, e)


if __name__ == "__main__":
    asyncio.run(main())
