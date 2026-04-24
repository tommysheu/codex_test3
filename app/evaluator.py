from __future__ import annotations

import json
import os
from typing import Any

import requests

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


def _build_prompt(report_map: dict[str, str], criteria_map: dict[str, str]) -> str:
    payload = []
    for field, content in report_map.items():
        payload.append(
            {
                "field": field,
                "report_content": content,
                "criteria": criteria_map[field],
            }
        )

    return (
        "你是資深 SQE/品質系統稽核專家。請根據每個欄位對應評核標準，"
        "評分並提供精簡、可執行的改善建議。\n"
        "分數範圍為 0~20 且需符合標準分級描述。\n"
        "請只輸出 JSON，格式如下：\n"
        "{\n"
        '  "field_results": [\n'
        "    {\n"
        '      "field": "欄位名稱",\n'
        '      "score": 0,\n'
        '      "comment": "評語",\n'
        '      "gap_suggestions": ["建議1", "建議2"]\n'
        "    }\n"
        "  ],\n"
        '  "overall_summary": "整體總結"\n'
        "}\n"
        "以下是資料：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def evaluate_8d_report(report_map: dict[str, str], criteria_map: dict[str, str]) -> dict[str, Any]:
    prompt = _build_prompt(report_map, criteria_map)
    api_key = os.environ["OPENAI_API_KEY"]

    response = requests.post(
        OPENAI_CHAT_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o",
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "你是嚴謹的 8D 報告審查 AI。",
                },
                {"role": "user", "content": prompt},
            ],
        },
        timeout=120,
    )
    response.raise_for_status()

    body = response.json()
    content = body["choices"][0]["message"]["content"]
    data = json.loads(content)

    # basic schema guard
    if "field_results" not in data or "overall_summary" not in data:
        raise ValueError("AI 回傳格式不正確")

    for row in data["field_results"]:
        score = int(row.get("score", 0))
        row["score"] = max(0, min(20, score))

    return data
