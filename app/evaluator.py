from __future__ import annotations

import json
import os
from typing import Any, Callable

import requests

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

ProgressCallback = Callable[[int, str], None]


def _call_llm(prompt: str) -> dict[str, Any]:
    api_key = os.environ["OPENAI_API_KEY"]
    response = requests.post(
        OPENAI_CHAT_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-5.4",
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "你是嚴謹的 8D 報告審查 AI。"},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=120,
    )
    response.raise_for_status()
    body = response.json()
    return json.loads(body["choices"][0]["message"]["content"])


def _build_batch_prompt(report_map: dict[str, str], criteria_map: dict[str, str]) -> str:
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
        "評分並提供詳細、可執行的改善建議。\n"
        "分數範圍為 0~20 且需符合標準分級描述。\n"
        "請針對每個欄位至少提供 3 點 gap_suggestions，且每點都要具體到可落地執行。\n"
        "請只輸出 JSON，格式如下：\n"
        "{\n"
        '  "field_results": [\n'
        "    {\n"
        '      "field": "欄位名稱",\n'
        '      "score": 0,\n'
        '      "comment": "評語",\n'
        '      "gap_suggestions": ["建議1", "建議2", "建議3"]\n'
        "    }\n"
        "  ],\n"
        '  "overall_summary": "整體總結"\n'
        "}\n"
        "以下是資料：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _build_single_field_prompt(field: str, content: str, criteria: str) -> str:
    return (
        "你是資深 SQE/品質系統稽核專家。請僅針對單一欄位進行評核，"
        "並提供詳細、可執行的改善建議。\n"
        "分數範圍為 0~20 且需符合標準分級描述。\n"
        "請至少提供 3 點 gap_suggestions，且每點都要具體到可落地執行。\n"
        "請只輸出 JSON，格式如下：\n"
        "{\n"
        '  "field_result": {\n'
        '    "field": "欄位名稱",\n'
        '    "score": 0,\n'
        '    "comment": "評語",\n'
        '    "gap_suggestions": ["建議1", "建議2", "建議3"]\n'
        "  }\n"
        "}\n"
        "以下是資料：\n"
        f"{json.dumps({'field': field, 'report_content': content, 'criteria': criteria}, ensure_ascii=False, indent=2)}"
    )


def _normalize_scores(field_results: list[dict[str, Any]]) -> None:
    for row in field_results:
        score = int(row.get("score", 0))
        row["score"] = max(0, min(20, score))


def _build_overall_summary(field_results: list[dict[str, Any]]) -> str:
    if not field_results:
        return "無可評核欄位。"

    avg_score = sum(int(r.get("score", 0)) for r in field_results) / len(field_results)
    top = sorted(field_results, key=lambda x: int(x.get("score", 0)), reverse=True)[:2]
    low = sorted(field_results, key=lambda x: int(x.get("score", 0)))[:2]

    top_text = "、".join(f"{r.get('field', '')}({r.get('score', 0)})" for r in top)
    low_text = "、".join(f"{r.get('field', '')}({r.get('score', 0)})" for r in low)
    return (
        f"本次共評核 {len(field_results)} 個欄位，平均分數 {avg_score:.1f}/20。"
        f"相對表現較佳欄位：{top_text}；"
        f"優先改善欄位：{low_text}。"
        "建議優先補強低分欄位之證據完整性、量化數據與防呆閉環。"
    )


def evaluate_8d_report(
    report_map: dict[str, str],
    criteria_map: dict[str, str],
    mode: str = "batch",
    progress_cb: ProgressCallback | None = None,
) -> dict[str, Any]:
    if mode not in {"batch", "per_field"}:
        raise ValueError("mode 僅支援 batch 或 per_field")

    if mode == "batch":
        data = _call_llm(_build_batch_prompt(report_map, criteria_map))
        if "field_results" not in data or "overall_summary" not in data:
            raise ValueError("AI 回傳格式不正確")
        _normalize_scores(data["field_results"])
        return data

    field_results: list[dict[str, Any]] = []
    total = len(report_map)
    for idx, (field, content) in enumerate(report_map.items(), start=1):
        if progress_cb:
            current = 45 + int((idx - 1) * 40 / max(total, 1))
            progress_cb(current, f"逐欄評核中 ({idx}/{total})：{field}")

        prompt = _build_single_field_prompt(field, content, criteria_map[field])
        data = _call_llm(prompt)
        row = data.get("field_result")
        if not isinstance(row, dict):
            raise ValueError(f"欄位 {field} 的 AI 回傳格式不正確")
        field_results.append(row)

    _normalize_scores(field_results)
    return {
        "field_results": field_results,
        "overall_summary": _build_overall_summary(field_results),
    }
