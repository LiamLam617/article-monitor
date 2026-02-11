 # Contributing to Article Monitor

這份文檔說明本專案的開發流程、腳本與測試方式，方便你在本機開發與提交改動。

## 開發環境設定

- 建議 Python 版本：**3.11+**
- 建議步驟：
  1. 建立虛擬環境
     ```bash
     python -m venv .venv
     .venv\Scripts\activate  # Windows PowerShell
     ```
  2. 安裝依賴（在 `article-monitor/` 目錄下）
     ```bash
     pip install -r requirements.txt
     ```

後端應用程式碼位於 `monitor/` 子目錄；測試都放在 `tests/`。

## 可用腳本（Python 專案）

此專案目前 **沒有 `package.json`**，所有腳本都以 Python 命令方式執行：

| 動作                     | 指令（從 `article-monitor/` 執行）                             | 說明                              |
|--------------------------|----------------------------------------------------------------|-----------------------------------|
| 啟動 Web 服務           | `python run_monitor.py`                                       | 啟動 Flask 服務（預設 127.0.0.1） |
| 直接從模組啟動           | `cd monitor && python app.py`                                | 直接用原始 `monitor/app.py` 啟動  |
| 執行全部測試            | `cd article-monitor && python -m pytest --cov=monitor -q`     | 執行 pytest 並產生覆蓋率          |
| 指定某個測試檔          | `cd article-monitor && python -m pytest tests/test_xxx.py -q` | 只跑單一測試檔                    |

> 單一來源（Single Source of Truth）：上述指令來自 `monitor/README.md` 與實際測試流程。

## 環境變數與設定

本專案目前 **沒有 `.env.example`** 檔案，設定主要由 `monitor/config.py` 中的環境變數控制：

- 資料庫與日誌
  - `ARTICLE_MONITOR_DEBUG_LOG`：可選的 debug 日誌檔路徑
- 爬蟲行為
  - `CRAWL_INTERVAL_HOURS`：爬取週期（小時）
  - `CRAWL_TIMEOUT`：單次請求逾時秒數
  - `CRAWL_CONCURRENCY`：並發爬取數
  - `CRAWL_DELAY`：每個請求之間延遲秒數
  - `CRAWL_MAX_RETRIES` / `CRAWL_RETRY_DELAY` / `CRAWL_RETRY_BACKOFF` / `CRAWL_RETRY_MAX_DELAY` / `CRAWL_RETRY_JITTER`
  - `CRAWL_RETRY_NETWORK_MAX` / `CRAWL_RETRY_PARSE_MAX` / `CRAWL_RETRY_SSL_MAX` / `CRAWL_RETRY_SSL_DELAY`
- 防反爬
  - `ANTI_SCRAPING_ENABLED`
  - `ANTI_SCRAPING_ROTATE_UA`
  - `ANTI_SCRAPING_RANDOM_DELAY`
  - `ANTI_SCRAPING_STEALTH_MODE`
  - `ANTI_SCRAPING_MIN_DELAY` / `ANTI_SCRAPING_MAX_DELAY`
  - `ANTI_SCRAPING_UA_ROTATION_MIN` / `ANTI_SCRAPING_UA_ROTATION_MAX`
- Flask
  - `FLASK_HOST`（預設 `127.0.0.1`）
  - `FLASK_PORT`（預設 `5001`）
  - `FLASK_DEBUG`
- 平台白名單
  - `ALLOWED_PLATFORMS`：以逗號分隔的平台名稱（例如：`juejin,csdn,cnblog`）

建議在本機自行建立 `.env` 或使用系統環境變數，勿在程式碼中硬編碼任何密鑰或憑證。

## 開發流程建議

1. **建立分支**
   - 以功能為單位建立分支（例如：`feat/crawler-tests`、`fix/export-bom`）。
2. **TDD 開發**
   - 依照專案規則，先寫測試再實作：
     1. RED：撰寫失敗的測試
     2. GREEN：最小實作讓測試通過
     3. REFACTOR：重構、清理、提取共用函式
3. **執行測試與覆蓋率**
   - `python -m pytest --cov=monitor -q`
4. **程式風格與安全性**
   - 保持函式精簡（< 50 行）、檔案聚焦（< 800 行）
   - 避免可變共享狀態，偏好不可變資料結構
   - 所有外部輸入都要做驗證
5. **提交前自我檢查**
   - 測試全部通過
   - 沒有硬編碼秘密（token / password / API key 等）
   - 無多餘的 `print` / 除錯程式碼

## 測試流程

- 全部測試：
  ```bash
  cd article-monitor
  python -m pytest --cov=monitor -q
  ```

- 覆蓋率報告（含遺漏行、80% 門檻、HTML 報告）：
  ```bash
  cd article-monitor
  python -m pytest --cov=monitor --cov-report=term-missing --cov-report=html --cov-fail-under=80
  ```
  設定檔為 `article-monitor/.coveragerc`（source=monitor，fail_under=80）。  
  `monitor/extractors.py` 與 `monitor/anti_scraping.py` 因依賴真實瀏覽器或複雜 UA/stealth 邏輯，目前自覆蓋率計算中排除；其餘模組以 80% 為目標。

- 僅產生 JSON 摘要（可給工具讀取）：
  ```bash
  python -m pytest --cov=monitor --cov-report=json -q
  ```

- 只跑單一檔案：
  ```bash
  cd article-monitor
  python -m pytest tests/test_crawler.py -q
  ```

目前目標是核心模組（例如 `crawler.py`、`article_service.py`、`url_utils.py` 等）覆蓋率 **≥ 80%**，整體覆蓋率會隨重構與補測逐步提升。

## Pull Request 建議

- PR 說明建議包含：
  - 變更摘要（What / Why）
  - 測試結果與指令
  - 可能影響範圍（API 行為、資料庫結構、爬蟲策略等）
- 提交前可先在本機執行「驗證指令」：
  - 建置：`python -m compileall monitor`
  - 測試：`python -m pytest --cov=monitor -q`

