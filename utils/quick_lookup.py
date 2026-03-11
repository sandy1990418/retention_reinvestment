"""Direct stock lookup — bypasses LLM agent for simple queries.

Runs search-stock and get-stock-price in parallel, then compares
prices programmatically. Much faster than going through the agent.
"""

import asyncio
import importlib.util
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def _import_module(name: str, path: str):
    """Import a module from a file path (works with hyphenated directories)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Import skill modules directly (no subprocess needed)
_search_mod = _import_module(
    "search", str(SKILLS_DIR / "search-stock" / "scripts" / "search.py")
)
_price_mod = _import_module(
    "get_price", str(SKILLS_DIR / "get-stock-price" / "scripts" / "get_price.py")
)


async def quick_analyze(stock_ids: list[str]) -> str:
    """Analyze stocks directly without LLM. Returns formatted text."""

    # Run all search + price lookups in parallel
    search_tasks = [_search_mod.search(sid) for sid in stock_ids]

    # get_price is sync, run in thread pool
    loop = asyncio.get_event_loop()
    price_task = loop.run_in_executor(None, _price_mod.get_price, stock_ids)

    # Wait for everything concurrently
    search_results = await asyncio.gather(*search_tasks, return_exceptions=True)
    price_data = await price_task

    # Build price lookup
    prices = {}
    if isinstance(price_data, list):
        for p in price_data:
            prices[p["stock_id"]] = p

    # Format output
    lines = []
    for sid, search_result in zip(stock_ids, search_results):
        # Handle exceptions from search
        if isinstance(search_result, Exception):
            lines.append(f"❌ {sid}: {str(search_result)}")
            lines.append("")
            continue

        if isinstance(search_result, dict) and search_result.get("status") == "error":
            lines.append(f"❌ {sid}: {search_result.get('message', '查詢失敗')}")
            lines.append("")
            continue

        name = search_result.get("name", "")
        cheap = _parse_float(search_result.get("cheap_price", ""))
        expensive = _parse_float(search_result.get("expensive_price", ""))

        price_info = prices.get(sid, {})
        current = _parse_float(price_info.get("price", ""))
        stock_name = price_info.get("name", name)

        # Determine recommendation
        if current is not None and expensive is not None and current >= expensive:
            rec, emoji = "賣出", "🔴"
            reasoning = f"現價 {current} ≥ 貴價 {expensive}"
        elif current is not None and cheap is not None and current <= cheap:
            rec, emoji = "買入", "🟢"
            reasoning = f"現價 {current} ≤ 淑價 {cheap}"
        elif current is not None:
            rec, emoji = "持有", "⚪"
            reasoning = f"淑價 {cheap} < 現價 {current} < 貴價 {expensive}"
        else:
            rec, emoji = "無法判斷", "❓"
            reasoning = "無法取得即時價格"

        lines.append(f"{emoji} {sid} {stock_name}")
        price_str = f"  現價:{current}" if current else "  現價:N/A"
        cheap_str = f" 淑價:{cheap}" if cheap else ""
        exp_str = f" 貴價:{expensive}" if expensive else ""
        lines.append(f"{price_str}{cheap_str}{exp_str}")
        lines.append(f"  建議：{rec}")
        lines.append(f"  {reasoning}")
        lines.append("")

    return "\n".join(lines).strip() if lines else "查無資料"


def _parse_float(val: str | None) -> float | None:
    """Parse a string to float, return None on failure."""
    if not val:
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, AttributeError):
        return None
