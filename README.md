# 文章閱讀數監測（Article Monitor）

定時爬取多平台文章閱讀數，支援本地 SQLite 儲存、CSV 導出與飛書 Bitable 同步。

## 快速開始

- **Docker（推薦）**  
  ```bash
  cd article-monitor
  docker compose up -d --build
  ```
  預設埠：5000；預設為 2 核 2GB 低資源配置。

- **本機執行**  
  ```bash
  cd article-monitor
  python -m venv .venv && .venv\Scripts\activate   # Windows
  pip install -r requirements.txt
  python -m playwright install chromium
  cp .env.example .env   # 可選，依需修改
  python run_monitor.py
  ```
  預設訪問：http://127.0.0.1:5001（埠可由 `FLASK_PORT` 或 `.env` 設定）。

## 專案結構

| 路徑 | 說明 |
|------|------|
| `article-monitor/` | 應用根目錄：`run_monitor.py`、`requirements.txt`、Dockerfile、docker-compose.yml |
| `article-monitor/monitor/` | 核心程式：Flask API、爬蟲、資料庫、Bitable 同步等 |
| `article-monitor/.env.example` | 環境變數範本（複製為 `.env` 使用） |
| `docs/` | 說明文件 |
| `codemaps/` | 架構與模組結構說明（供開發參考） |

## 文件

- **[參與貢獻（CONTRIB）](docs/CONTRIB.md)**：開發環境、可用指令、環境變數、測試與 PR 流程  
- **[維運手冊（RUNBOOK）](docs/RUNBOOK.md)**：部署、監控、健康檢查、常見問題與回滾  
- **[應用說明（monitor/README）](article-monitor/monitor/README.md)**：功能、支援網站、配置與低資源部署  
- **API 說明**：`article-monitor/API_README.md`

## 支援平台

掘金、CSDN、博客園、51CTO、電子發燒友、SegmentFault、簡書等（見 `monitor/platform_rules.py` 與 `ALLOWED_PLATFORMS`）。

## 授權與貢獻

請勿提交敏感資訊；開發與測試流程見 [docs/CONTRIB.md](docs/CONTRIB.md)。
