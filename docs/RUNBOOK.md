 # Article Monitor Runbook

本 RUNBOOK 說明如何部署、監控與維運 Article Monitor 系統，以及常見問題與回滾流程。

## 系統概要

- 架構：單體 Flask 應用 + SQLite 資料庫
- 服務啟動入口：
  - 推薦：在 `article-monitor/` 目錄執行 `python run_monitor.py`
  - 傳統：在 `article-monitor/monitor/` 目錄執行 `python app.py`
- 資料庫位置：`monitor/../data/monitor.db`
- 主要功能：
  - 文章監控（新增、刪除、查看歷史）
  - 週期性爬取閱讀數
  - 失敗重試與錯誤分類
  - CSV 導出
  - 系統健康檢查 API

## 部署流程

以下以單機或簡單伺服器部署為例：

1. **準備環境**
   - 安裝 Python 3.11+
   - 建立專用系統帳號（非必要但建議）
2. **部署程式碼**
   - `git clone` 至目標路徑，例如 `/opt/article-monitor`
3. **建立虛擬環境與安裝依賴**
   ```bash
   cd article-monitor
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   # Windows 可使用 .venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. **設定環境變數**
   - 建議使用 systemd service、docker-compose 或 shell 啟動腳本設定環境變數：
     - `FLASK_HOST`、`FLASK_PORT`
     - `CRAWL_INTERVAL_HOURS` 等爬蟲設定
     - `ALLOWED_PLATFORMS` 控制允許的平台
     - 防反爬相關變數（見 `monitor/config.py`）
5. **啟動服務**
   - 直接啟動（開發 / 單機）：
     ```bash
     cd article-monitor
     python run_monitor.py
     ```
   - 建議以 process manager 管理（systemd / supervisor / docker 等）。

## 監控與健康檢查

### HTTP 健康檢查

- 健康檢查端點：`GET /api/monitor/health`
- 回傳內容包含：
  - 系統資源（CPU、記憶體、磁碟）
  - 各平台健康狀態
  - 網路連通性檢查

可在監控系統中定期呼叫此端點（例如每 1 分鐘），並根據：

- HTTP 狀態碼（200 / 5xx）
- JSON 中 `success` 欄位
- CPU / 記憶體 / 磁碟使用率閾值

來設定告警規則。

### 爬蟲進度與失敗監控

- 爬取進度：`GET /api/crawl/progress`
- 失敗列表：`GET /api/failures`
- 失敗重試：`POST /api/failures/retry/<article_id>`

建議：

- 監控失敗總數與按平台統計
- 對異常高失敗率的平台發出告警

## 常見操作

### 手動觸發爬取

- `POST /api/crawl`
- 用於立即觸發一次全量爬取，適合在部署後或調整設定後驗證。

### 停止爬取

- `POST /api/crawl/stop`
- 當爬蟲異常或需要緊急停止時使用。

### 查詢統計與歷史

- 文章列表與最新閱讀數：`GET /api/articles`
- 單篇文章歷史：`GET /api/articles/<id>/history`
- 匯總統計：`GET /api/statistics`

## 常見問題與排除

### 問題：服務啟不來 / 連不上

- 檢查：
  - Python 版本是否符合要求
  - `pip install -r requirements.txt` 是否成功
  - `FLASK_HOST` / `FLASK_PORT` 是否被防火牆或其他服務占用
  - 日誌中是否有 traceback（建議在啟動腳本中將輸出重導至檔案）

### 問題：爬取速度過慢或頻繁逾時

- 檢查並調整環境變數：
  - `CRAWL_CONCURRENCY`
  - `CRAWL_DELAY`
  - `CRAWL_TIMEOUT`
  - `CRAWL_MAX_RETRIES` / `CRAWL_RETRY_*`
- 檢查外部網站是否有更嚴格的反爬策略，必要時調整防反爬設定：
  - `ANTI_SCRAPING_ENABLED`
  - `ANTI_SCRAPING_RANDOM_DELAY`
  - `ANTI_SCRAPING_STEALTH_MODE`

### 問題：某些平台永遠失敗

- 使用：
  - `GET /api/failures` 查看錯誤訊息
  - 檢查錯誤分類（永久錯誤 / SSL / 網路 / 解析）
- 若是該平台已不再支援或結構改變：
  - 可暫時從 `ALLOWED_PLATFORMS` 中移除，避免無效重試。

### 問題：磁碟空間不足

- SQLite 檔案路徑位於 `data/monitor.db`，歷史資料可能持續成長。
- 解法：
  - 定期備份並壓縮舊資料
  - 或定期清理過舊的歷史記錄（未實作時可透過額外腳本完成）

## 回滾流程

1. **回滾程式碼**
   - 使用 git 回到前一個穩定標籤或 commit：
     ```bash
     git checkout <previous-stable-commit>
     ```
2. **回滾依賴（如有變更）**
   - 若 requirements 有變更，可重新安裝：
     ```bash
     pip install -r requirements.txt
     ```
3. **資料庫處理**
   - 通常不需要回滾 SQLite 結構。
   - 若本次發布包含 schema 變更且導致問題，建議：
     - 先備份當前 `monitor.db`
     - 如有舊版備份，可切換回舊版並記錄資料差異
4. **重啟服務並驗證**
   - 依前述啟動方式重啟服務
   - 手動驗證：
     - 文章列表是否可正常讀取
     - 手動觸發爬取是否正常
     - `/api/monitor/health` 是否回傳正常

## 發布前檢查清單

- [ ] 所有單元測試與整合測試皆通過：
  - `python -m pytest --cov=monitor -q`
- [ ] 沒有新增硬編碼秘密（token / password / API key 等）
- [ ] 關鍵模組覆蓋率合理（例如 `crawler.py`、`article_service.py`）
- [ ] `GET /api/monitor/health` 回傳正常
- [ ] 手動爬取與停止爬取 API 正常運作

如需更詳細的 API 細節與 payload 結構，請參考 `API_README.md`。

