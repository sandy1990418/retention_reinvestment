#!/usr/bin/env python3
"""Query real-time Taiwan stock prices (supports multiple stocks at once)."""

import json
import sys
import ssl
import urllib.request


def get_price(stock_ids: list[str]) -> list[dict]:
    """從 TWSE 查詢股票即時價格。"""
    # Build query string (check both TSE listed and OTC stocks)
    ex_ch = "|".join(
        [f"tse_{sid}.tw" for sid in stock_ids] +
        [f"otc_{sid}.tw" for sid in stock_ids]
    )
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch}&json=1&delay=0"

    # Handle SSL certificate issues
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if "msgArray" not in data or not data["msgArray"]:
        return []

    results = []
    seen = set()
    for info in data["msgArray"]:
        sid = info.get("c", "")
        if not sid or sid in seen:
            continue
        seen.add(sid)

        name = info.get("n", "未知")
        price = info.get("z", "-")
        if price == "-":
            price = info.get("y", "N/A")
        yesterday = info.get("y", "N/A")

        results.append({
            "stock_id": sid,
            "name": name,
            "price": price,
            "yesterday_close": yesterday,
        })

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-id", action="append", required=True, help="股票代號（可多次指定）")
    args = parser.parse_args()

    stock_ids = args.stock_id
    try:
        results = get_price(stock_ids)
        if not results:
            print(json.dumps({"status": "error", "message": f"查無股票資料: {stock_ids}"}, ensure_ascii=False))
            sys.exit(1)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
