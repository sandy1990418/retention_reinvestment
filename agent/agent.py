import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai_skills import SkillsToolset
from pydantic_ai_skills.local import LocalSkillScriptExecutor
from pydantic_ai_skills.directory import SkillsDirectory
from agent.models import get_model
from agent.deps import StockDeps


class StockRecommendation(BaseModel):
    """Buy/sell recommendation for a single stock."""
    stock_id: str
    stock_name: str
    current_price: float | None = None
    cheap_price: float | None = None
    expensive_price: float | None = None
    recommendation: Literal["買入", "賣出", "持有"]
    reasoning: str


class AnalysisResult(BaseModel):
    """Overall analysis result."""
    summary: str
    recommendations: list[StockRecommendation]


SYSTEM_PROMPT = """你是一個台灣股票分析助手。根據盈再表的「貴價」和「淑價」判斷股票買賣時機。

規則：
- 現價 ≥ 貴價 → 建議「賣出」
- 現價 ≤ 淑價 → 建議「買入」
- 淑價 < 現價 < 貴價 → 建議「持有」

工作流程（務必按步驟執行）：
1. 先用 load_skill 載入 "search-stock" 技能
2. 用 run_skill_script 執行 search-stock 的 scripts/search.py，args 為 {"stock-id": "股票代號"}，取得貴價淑價
3. 用 load_skill 載入 "get-stock-price" 技能
4. 用 run_skill_script 執行 get-stock-price 的 scripts/get_price.py，args 為 {"stock-id": ["股票代號"]}，取得即時價格
5. 比較現價與貴價淑價，給出建議

回覆使用繁體中文，簡潔明瞭。
"""

# Skills directory
SKILLS_DIR = str(Path(__file__).resolve().parent.parent / "skills")


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


SKILL_SCRIPT_TIMEOUT_SECONDS = _env_int("SKILL_SCRIPT_TIMEOUT_SECONDS", 120, 30)


def create_agent() -> tuple[Agent[StockDeps, AnalysisResult], SkillsToolset]:
    """Create stock analysis agent."""
    model = get_model()

    executor = LocalSkillScriptExecutor(timeout=SKILL_SCRIPT_TIMEOUT_SECONDS)
    skills_dir = SkillsDirectory(path=SKILLS_DIR, script_executor=executor)
    skills_toolset = SkillsToolset(directories=[skills_dir])

    stock_agent = Agent(
        model,
        deps_type=StockDeps,
        output_type=AnalysisResult,
        instructions=SYSTEM_PROMPT,
        toolsets=[skills_toolset],
    )

    # Dynamically inject skills list into agent instructions
    @stock_agent.instructions
    async def add_skills(ctx: RunContext[StockDeps]) -> str | None:
        return await skills_toolset.get_instructions(ctx)

    return stock_agent, skills_toolset
