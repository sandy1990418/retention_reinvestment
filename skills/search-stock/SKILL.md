---
name: search-stock
description: 在盈再表搜尋特定股票的貴價與淑價。當使用者詢問的股票不在 Watchlist 中時使用此技能。
metadata:
  author: hschen
  version: "1.0"
---

# 搜尋盈再表個股資料

## 使用時機

- 使用者詢問特定股票的貴價淑價
- 需要查詢特定股票的盈再表分析資料

## 使用方式

使用 `run_skill_script` 工具：

1. **skill_name**: "search-stock"
2. **script_name**: "scripts/search.py"
3. **args**: `{"stock-id": "2317"}`

回傳 JSON 包含：stock_id, name, exchange, expected_return, cheap_price, expensive_price, nav
