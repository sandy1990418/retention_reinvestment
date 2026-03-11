---
name: get-stock-price
description: 查詢台灣股票的即時價格。當需要知道某支股票的當前市場價格、用來與貴價淑價比較時使用此技能。
metadata:
  author: hschen
  version: "1.0"
---

# 查詢台灣股票即時價格

## 使用時機

- 需要知道某支股票的現在價格
- 與盈再表的貴價、淑價比較以判斷買賣時機
- 使用者詢問特定股票的即時報價

## 使用方式

使用 `run_skill_script` 工具：

1. **skill_name**: "get-stock-price"
2. **script_name**: "scripts/get_price.py"
3. **args**: `{"stock-id": ["2330", "2317"]}` （傳入股票代號清單）

## 回傳格式範例

```json
[
  {
    "stock_id": "2330",
    "name": "台積電",
    "price": "890.00",
    "yesterday_close": "885.00"
  }
]
```
