#!/usr/bin/env python3
"""Manually log into the Retention & Reinvestment Table and save cookies.
Auto-fills credentials; you only need to complete the reCAPTCHA and click login.
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_path)

STORAGE_STATE_PATH = Path(__file__).resolve().parents[1] / "storage_state.json"


async def login_and_save():
    email = os.environ.get("STOCKEMAIL", "")
    password = os.environ.get("STOCKEMAILPASSWORD", "")

    async with async_playwright() as p:
        # Use regular browser mode (avoid automation detection)
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        # Remove webdriver flag
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        await page.goto("https://stocks.ddns.net/App/Watchlist.aspx", wait_until="domcontentloaded", timeout=60000)

        # Auto-fill credentials
        if email and password:
            await page.fill('input[id$="txtUsername"]', email)
            await page.fill('input[id$="txtPassword"]', password)

        print("=" * 50)
        print("帳密已自動填入！")
        print("請在瀏覽器中：")
        print("  1. 完成 reCAPTCHA 驗證（勾選「我不是機器人」）")
        print("  2. 點擊「登入」按鈕")
        print("登入成功後會自動儲存 cookies")
        print("=" * 50)

        # Wait for navigation to Watchlist page (up to 3 minutes)
        try:
            # Wait until URL contains Watchlist and table is present
            await page.wait_for_function(
                """() => {
                    return window.location.href.includes('Watchlist')
                        && document.querySelector('table tr td') !== null;
                }""",
                timeout=180000,
            )
            # Wait a bit more to ensure page is fully loaded
            await page.wait_for_timeout(2000)

            await context.storage_state(path=str(STORAGE_STATE_PATH))
            print(f"\n✅ 登入成功！Cookies 已儲存到: {STORAGE_STATE_PATH}")

        except Exception as e:
            print(f"\n⚠️ 等待逾時或錯誤: {e}")
            print(f"目前 URL: {page.url}")
            # Still attempt to save
            await context.storage_state(path=str(STORAGE_STATE_PATH))
            print(f"已嘗試儲存 cookies 到: {STORAGE_STATE_PATH}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(login_and_save())
