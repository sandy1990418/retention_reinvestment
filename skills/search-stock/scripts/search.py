#!/usr/bin/env python3
"""在盈再表搜尋特定股票的貴價與淑價。

利用 Screener 頁面的全域搜尋自動完成功能：
1. 在搜尋欄輸入股票代號，觸發 autocomplete
2. 點擊 [TW] 的結果項目，導航到 Watchlist 頁面
3. 從 Watchlist 頁面抓取該股票的貴價、淑價等資料
"""

import json
import sys
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

STORAGE_STATE_PATH = Path(__file__).resolve().parents[3] / "storage_state.json"


async def search(stock_id: str):
    if not STORAGE_STATE_PATH.exists():
        print(json.dumps({
            "status": "error",
            "message": "找不到 storage_state.json，請先執行 scripts/login_save_cookies.py 手動登入。"
        }, ensure_ascii=False))
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=str(STORAGE_STATE_PATH),
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        try:
            await page.goto("https://stocks.ddns.net/Screener.aspx", wait_until="domcontentloaded", timeout=60000)

            if "login" in page.url.lower():
                print(json.dumps({
                    "status": "error",
                    "message": "Cookies 已過期，請重新執行 scripts/login_save_cookies.py 手動登入。"
                }, ensure_ascii=False))
                sys.exit(1)

            await page.wait_for_selector("#ctl00_txtGlobalSearch", timeout=10000)

            # 在搜尋欄逐字輸入股票代號，觸發 autocomplete
            await page.click("#ctl00_txtGlobalSearch")
            await page.type("#ctl00_txtGlobalSearch", stock_id, delay=80)

            # 等待 autocomplete 下拉選單出現，找 [TW] 項目
            tw_item = page.locator(f'div.AutoExtenderList:has-text("[TW]"):has-text("{stock_id}")')
            try:
                await tw_item.first.wait_for(state="visible", timeout=5000)
            except Exception:
                pass
            count = await tw_item.count()

            if count == 0:
                print(json.dumps({
                    "status": "error",
                    "message": f"在盈再表搜尋中找不到台灣股票 {stock_id}。"
                }, ensure_ascii=False))
                sys.exit(1)

            # 點擊後會導航到 Watchlist 頁面
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                await tw_item.first.click()

            await page.wait_for_selector("#ctl00_ContentPlaceHolder1_GridView2", timeout=15000)

            # 在 Watchlist 頁面找到目標股票的資料
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
                print(json.dumps({
                    "status": "error",
                    "message": f"在盈再表 Watchlist 中找不到 {stock_id} 的資料。"
                }, ensure_ascii=False))
                sys.exit(1)

            del result["found"]
            print(json.dumps(result, ensure_ascii=False, indent=2))

        except Exception as e:
            print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
            sys.exit(1)
        finally:
            await browser.close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-id", required=True, help="股票代號，例如 2317")
    args = parser.parse_args()
    asyncio.run(search(args.stock_id))


if __name__ == "__main__":
    main()
