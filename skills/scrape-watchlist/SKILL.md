---
name: scrape-watchlist
description: 登入盈再表網站爬取使用者 Watchlist 中所有股票的貴價與淑價資料。當使用者想要查看持股的買賣建議、查詢貴價淑價、或分析 Watchlist 時使用此技能。
metadata:
  author: hschen
  version: "1.0"
---

# 爬取盈再表 Watchlist

## 使用時機

- 使用者想知道哪些股票該買或該賣
- 使用者要求分析 Watchlist
- 需要取得盈再表上的貴價、淑價資料

## 使用方式

使用 `run_skill_script` 工具：

1. **skill_name**: "scrape-watchlist"
2. **script_name**: "scripts/scrape.py"
3. **args**: 不需要參數（帳密從環境變數讀取）

回傳 JSON 格式的股票清單，每支股票包含盈再表上顯示的所有欄位（股票代號、名稱、貴價、淑價等）。

## 回傳格式範例

```json
[
  {
    "股票代號": "2330",
    "名稱": "台積電",
    "貴價": "850",
    "淑價": "550"
  }
]
```
