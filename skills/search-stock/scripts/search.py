#!/usr/bin/env python3
"""Search for a specific stock's expensive/cheap prices on the Retention & Reinvestment Table.

Uses the Screener page's global search autocomplete:
1. Type stock ID in the search bar to trigger autocomplete
2. Click the [TW] result item to navigate to the Watchlist page
3. Extract the stock's expensive price, cheap price, and other data from the Watchlist page
"""

import json
import sys
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from utils.storage import get_storage_state_path


async def search(stock_id: str) -> dict:
    """Search a stock and return result dict. Raises on fatal errors."""
    state_path = get_storage_state_path()
    if not state_path:
        return {"status": "error", "message": "找不到 storage_state.json，請先執行 scripts/login_save_cookies.py 手動登入。"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            storage_state=state_path,
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        try:
            await page.goto("https://stocks.ddns.net/Screener.aspx", wait_until="domcontentloaded", timeout=60000)

            if "login" in page.url.lower():
                return {"status": "error", "message": "Cookies 已過期，請重新執行 scripts/login_save_cookies.py 手動登入。"}

            await page.wait_for_selector("#ctl00_txtGlobalSearch", timeout=10000)

            # Type stock ID character by character in search bar to trigger autocomplete
            await page.click("#ctl00_txtGlobalSearch")
            await page.type("#ctl00_txtGlobalSearch", stock_id, delay=20)

            # Wait for autocomplete dropdown and find the [TW] item
            tw_item = page.locator(f'div.AutoExtenderList:has-text("[TW]"):has-text("{stock_id}")')
            try:
                await tw_item.first.wait_for(state="visible", timeout=5000)
            except Exception:
                pass
            count = await tw_item.count()

            if count == 0:
                return {"status": "error", "message": f"在盈再表搜尋中找不到台灣股票 {stock_id}。"}

            # Click to navigate to the Watchlist page
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                await tw_item.first.click()

            await page.wait_for_selector("#ctl00_ContentPlaceHolder1_GridView2", timeout=15000)

            # Find the target stock's data on the Watchlist page
            result = await page.evaluate("""(targetId) => {
                const rows = document.querySelectorAll('#ctl00_ContentPlaceHolder1_GridView2 tr');

                for (const row of rows) {
                    const cardTitle = row.querySelector('.card-title');
                    if (!cardTitle) continue;
                    const stockId = cardTitle.textContent.trim();
                    if (stockId !== targetId) continue;

                    const get = (sel) => {
                        const el = row.querySelector(sel);
                        return el ? el.textContent.trim() : '';
                    };

                    return {
                        stock_id: stockId,
                        name: get('[id*="ViewlblIndustry"]'),
                        exchange: get('[id*="lblExchange"]'),
                        expected_return: get('[id*="lblIRRPortrait"]'),
                        cheap_price: get('[id*="lblNPVLOWPortrait"]'),
                        expensive_price: get('[id*="lblNPVHIGHPortrait"]'),
                        nav: get('[id*="lblNAVPortrait"]'),
                        found: true,
                    };
                }

                return {found: false};
            }""", stock_id)

            if not result.get("found"):
                return {"status": "error", "message": f"在盈再表 Watchlist 中找不到 {stock_id} 的資料。"}

            del result["found"]
            return result

        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-id", required=True, help="股票代號，例如 2317")
    args = parser.parse_args()
    result = asyncio.run(search(args.stock_id))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
