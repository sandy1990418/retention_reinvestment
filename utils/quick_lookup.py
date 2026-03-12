"""Direct stock lookup — bypasses LLM agent for simple queries.

Reads cached cheap/expensive prices from Supabase (populated by GitHub Actions),
fetches real-time prices from TWSE API, then compares programmatically.
No Playwright needed on the server side.
"""

import asyncio
import importlib.util
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


MAX_STOCK_IDS_PER_REQUEST = _env_int("QUICK_MAX_STOCK_IDS", 6, 1)
MEMORY_CACHE_TTL = _env_int("QUICK_MEMORY_CACHE_TTL", 600, 60)  # 10 min

# In-memory L1 cache: {stock_id: (expires_at, data_dict)}
_mem_cache: dict[str, tuple[float, dict]] = {}


def _import_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# get_price is lightweight (HTTP only), safe to run in-process
_price_mod = _import_module(
    "get_price", str(SKILLS_DIR / "get-stock-price" / "scripts" / "get_price.py")
)


def _normalize_stock_ids(stock_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for sid in stock_ids:
        s = sid.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        normalized.append(s)
        if len(normalized) >= MAX_STOCK_IDS_PER_REQUEST:
            break
    return normalized


def _get_from_mem_cache(stock_ids: list[str]) -> tuple[dict[str, dict], list[str]]:
    """Check memory cache. Returns (cached_results, uncached_ids)."""
    now = time.time()
    cached = {}
    uncached = []
    for sid in stock_ids:
        entry = _mem_cache.get(sid)
        if entry and entry[0] > now:
            cached[sid] = entry[1]
        else:
            uncached.append(sid)
    return cached, uncached


def _update_mem_cache(results: dict[str, dict]):
    expires = time.time() + MEMORY_CACHE_TTL
    for sid, data in results.items():
        if data.get("status") != "error":
            _mem_cache[sid] = (expires, data)


def _fetch_from_supabase(stock_ids: list[str]) -> dict[str, dict]:
    """Fetch cached stock data from Supabase stock_cache table."""
    from utils.stock_cache import get_cached_stocks
    return get_cached_stocks(stock_ids)


async def _get_search_results(stock_ids: list[str]) -> dict[str, dict]:
    """Get search results from memory cache → Supabase cache."""
    cached, uncached = _get_from_mem_cache(stock_ids)

    if uncached:
        loop = asyncio.get_running_loop()
        db_results = await loop.run_in_executor(None, _fetch_from_supabase, uncached)
        _update_mem_cache(db_results)
        cached.update(db_results)

    return cached


async def quick_analyze(stock_ids: list[str]) -> str:
    """Analyze stocks directly without LLM. Returns formatted text."""
    normalized_stock_ids = _normalize_stock_ids(stock_ids)
    if not normalized_stock_ids:
        return "請輸入有效股票代號（例如 2330）"

    # Run Supabase cache read and TWSE price lookup in parallel
    search_task = _get_search_results(normalized_stock_ids)

    loop = asyncio.get_running_loop()
    price_task = loop.run_in_executor(None, _price_mod.get_price, normalized_stock_ids)

    search_data = await search_task
    try:
        price_data = await price_task
    except Exception:
        price_data = []

    # Build price lookup
    prices = {}
    if isinstance(price_data, list):
        for p in price_data:
            prices[p["stock_id"]] = p

    # Check if any stock has cached cheap/expensive prices
    has_cache = any(
        search_data.get(sid) and (search_data[sid].get("cheap_price") or search_data[sid].get("expensive_price"))
        for sid in normalized_stock_ids
    )
    if not has_cache:
        logger.info("quick_analyze: no cache data for %s, fallback to agent", normalized_stock_ids)
        return None

    # Format output
    lines = []
    if len(normalized_stock_ids) < len(stock_ids):
        lines.append(
            f"⚠️ 免費版效能模式：一次最多查詢 {MAX_STOCK_IDS_PER_REQUEST} 檔，已優先處理前 {len(normalized_stock_ids)} 檔。"
        )
        lines.append("")

    for sid in normalized_stock_ids:
        search_result = search_data.get(sid)
        if search_result is None:
            search_error = "此股票尚未收錄，請先追蹤後等待下次更新。"
        elif search_result.get("status") == "error":
            search_error = search_result.get("message", "查詢失敗")
        else:
            search_error = ""

        name = search_result.get("name", "") if search_result else ""
        cheap = _parse_float(search_result.get("cheap_price", "")) if search_result else None
        expensive = _parse_float(search_result.get("expensive_price", "")) if search_result else None

        price_info = prices.get(sid, {})
        current = _parse_float(price_info.get("price", ""))
        stock_name = price_info.get("name", name)

        if search_error:
            if current is not None:
                lines.append(f"⚠️ {sid} {stock_name or sid}")
                lines.append(f"  現價:{current}")
                lines.append("  建議：無法判斷")
                lines.append(f"  {search_error}")
                lines.append("")
            else:
                lines.append(f"❌ {sid}: {search_error}")
                lines.append("")
            continue

        # Determine recommendation
        if current is not None and expensive is not None and current >= expensive:
            rec, emoji = "賣出", "🔴"
            reasoning = f"現價 {current} ≥ 貴價 {expensive}"
        elif current is not None and cheap is not None and current <= cheap:
            rec, emoji = "買入", "🟢"
            reasoning = f"現價 {current} ≤ 淑價 {cheap}"
        elif current is not None and cheap is not None and expensive is not None:
            rec, emoji = "持有", "⚪"
            reasoning = f"淑價 {cheap} < 現價 {current} < 貴價 {expensive}"
        else:
            rec, emoji = "無法判斷", "❓"
            if current is not None:
                reasoning = "已取得現價，但缺少盈再表貴價/淑價。"
            else:
                reasoning = "無法取得即時價格"

        lines.append(f"{emoji} {sid} {stock_name}")
        price_str = f"  現價:{current}" if current is not None else "  現價:N/A"
        cheap_str = f" 淑價:{cheap}" if cheap is not None else ""
        exp_str = f" 貴價:{expensive}" if expensive is not None else ""
        lines.append(f"{price_str}{cheap_str}{exp_str}")
        lines.append(f"  建議：{rec}")
        lines.append(f"  {reasoning}")
        lines.append("")

    return "\n".join(lines).strip() if lines else "查無資料"


def _parse_float(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, AttributeError):
        return None
