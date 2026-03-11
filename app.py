import asyncio
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

import config
from utils import watchlist
from utils.quick_lookup import quick_analyze
from agent.agent import create_agent
from agent.deps import StockDeps


@asynccontextmanager
async def lifespan(app: FastAPI):
    agent, skills_toolset = create_agent()
    app.state.agent = agent
    app.state.skills_toolset = skills_toolset
    app.state.line_config = Configuration(access_token=config.LINE_CHANNEL_ACCESS_TOKEN)
    app.state.deps = StockDeps(
        stock_email=config.STOCK_EMAIL,
        stock_password=config.STOCK_PASSWORD,
    )
    app.state.background_tasks: set = set()
    yield


app = FastAPI(lifespan=lifespan)
parser = WebhookParser(config.LINE_CHANNEL_SECRET)


# --- LINE helpers ---

async def send_push(line_config, user_id: str, text: str):
    """Send a push message to a user, chunking if needed."""
    async with AsyncApiClient(line_config) as api_client:
        line_api = AsyncMessagingApi(api_client)
        if len(text) > 4500:
            chunks = [text[i:i + 4500] for i in range(0, len(text), 4500)]
            for chunk in chunks:
                await line_api.push_message(
                    PushMessageRequest(to=user_id, messages=[TextMessage(text=chunk)])
                )
        else:
            await line_api.push_message(
                PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])
            )


def format_analysis(output) -> str:
    """Format AnalysisResult into readable text."""
    lines = [output.summary, ""]
    for rec in output.recommendations:
        price_info = f"現價:{rec.current_price}" if rec.current_price else ""
        cheap_info = f" 淑價:{rec.cheap_price}" if rec.cheap_price else ""
        exp_info = f" 貴價:{rec.expensive_price}" if rec.expensive_price else ""
        emoji = "🔴" if rec.recommendation == "賣出" else "🟢" if rec.recommendation == "買入" else "⚪"
        lines.append(f"{emoji} {rec.stock_id} {rec.stock_name}")
        lines.append(f"  {price_info}{cheap_info}{exp_info}")
        lines.append(f"  建議：{rec.recommendation}")
        lines.append(f"  {rec.reasoning}")
        lines.append("")
    return "\n".join(lines).strip()


# --- Command parsing ---

def parse_command(text: str) -> tuple[str, str]:
    """Parse user message into (command, arg).

    Returns:
        ("track", "2330")       - 追蹤 2330
        ("untrack", "2330")     - 取消追蹤 2330 / 取消 2330
        ("list", "")            - 追蹤清單 / 清單
        ("help", "")            - 指令 / 幫助
        ("query", original_msg) - anything else → agent query
    """
    t = text.strip()

    if not t:
        return ("help", "")

    # 追蹤 <stock_id>
    m = re.match(r"^追蹤\s+(\w+)$", t)
    if m:
        return ("track", m.group(1))

    # 取消追蹤 <stock_id> or 取消 <stock_id>
    m = re.match(r"^取消追蹤?\s+(\w+)$", t)
    if m:
        return ("untrack", m.group(1))

    # 追蹤清單 / 清單
    if t in ("追蹤清單", "清單", "我的清單"):
        return ("list", "")

    # 指令 / 幫助
    if t in ("指令", "幫助", "help"):
        return ("help", "")

    # Simple stock IDs: "2330" or "2330 2317" or "查 2330"
    cleaned = re.sub(r"^(查|分析|看)\s*", "", t)
    stock_ids = re.findall(r"\b(\d{4,6})\b", cleaned)
    if stock_ids:
        return ("quick", " ".join(stock_ids))

    # Default: agent query
    return ("query", t)


HELP_TEXT = """指令說明：
• 2330 → 快速查詢（直接輸入股票代號）
• 2330 2317 → 同時查多支
• 追蹤 2330 → 加入定期追蹤
• 取消追蹤 2330 → 移除追蹤
• 追蹤清單 → 查看追蹤的股票
• 其他文字 → AI 深度分析
• 指令 → 顯示此說明"""


# --- Handlers ---

async def handle_command(command: str, arg: str, user_id: str, reply_token: str):
    """Handle watchlist commands with immediate reply."""
    async with AsyncApiClient(app.state.line_config) as api_client:
        line_api = AsyncMessagingApi(api_client)

        if command == "track":
            if not re.match(r"^\d{4,6}$", arg):
                reply = f"股票代號格式不正確：{arg}（請輸入 4-6 位數字，例如 2330）"
            else:
                added = watchlist.add_stock(user_id, arg)
                reply = f"已將 {arg} 加入追蹤清單" if added else f"{arg} 已在追蹤清單中"

        elif command == "untrack":
            removed = watchlist.remove_stock(user_id, arg)
            reply = f"已將 {arg} 從追蹤清單移除" if removed else f"{arg} 不在追蹤清單中"

        elif command == "list":
            stocks = watchlist.list_stocks(user_id)
            if stocks:
                reply = "你的追蹤清單：\n" + "\n".join(f"• {s}" for s in stocks)
            else:
                reply = "追蹤清單是空的。輸入「追蹤 2330」來新增。"

        elif command == "help":
            reply = HELP_TEXT

        else:
            reply = "未知指令"

        await line_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=reply)]
            )
        )


async def quick_lookup_and_reply(stock_ids: list[str], line_config, user_id: str):
    """Direct stock lookup without LLM — much faster."""
    try:
        reply_text = await quick_analyze(stock_ids)
    except Exception as e:
        reply_text = f"查詢發生錯誤：{str(e)}"
    await send_push(line_config, user_id, reply_text)


async def run_agent_and_reply(agent, deps: StockDeps, user_message: str, line_config, user_id: str):
    """Run agent in background and send results via push message when done."""
    try:
        result = await agent.run(user_message, deps=deps)
        reply_text = format_analysis(result.output)
    except Exception as e:
        reply_text = f"分析過程發生錯誤：{str(e)}"

    await send_push(line_config, user_id, reply_text)


# --- Routes ---

@app.post("/callback")
async def line_callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent) or not isinstance(event.message, TextMessageContent):
            continue

        user_message = event.message.text
        user_id = event.source.user_id
        command, arg = parse_command(user_message)

        # Watchlist commands: reply immediately
        if command in ("track", "untrack", "list", "help"):
            await handle_command(command, arg, user_id, event.reply_token)
            continue

        # Reply "processing" for all async operations
        async with AsyncApiClient(app.state.line_config) as api_client:
            line_api = AsyncMessagingApi(api_client)
            await line_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="分析中，請稍候...")]
                )
            )

        # Quick lookup for simple stock IDs (bypasses LLM, ~20-30s)
        if command == "quick":
            stock_ids = arg.split()
            task = asyncio.create_task(
                quick_lookup_and_reply(stock_ids, app.state.line_config, user_id)
            )
        else:
            # Complex query: use full agent (slower but handles natural language)
            task = asyncio.create_task(
                run_agent_and_reply(app.state.agent, app.state.deps, user_message, app.state.line_config, user_id)
            )
        app.state.background_tasks.add(task)
        task.add_done_callback(app.state.background_tasks.discard)

    return {"status": "ok"}


@app.post("/cron/notify")
async def cron_notify(request: Request):
    """Scheduled endpoint: analyze all tracked stocks and push results to users."""
    # Verify cron secret
    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {config.CRON_SECRET}"
    if not config.CRON_SECRET or not secrets.compare_digest(auth, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")

    users = watchlist.get_all_users_with_stocks()
    if not users:
        return {"status": "ok", "message": "No users with tracked stocks"}

    # Limit concurrency to avoid overwhelming LLM API and Playwright
    semaphore = asyncio.Semaphore(3)

    async def notify_user(user_id: str, stock_ids: list[str]):
        async with semaphore:
            try:
                result = await quick_analyze(stock_ids)
                text = "📊 每日追蹤報告\n\n" + result
            except Exception as e:
                text = f"每日追蹤分析失敗：{str(e)}"
            await send_push(app.state.line_config, user_id, text)

    tasks = [notify_user(uid, sids) for uid, sids in users.items()]
    await asyncio.gather(*tasks, return_exceptions=True)

    return {"status": "ok", "users_notified": len(users)}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
