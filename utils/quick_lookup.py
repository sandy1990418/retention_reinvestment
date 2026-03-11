"""Direct stock lookup — bypasses LLM agent for simple queries.

Runs search-stock and get-stock-price in parallel, then compares
prices programmatically. Much faster than going through the agent.
"""

import asyncio
import importlib.util
import os
import time
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


SEARCH_CACHE_TTL_SECONDS = _env_int("SEARCH_CACHE_TTL_SECONDS", 21600, 60)
SEARCH_CONCURRENCY = _env_int("QUICK_SEARCH_CONCURRENCY", 1, 1)
SEARCH_TIMEOUT_SECONDS = _env_int("QUICK_SEARCH_TIMEOUT_SECONDS", 55, 10)
MAX_STOCK_IDS_PER_REQUEST = _env_int("QUICK_MAX_STOCK_IDS", 6, 1)

# In-memory cache: {stock_id: (expires_at_epoch, search_result_dict)}
_search_cache: dict[str, tuple[float, dict]] = {}


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


def _normalize_stock_ids(stock_ids: list[str]) -> list[str]:
    """Dedupe and cap stock IDs to protect free-tier resources."""
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


def _get_cached_search(stock_id: str) -> dict | None:
    cached = _search_cache.get(stock_id)
    if not cached:
        return None
    expires_at, data = cached
    if time.time() >= expires_at:
        _search_cache.pop(stock_id, None)
        return None
    return dict(data)


def _set_cached_search(stock_id: str, result: dict):
    # Cache successful results only.
    if result.get("status") == "error":
        return
    if not result.get("cheap_price") and not result.get("expensive_price"):
        return
    _search_cache[stock_id] = (time.time() + SEARCH_CACHE_TTL_SECONDS, dict(result))


async def _run_search(stock_id: str, semaphore: asyncio.Semaphore) -> dict:
    cached = _get_cached_search(stock_id)
    if cached is not None:
        return cached

    async with semaphore:
        try:
            result = await asyncio.wait_for(_search_mod.search(stock_id), timeout=SEARCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return {"status": "error", "message": f"盈再表查詢逾時（{SEARCH_TIMEOUT_SECONDS} 秒）"}
        except Exception as e:
            return {"status": "error", "message": f"{type(e).__name__}: {e}"}

    if isinstance(result, dict):
        _set_cached_search(stock_id, result)
        return result
    return {"status": "error", "message": "盈再表回傳格式異常"}


async def quick_analyze(stock_ids: list[str]) -> str:
    """Analyze stocks directly without LLM. Returns formatted text."""
    normalized_stock_ids = _normalize_stock_ids(stock_ids)
    if not normalized_stock_ids:
        return "請輸入有效股票代號（例如 2330）"

    semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)
    search_tasks = [_run_search(sid, semaphore) for sid in normalized_stock_ids]

    # get_price is sync, run in thread pool
    loop = asyncio.get_running_loop()
    price_task = loop.run_in_executor(None, _price_mod.get_price, normalized_stock_ids)

    # Wait for everything concurrently
    search_results = await asyncio.gather(*search_tasks, return_exceptions=False)
    try:
        price_data = await price_task
    except Exception:
        price_data = []

    # Build price lookup
    prices = {}
    if isinstance(price_data, list):
        for p in price_data:
            prices[p["stock_id"]] = p

    # Format output
    lines = []
    if len(normalized_stock_ids) < len(stock_ids):
        lines.append(
            f"⚠️ 免費版效能模式：一次最多查詢 {MAX_STOCK_IDS_PER_REQUEST} 檔，已優先處理前 {len(normalized_stock_ids)} 檔。"
        )
        lines.append("")

    for sid, search_result in zip(normalized_stock_ids, search_results):
        if isinstance(search_result, dict) and search_result.get("status") == "error":
            search_error = search_result.get("message", "查詢失敗")
        else:
            search_error = ""

        name = search_result.get("name", "") if isinstance(search_result, dict) else ""
        cheap = _parse_float(search_result.get("cheap_price", "")) if isinstance(search_result, dict) else None
        expensive = _parse_float(search_result.get("expensive_price", "")) if isinstance(search_result, dict) else None

        price_info = prices.get(sid, {})
        current = _parse_float(price_info.get("price", ""))
        stock_name = price_info.get("name", name)

        if search_error:
            if current is not None:
                lines.append(f"⚠️ {sid} {stock_name or sid}")
                lines.append(f"  現價:{current}")
                lines.append("  建議：無法判斷")
                lines.append(f"  無法取得盈再表貴價/淑價：{search_error}")
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
    """Parse a string to float, return None on failure."""
    if not val:
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, AttributeError):
        return None
