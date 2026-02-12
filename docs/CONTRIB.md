# 參與貢獻（Article Monitor）

本文說明開發流程、可用指令、環境設定與測試方式。單一事實來源：`article-monitor/.env.example`、`article-monitor/run_monitor.py`、`article-monitor/monitor/config.py`。

## 開發環境

- **Python**：3.11+
- **工作目錄**：`article-monitor/`（倉庫根目錄為上一層）

### 環境準備

1. **建立虛擬環境並安裝依賴**

   **方式 A：PowerShell 腳本（Windows）**  
   在倉庫根目錄執行：
   ```powershell
   .\article-monitor\scripts\install_venv.ps1
   ```
   啟用：`article-monitor\.venv\Scripts\Activate.ps1`

   **方式 B：手動**
   ```bash
   cd article-monitor
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate  # Linux/macOS
   pip install -r requirements.txt
   ```

2. **（爬蟲必備）安裝 Playwright Chromium**
   ```bash
   python -m playwright install chromium
   ```

3. **複製環境變數範本並依需填寫**
   ```bash
   cp .env.example .env
   ```

應用程式碼在 `monitor/`，測試在 `tests/`。

---

## 可用指令一覽

本專案為 Python 專案，無 `package.json`。以下指令均在 `article-monitor/` 目錄下執行（另有說明者除外）。

| 用途 | 指令 | 說明 |
|------|------|------|
| 建立 venv 並安裝依賴 | `scripts/install_venv.ps1`（自倉庫根目錄執行） | 建立 `.venv`，依 `monitor/requirements.txt` 安裝 |
| 啟動 Web 服務 | `python run_monitor.py` | 啟動 Flask + 定時爬取排程（預設 127.0.0.1:5001） |
| 以模組方式啟動 | `cd monitor && python -m flask --app app run` 或執行 `app.py` | 依環境變數決定 port |
| 執行全部測試 | `python -m pytest tests/ -q` | Pytest，精簡輸出 |
| 測試 + 覆蓋率 | `python -m pytest --cov=monitor --cov-report=term-missing -q` | 終端機覆蓋率報告 |
| 覆蓋率 80% 門檻 | `python -m pytest --cov=monitor --cov-fail-under=80 -q` | 未達 80% 即失敗（見 `.coveragerc`） |
| 單一測試檔 | `python -m pytest tests/test_xxx.py -v` | 單檔、詳細輸出 |
| 語法檢查 | `python -m compileall monitor` | 編譯檢查 |
| Codemap 分析 | `node scripts/codemap-analyzer.mjs`（自倉庫根目錄） | 掃描 Python 匯入/結構，輸出 JSON |

---

## 環境變數

定義於 `monitor/config.py`；範本：`article-monitor/.env.example`。請勿提交敏感資訊，使用 `.env`（已加入 .gitignore）或系統環境變數。

### 日誌

| 變數 | 用途 | 格式 / 預設 |
|------|------|-------------|
| `ARTICLE_MONITOR_DEBUG_LOG` | 可選的除錯日誌檔案路徑 | 字串；留空則不寫入 |

### 爬取

| 變數 | 用途 | 格式 / 預設 |
|------|------|-------------|
| `CRAWL_INTERVAL_HOURS` | 爬取間隔（小時） | 整數，預設 `6` |
| `CRAWL_TIMEOUT` | 單次請求超時（秒） | 整數，預設 `60` |
| `CRAWL_CONCURRENCY` | 並發爬取數（1–10） | 整數，預設依資源模式（見下） |
| `CRAWL_DELAY` | 請求間延遲（秒） | 浮點數，預設 `1` |
| `CRAWL_CONCURRENCY_PER_DOMAIN` | 單一網域最大並發；0 表示不限制 | 整數，預設 `1` |
| `CRAWL_INTERLEAVE_BY_SITE` | 是否依站點交錯排程 | `True`/`False`，預設 `True` |
| `CRAWL_MIN_DELAY_PER_DOMAIN` | 同網域兩次請求最小間隔（秒） | 浮點數，預設 `0` |
| `CRAWL_MAX_RETRIES` | 最大重試次數（網路） | 整數，預設 `10` |
| `CRAWL_RETRY_DELAY` | 重試延遲（秒） | 浮點數，預設 `2` |
| `CRAWL_RETRY_BACKOFF` | 退避倍數 | 浮點數，預設 `1.5` |
| `CRAWL_RETRY_MAX_DELAY` | 最大重試延遲（秒） | 浮點數，預設 `30` |
| `CRAWL_RETRY_JITTER` | 重試是否加抖動 | `True`/`False`，預設 `True` |
| `CRAWL_RETRY_NETWORK_MAX` | 網路錯誤最大重試 | 整數，預設 `10` |
| `CRAWL_RETRY_PARSE_MAX` | 解析錯誤最大重試 | 整數，預設 `3` |
| `CRAWL_RETRY_SSL_MAX` | SSL 錯誤最大重試 | 整數，預設 `5` |
| `CRAWL_RETRY_SSL_DELAY` | SSL 重試固定延遲（秒） | 浮點數，預設 `5` |

### 資源與低記憶體模式（2 核 2GB）

| 變數 | 用途 | 格式 / 預設 |
|------|------|-------------|
| `RESOURCE_PROFILE` | 設為 `low` 啟用 2C2G 友善預設 | 字串，預設未設 |
| `LOW_MEMORY` | `1`/`true`/`yes` 等同 RESOURCE_PROFILE=low | 字串，預設未設 |
| `BROWSER_POOL_MAX_SIZE` | 瀏覽器池最大數量 | 整數，low 時 2，否則 5 |
| `BROWSER_POOL_MIN_SIZE` | 瀏覽器池最小數量 | 整數，low 時 1，否則 2 |
| `SQLITE_CACHE_SIZE_KB` | SQLite 每連接快取（KB） | 整數，low 時 2048，否則 65536 |
| `MAX_HEALTH_CHECK_WORKERS` | 健康檢查最大工作線程數 | 整數，low 時 4，否則 20 |
| `MAX_CONCURRENT_TASKS` | 最大並發任務數 | 整數，low 時 2，否則 3 |

### 防反爬

| 變數 | 用途 | 格式 / 預設 |
|------|------|-------------|
| `ANTI_SCRAPING_ENABLED` | 是否啟用防反爬 | `True`/`False`，預設 `True` |
| `ANTI_SCRAPING_ROTATE_UA` | 是否輪換 User-Agent | `True`/`False`，預設 `True` |
| `ANTI_SCRAPING_RANDOM_DELAY` | 是否隨機延遲 | `True`/`False`，預設 `True` |
| `ANTI_SCRAPING_STEALTH_MODE` | 是否隱身模式 | `True`/`False`，預設 `True` |
| `ANTI_SCRAPING_MIN_DELAY` | 隨機延遲下限（秒） | 浮點數，預設 `1.0` |
| `ANTI_SCRAPING_MAX_DELAY` | 隨機延遲上限（秒） | 浮點數，預設 `5.0` |
| `ANTI_SCRAPING_UA_ROTATION_MIN` | UA 輪換間隔（請求數） | 整數，預設 `10` |
| `ANTI_SCRAPING_UA_ROTATION_MAX` | UA 輪換間隔（請求數） | 整數，預設 `30` |

### Flask

| 變數 | 用途 | 格式 / 預設 |
|------|------|-------------|
| `FLASK_HOST` | 綁定位址 | 預設 `127.0.0.1` |
| `FLASK_PORT` | 監聽埠 | 整數，預設 `5001`（Docker 常用 5000） |
| `FLASK_DEBUG` | 除錯模式 | `True`/`False`，預設 `False` |

### 平台與飛書 Bitable

| 變數 | 用途 | 格式 / 預設 |
|------|------|-------------|
| `ALLOWED_PLATFORMS` | 允許爬取的平台（逗號分隔） | 例如 `juejin,csdn,cnblog`；留空為預設全開 |
| `FEISHU_APP_ID` | 飛書應用 ID | 字串 |
| `FEISHU_APP_SECRET` | 飛書應用密鑰 | 字串 |
| `FEISHU_BITABLE_APP_TOKEN` | Bitable 應用 token | 字串 |
| `FEISHU_BITABLE_TABLE_ID` | Bitable 表格 ID | 字串 |
| `FEISHU_BITABLE_FIELD_URL` | Bitable 欄位：發布連結 | 預設 `发布链接` |
| `FEISHU_BITABLE_FIELD_TOTAL_READ` | Bitable 欄位：總閱讀量 | 預設 `总阅读量` |
| `FEISHU_BITABLE_FIELD_READ_24H` | Bitable 欄位：24 小時閱讀量 | 預設 `24小时阅读量` |
| `FEISHU_BITABLE_FIELD_READ_72H` | Bitable 欄位：72 小時閱讀量 | 預設 `72小时总阅读量` |
| `FEISHU_BITABLE_FIELD_ERROR` | Bitable 欄位：失敗原因 | 預設 `失败原因` |
| `FEISHU_BITABLE_ERROR_MESSAGE_MAX_LEN` | 寫入 Bitable 的錯誤訊息最大長度（100–500） | 整數，預設 `200` |

---

## 開發流程

1. **分支**  
   建立功能/修復分支（例如 `feat/bitable-sync`、`fix/export-bom`）。

2. **TDD**  
   - RED：先寫失敗的測試  
   - GREEN：最小實作通過  
   - REFACTOR：整理、抽取輔助函式  

3. **品質**  
   - 函式 &lt; 50 行、檔案 &lt; 800 行  
   - 偏好不可變資料；對外輸入皆需驗證  
   - 不提交硬編碼密鑰與除錯用 print  

4. **提交前**  
   - `python -m pytest --cov=monitor -q`  
   - `python -m compileall monitor`  
   - 確認無 CRITICAL/HIGH 的資安或程式審查問題  

---

## 測試

- **執行全部測試（在 `article-monitor/` 下）**
  ```bash
  python -m pytest tests/ -q
  ```

- **含覆蓋率且 80% 門檻**
  ```bash
  python -m pytest --cov=monitor --cov-report=term-missing --cov-fail-under=80 -q
  ```
  設定見 `.coveragerc`（來源 `monitor`，排除 `tests/`、`extractors.py`、`anti_scraping.py`）。

- **HTML 覆蓋率報告**
  ```bash
  python -m pytest --cov=monitor --cov-report=html -q
  ```
  開啟 `htmlcov/index.html`。

- **單一檔案**
  ```bash
  python -m pytest tests/test_app_routes.py -v
  ```

目標：核心模組（如 `crawler`、`article_service`、`url_utils`）覆蓋率 ≥ 80%；extractors/anti_scraping 因瀏覽器/UA 複雜度可排除。

---

## Pull Request

- 說明變更內容與原因；註明測試指令及對 API/DB/爬蟲行為的影響。
- 合併前：測試通過、無硬編碼密鑰、覆蓋率可接受。
