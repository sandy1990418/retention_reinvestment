import asyncio
from contextlib import asynccontextmanager

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
from agent.agent import create_agent
from agent.deps import StockDeps


@asynccontextmanager
async def lifespan(app: FastAPI):
    agent, skills_toolset = create_agent()
    app.state.agent = agent
    app.state.skills_toolset = skills_toolset
    app.state.line_config = Configuration(access_token=config.LINE_CHANNEL_ACCESS_TOKEN)
    app.state.background_tasks: set = set()
    yield


app = FastAPI(lifespan=lifespan)
parser = WebhookParser(config.LINE_CHANNEL_SECRET)


async def run_agent_and_reply(agent, deps: StockDeps, user_message: str, line_config, user_id: str):
    """Run agent in background and send results via push message when done."""
    try:
        result = await agent.run(user_message, deps=deps)
        output = result.output

        # Format reply
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

        reply_text = "\n".join(lines).strip()

    except Exception as e:
        reply_text = f"分析過程發生錯誤：{str(e)}"

    # Send via push message (not limited by reply token's 30-second expiry)
    async with AsyncApiClient(line_config) as api_client:
        line_api = AsyncMessagingApi(api_client)
        if len(reply_text) > 4500:
            chunks = [reply_text[i:i + 4500] for i in range(0, len(reply_text), 4500)]
            for chunk in chunks:
                await line_api.push_message(
                    PushMessageRequest(to=user_id, messages=[TextMessage(text=chunk)])
                )
        else:
            await line_api.push_message(
                PushMessageRequest(to=user_id, messages=[TextMessage(text=reply_text)])
            )


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

        # Quickly reply "processing" using the reply token
        async with AsyncApiClient(app.state.line_config) as api_client:
            line_api = AsyncMessagingApi(api_client)
            await line_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="分析中，請稍候...")]
                )
            )

        # Run agent in background
        deps = StockDeps(
            stock_email=config.STOCK_EMAIL,
            stock_password=config.STOCK_PASSWORD,
        )
        task = asyncio.create_task(
            run_agent_and_reply(app.state.agent, deps, user_message, app.state.line_config, user_id)
        )
        app.state.background_tasks.add(task)
        task.add_done_callback(app.state.background_tasks.discard)

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
