# 文章閱讀數監測系統

定時爬取多平台文章閱讀數，支援本地儲存、歷史趨勢、CSV 導出與飛書 Bitable 同步。

## 安裝

```bash
# 在 article-monitor/ 目錄下
pip install -r requirements.txt
python -m playwright install chromium
```

## 運行

```bash
# 在 article-monitor/ 目錄下
python run_monitor.py
```

或於本目錄：`python app.py`。訪問 http://127.0.0.1:5000（或依 `FLASK_PORT` 設定）。

## 功能

1. **添加文章**：輸入文章連結，自動識別網站類型  
2. **定時爬取**：每 6 小時自動爬取一次（可由環境變數 `CRAWL_INTERVAL_HOURS` 修改）  
3. **數據展示**：每篇文章最新閱讀數與歷史趨勢圖  
4. **手動爬取**：透過介面或 API 立即觸發全量爬取  

## 支援的網站

- 掘金 (juejin.cn)  
- CSDN (csdn.net)  
- 博客園 (cnblogs.com)  
- 51CTO (51cto.com)  
- 電子發燒友 (elecfans.com)  
- SegmentFault (segmentfault.com)  
- 簡書 (jianshu.com)  

## 資料儲存

使用 SQLite，檔案位置：`data/monitor.db`（相對於 `article-monitor/`）。

## 配置

- **環境變數**：複製 `article-monitor/.env.example` 為 `.env`，依需填寫；完整清單與說明見 [docs/CONTRIB.md](../../docs/CONTRIB.md#環境變數)。  
- **爬取間隔、埠、平台白名單**：由環境變數或 `config.py` 對應項控制。  

## 低資源部署（2 核 2GB）

在 2 核 CPU、2GB 記憶體環境下，建議啟用資源友善模式，避免 OOM 與 CPU 過載：

**方式一：單一開關（推薦）**

```bash
export RESOURCE_PROFILE=low
# 或
export LOW_MEMORY=1
```

**方式二：手動指定環境變數**

```bash
CRAWL_CONCURRENCY=2
BROWSER_POOL_MAX_SIZE=2
BROWSER_POOL_MIN_SIZE=1
SQLITE_CACHE_SIZE_KB=2048
MAX_HEALTH_CHECK_WORKERS=4
MAX_CONCURRENT_TASKS=2
```

未設定上述變數時，程式行為與原有一致；僅在需適應小規格主機時設定即可。

## 更多說明

- **開發與測試**：[docs/CONTRIB.md](../../docs/CONTRIB.md)  
- **部署與維運**：[docs/RUNBOOK.md](../../docs/RUNBOOK.md)  
- **API 文件**：`article-monitor/API_README.md`  
