# AI 8D 報告智能評核 Prototype

## 架構
- 前端：`static/index.html`（HTML + JavaScript）
- 後端：FastAPI（Swagger UI: `/docs`）
- AI：OpenAI `gpt-5.4` API

## 啟動
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="<your-key>"
uvicorn app.main:app --reload
```

開啟：
- 首頁：`http://127.0.0.1:8000/`
- Swagger：`http://127.0.0.1:8000/docs`

## Excel 格式
### 8D 報告檔
需包含欄位：
- `項目`
- `原始內容`（若無此欄，系統會使用除 `項目` 之外的第一個欄位）

### 評核標準檔
需包含欄位：
- `項目`
- `評核標準`（若無此欄，系統會使用除 `項目` 之外的第一個欄位）

## API
### 1) 同步評核
`POST /api/evaluate`
- form-data:
  - `report_file`: Excel
  - `criteria_file`: Excel

### 2) 非同步評核（前端建議）
1. `POST /api/evaluate/start` 建立任務，回傳 `job_id`
2. `GET /api/evaluate/status/{job_id}` 查詢進度

回傳結果：
- `field_results[]`
  - `field`
  - `original_content`
  - `score` (0-20)
  - `comment`
  - `gap_suggestions[]`
- `overall_summary`
