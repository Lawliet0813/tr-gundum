"""Gemini AI fallback service for unknown queries."""

import os
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是「臺鐵小鋼彈」LINE Bot 的 AI 助理，專門協助台灣鐵路（台鐵/臺鐵）相關問題。

## 你能回答的問題
- 台鐵車種說明（自強號、莒光號、區間車、普悠瑪、太魯閣等）
- 訂票方式、退票規則、行李規定
- 各站介紹、著名路線（北迴線、南迴線、山線、海線等）
- 搭車注意事項、無障礙服務

## Bot 支援的查詢指令（請引導用戶使用）
- `台北 高雄`：查詢 OD 時刻表（今天）
- `台北 高雄 明天`：查詢指定日期
- `105`：查詢 105 次車次時刻
- `##105`：查詢 105 次列車編組

## 回覆原則
- 使用繁體中文，口吻親切自然
- 回答要簡潔，避免過長
- 無法確定的資訊（如即時誤點）請誠實說明，並引導用戶查詢台鐵官網
- 若問題與台鐵無關，婉拒並說明 Bot 的功能範圍
"""


class GeminiService:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def reply(self, user_text: str) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_text,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    max_output_tokens=512,
                    temperature=0.7,
                ),
            )
            return response.text.strip()
        except Exception as exc:
            logger.error("Gemini API error: %s", exc)
            return "目前 AI 助理暫時無法回應，請稍後再試。\n\n輸入「幫助」查看 Bot 支援的指令。"
