#!/usr/bin/env python3
"""手動登入盈再表並儲存 cookies。
自動填入帳密，你只需要完成 reCAPTCHA 驗證並點登入。
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
        # 用普通瀏覽器模式（避免被偵測為自動化）
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        # 移除 webdriver 標記
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        await page.goto("https://stocks.ddns.net/App/Watchlist.aspx", wait_until="domcontentloaded", timeout=60000)

        # 自動填入帳密
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

        # 等待導航到 Watchlist 頁面（最多等 3 分鐘）
        try:
            # 等到 URL 包含 Watchlist 且有 table
            await page.wait_for_function(
                """() => {
                    return window.location.href.includes('Watchlist')
                        && document.querySelector('table tr td') !== null;
                }""",
                timeout=180000,
            )
            # 多等一下確保頁面完全載入
            await page.wait_for_timeout(2000)

            await context.storage_state(path=str(STORAGE_STATE_PATH))
            print(f"\n✅ 登入成功！Cookies 已儲存到: {STORAGE_STATE_PATH}")

        except Exception as e:
            print(f"\n⚠️ 等待逾時或錯誤: {e}")
            print(f"目前 URL: {page.url}")
            # 還是嘗試儲存
            await context.storage_state(path=str(STORAGE_STATE_PATH))
            print(f"已嘗試儲存 cookies 到: {STORAGE_STATE_PATH}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(login_and_save())
