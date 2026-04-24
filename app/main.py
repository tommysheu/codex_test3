from __future__ import annotations

import io
import os
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.evaluator import evaluate_8d_report

app = FastAPI(
    title="AI 8D 報告智能評核 Prototype",
    description="上傳 8D 報告與評核標準 Excel，使用 GPT-4o 產出欄位評核結果。",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse("static/index.html")


def _read_excel_mapping(raw_bytes: bytes, value_column_hint: str) -> dict[str, str]:
    try:
        df = pd.read_excel(io.BytesIO(raw_bytes))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Excel 讀取失敗: {exc}") from exc

    if "項目" not in df.columns:
        raise HTTPException(status_code=400, detail="Excel 格式錯誤：必須包含『項目』欄位。")

    if value_column_hint in df.columns:
        value_col = value_column_hint
    else:
        value_candidates = [c for c in df.columns if c != "項目"]
        if not value_candidates:
            raise HTTPException(status_code=400, detail="Excel 格式錯誤：找不到內容欄位。")
        value_col = value_candidates[0]

    normalized = (
        df[["項目", value_col]]
        .dropna(subset=["項目"])
        .assign(**{"項目": lambda x: x["項目"].astype(str).str.strip()})
        .assign(**{value_col: lambda x: x[value_col].fillna("").astype(str).str.strip()})
    )

    return {row["項目"]: row[value_col] for _, row in normalized.iterrows()}


@app.post("/api/evaluate")
async def evaluate(
    report_file: UploadFile = File(..., description="8D報告內容 Excel"),
    criteria_file: UploadFile = File(..., description="評核標準 Excel"),
) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="伺服器未設定 OPENAI_API_KEY。")

    if not report_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="report_file 需為 Excel 檔案。")
    if not criteria_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="criteria_file 需為 Excel 檔案。")

    report_bytes = await report_file.read()
    criteria_bytes = await criteria_file.read()

    report_map = _read_excel_mapping(report_bytes, "原始內容")
    criteria_map = _read_excel_mapping(criteria_bytes, "評核標準")

    missing = [k for k in report_map.keys() if k not in criteria_map]
    if missing:
        raise HTTPException(status_code=400, detail=f"評核標準缺少項目: {missing}")

    try:
        result = evaluate_8d_report(report_map, criteria_map)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"AI 評核失敗: {exc}") from exc

    return result
