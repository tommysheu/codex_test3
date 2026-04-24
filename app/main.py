from __future__ import annotations

import io
import os
from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.evaluator import evaluate_8d_report

app = FastAPI(
    title="AI 8D 報告智能評核 Prototype",
    description="上傳 8D 報告與評核標準 Excel，使用 GPT-5.4 產出欄位評核結果。",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory job store for MVP.
JOBS: dict[str, dict[str, Any]] = {}


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


def _enrich_with_original_content(result: dict[str, Any], report_map: dict[str, str]) -> dict[str, Any]:
    for row in result.get("field_results", []):
        field = row.get("field", "")
        row["original_content"] = report_map.get(field, "")
    return result


def _set_job(job_id: str, *, status: str, progress: int, message: str, result: dict[str, Any] | None = None) -> None:
    JOBS[job_id].update(
        {
            "status": status,
            "progress": progress,
            "message": message,
            "result": result,
        }
    )


def _process_job(job_id: str, report_bytes: bytes, criteria_bytes: bytes) -> None:
    try:
        _set_job(job_id, status="running", progress=10, message="正在解析 8D 報告 Excel...")
        report_map = _read_excel_mapping(report_bytes, "原始內容")

        _set_job(job_id, status="running", progress=25, message="正在解析評核標準 Excel...")
        criteria_map = _read_excel_mapping(criteria_bytes, "評核標準")

        missing = [k for k in report_map.keys() if k not in criteria_map]
        if missing:
            raise HTTPException(status_code=400, detail=f"評核標準缺少項目: {missing}")

        _set_job(job_id, status="running", progress=45, message="資料檢查完成，準備呼叫 GPT-5.4...")
        result = evaluate_8d_report(report_map, criteria_map)

        _set_job(job_id, status="running", progress=85, message="AI 回覆完成，正在整理欄位結果...")
        result = _enrich_with_original_content(result, report_map)

        _set_job(job_id, status="completed", progress=100, message="評核完成。", result=result)
    except HTTPException as exc:
        _set_job(job_id, status="failed", progress=100, message=exc.detail)
    except Exception as exc:  # noqa: BLE001
        _set_job(job_id, status="failed", progress=100, message=f"AI 評核失敗: {exc}")


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
        return _enrich_with_original_content(result, report_map)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"AI 評核失敗: {exc}") from exc


@app.post("/api/evaluate/start")
async def evaluate_start(
    background_tasks: BackgroundTasks,
    report_file: UploadFile = File(..., description="8D報告內容 Excel"),
    criteria_file: UploadFile = File(..., description="評核標準 Excel"),
) -> dict[str, str]:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="伺服器未設定 OPENAI_API_KEY。")

    if not report_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="report_file 需為 Excel 檔案。")
    if not criteria_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="criteria_file 需為 Excel 檔案。")

    report_bytes = await report_file.read()
    criteria_bytes = await criteria_file.read()

    job_id = str(uuid4())
    JOBS[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "任務已建立，等待處理...",
        "result": None,
    }

    background_tasks.add_task(_process_job, job_id, report_bytes, criteria_bytes)
    return {"job_id": job_id}


@app.get("/api/evaluate/status/{job_id}")
def evaluate_status(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到任務 ID")
    return job
