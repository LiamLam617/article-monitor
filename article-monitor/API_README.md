# Article Monitor API 文檔

**版本**: 1.0  
**基礎 URL**: `http://your-server:5000`  
**格式**: JSON

---

## 📋 目錄

- [概述](#概述)
- [認證](#認證)
- [通用響應格式](#通用響應格式)
- [錯誤處理](#錯誤處理)
- [API 端點](#api-端點)
  - [文章管理](#文章管理)
  - [爬取控制](#爬取控制)
  - [設置管理](#設置管理)
  - [統計數據](#統計數據)
  - [任務管理](#任務管理)
  - [失敗管理](#失敗管理)
  - [數據導出](#數據導出)
  - [系統監控](#系統監控)

---

## 概述

Article Monitor API 提供了一套完整的 RESTful API，用於管理文章監控、爬取任務、數據統計等功能。

### 支持的平台

- **掘金** (juejin.cn)
- **CSDN** (csdn.net)
- **博客園** (cnblogs.com)
- **51CTO** (51cto.com)
- **SegmentFault** (segmentfault.com)
- **簡書** (jianshu.com)
- **面包板** (china.com)
- **電子發燒友** (elecfans.com)
- **與非網** (eefocus.com)
- **搜狐** (sohu.com)

---

## 認證

目前 API 無需認證，但建議在生產環境中配置認證機制。

---

## 通用響應格式

### 成功響應

```json
{
  "success": true,
  "data": { ... }
}
```

### 錯誤響應

```json
{
  "success": false,
  "error": "錯誤信息"
}
```

---

## 錯誤處理

### HTTP 狀態碼

- `200 OK` - 請求成功
- `400 Bad Request` - 請求參數錯誤
- `404 Not Found` - 資源不存在
- `500 Internal Server Error` - 服務器內部錯誤

### 錯誤響應示例

```json
{
  "success": false,
  "error": "URL不能為空"
}
```

---

## API 端點

## 文章管理

### 1. 獲取所有文章

**端點**: `GET /api/articles`

**描述**: 獲取所有監控的文章列表，包含最新閱讀數

**請求參數**: 無

**響應示例**:

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "url": "https://juejin.cn/post/123456",
      "title": "文章標題",
      "site": "juejin",
      "created_at": "2025-12-01 10:00:00",
      "latest_count": 1234,
      "latest_timestamp": "2025-12-09 14:30:00"
    }
  ]
}
```

---

### 2. 添加單篇文章

**端點**: `POST /api/articles`

**描述**: 添加一篇文章到監控列表

**請求體**:

```json
{
  "url": "https://juejin.cn/post/123456"
}
```

**響應示例**:

```json
{
  "success": true,
  "data": {
    "id": 1,
    "url": "https://juejin.cn/post/123456",
    "title": "文章標題",
    "site": "juejin",
    "initial_count": 1234
  }
}
```

**錯誤響應**:

```json
{
  "success": false,
  "error": "無效的URL格式（只支持 http/https）"
}
```

---

### 3. 批量添加文章

**端點**: `POST /api/articles/batch`

**描述**: 批量添加文章。如果 URL 數量 ≤ 5，立即返回結果；否則返回任務 ID，需要通過任務 API 查詢進度。

**請求體**:

```json
{
  "urls": [
    "https://juejin.cn/post/123456",
    "https://csdn.net/article/789012"
  ]
}
```

**小批量響應** (≤5 個 URL):

```json
{
  "success": true,
  "results": [
    {
      "url": "https://juejin.cn/post/123456",
      "success": true,
      "data": {
        "id": 1,
        "title": "文章標題",
        "site": "juejin",
        "initial_count": 1234
      }
    }
  ]
}
```

**大批量響應** (>5 個 URL):

```json
{
  "success": true,
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "已提交 10 個URL，正在後台處理",
  "status_url": "/api/tasks/550e8400-e29b-41d4-a716-446655440000"
}
```

---

### 4. 刪除文章

**端點**: `DELETE /api/articles/<article_id>`

**描述**: 刪除指定文章及其所有閱讀數記錄

**路徑參數**:
- `article_id` (integer) - 文章 ID

**響應示例**:

```json
{
  "success": true
}
```

---

### 5. 獲取文章閱讀數歷史

**端點**: `GET /api/articles/<article_id>/history`

**描述**: 獲取指定文章的閱讀數歷史記錄

**路徑參數**:
- `article_id` (integer) - 文章 ID

**查詢參數**:
- `limit` (integer, 可選) - 返回記錄數限制，默認 100
- `start_date` (string, 可選) - 開始日期，格式: `YYYY-MM-DD`
- `end_date` (string, 可選) - 結束日期，格式: `YYYY-MM-DD`
- `group_by_hour` (boolean, 可選) - 是否按小時分組，默認 `false`

**請求示例**:

```
GET /api/articles/1/history?start_date=2025-12-01&end_date=2025-12-09&group_by_hour=true
```

**響應示例**:

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "article_id": 1,
      "count": 1234,
      "timestamp": "2025-12-09 14:30:00"
    }
  ],
  "title": "文章標題",
  "url": "https://juejin.cn/post/123456",
  "site": "juejin"
}
```

---

## 爬取控制

### 6. 手動觸發爬取

**端點**: `POST /api/crawl`

**描述**: 手動觸發一次全量爬取任務

**請求體**: 無

**響應示例**:

```json
{
  "success": true,
  "message": "爬取任務已啟動"
}
```

---

### 7. 停止爬取

**端點**: `POST /api/crawl/stop`

**描述**: 停止正在進行的爬取任務

**請求體**: 無

**響應示例**:

```json
{
  "success": true,
  "message": "正在停止爬取..."
}
```

---

### 8. 獲取爬取進度

**端點**: `GET /api/crawl/progress`

**描述**: 獲取當前爬取任務的進度信息

**響應示例**:

```json
{
  "success": true,
  "data": {
    "is_running": true,
    "total": 100,
    "current": 45,
    "success": 40,
    "failed": 5,
    "retried": 3,
    "current_url": "https://juejin.cn/post/123456",
    "start_time": "2025-12-09T14:00:00",
    "end_time": null
  }
}
```

---

## 設置管理

### 9. 獲取設置

**端點**: `GET /api/settings`

**描述**: 獲取當前系統設置

**響應示例**:

```json
{
  "success": true,
  "data": {
    "crawl_interval_hours": 6
  }
}
```

---

### 10. 更新設置

**端點**: `POST /api/settings`

**描述**: 更新系統設置

**請求體**:

```json
{
  "crawl_interval_hours": 6
}
```

**響應示例**:

```json
{
  "success": true,
  "message": "設置已更新"
}
```

**錯誤響應**:

```json
{
  "success": false,
  "error": "爬取間隔必須大於0"
}
```

---

## 統計數據

### 11. 獲取統計數據

**端點**: `GET /api/statistics`

**描述**: 獲取日期範圍統計數據，用於生成圖表

**查詢參數**:
- `days` (integer, 可選) - 天數，默認 7
- `start_date` (string, 可選) - 開始日期，格式: `YYYY-MM-DD`
- `end_date` (string, 可選) - 結束日期，格式: `YYYY-MM-DD`
- `group_by_hour` (boolean, 可選) - 是否按小時分組，默認 `false`

**請求示例**:

```
GET /api/statistics?start_date=2025-12-01&end_date=2025-12-09&group_by_hour=false
```

**響應示例**:

```json
{
  "success": true,
  "data": {
    "dates": [
      "2025-12-01",
      "2025-12-02",
      "2025-12-03"
    ],
    "date_range": {
      "start": "2025-12-01",
      "end": "2025-12-03"
    },
    "group_by_hour": false
  }
}
```

---

## 任務管理

### 12. 獲取任務狀態

**端點**: `GET /api/tasks/<task_id>`

**描述**: 獲取異步任務的狀態和進度

**路徑參數**:
- `task_id` (string) - 任務 ID

**響應示例**:

```json
{
  "success": true,
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "running",
    "start_time": "2025-12-09T14:00:00",
    "end_time": null,
    "progress": {
      "processed": 5,
      "total": 10,
      "success": 4,
      "failed": 1
    },
    "error": null
  }
}
```

**任務狀態**:
- `pending` - 等待中
- `running` - 運行中
- `completed` - 已完成
- `failed` - 失敗
- `cancelled` - 已取消

---

### 13. 取消任務

**端點**: `DELETE /api/tasks/<task_id>`

**描述**: 取消指定的異步任務

**路徑參數**:
- `task_id` (string) - 任務 ID

**響應示例**:

```json
{
  "success": true,
  "message": "任務已取消"
}
```

---

## 失敗管理

### 14. 獲取失敗列表

**端點**: `GET /api/failures`

**描述**: 獲取爬取失敗的文章列表

**查詢參數**:
- `limit` (integer, 可選) - 返回記錄數限制，默認 100
- `site` (string, 可選) - 按平台過濾

**請求示例**:

```
GET /api/failures?limit=50&site=juejin
```

**響應示例**:

```json
{
  "success": true,
  "data": {
    "failures": [
      {
        "id": 1,
        "url": "https://juejin.cn/post/123456",
        "title": "文章標題",
        "site": "juejin",
        "last_error": "Timeout 30000ms exceeded",
        "last_crawl_time": "2025-12-09 14:00:00"
      }
    ],
    "stats": {
      "total": 10,
      "by_site": {
        "juejin": 5,
        "csdn": 3,
        "cnblog": 2
      }
    }
  }
}
```

---

### 15. 重試失敗的文章

**端點**: `POST /api/failures/retry/<article_id>`

**描述**: 將失敗的文章重新加入爬取隊列

**路徑參數**:
- `article_id` (integer) - 文章 ID

**響應示例**:

```json
{
  "success": true,
  "message": "已加入爬取隊列，請稍後查看結果"
}
```

---

## 數據導出

### 16. 導出選定文章為 CSV

**端點**: `POST /api/export/csv`

**描述**: 導出指定文章的閱讀數數據為 CSV 格式

**請求體**:

```json
{
  "article_ids": [1, 2, 3],
  "start_date": "2025-12-01",
  "end_date": "2025-12-09"
}
```

**請求參數**:
- `article_ids` (array, 必需) - 文章 ID 列表
- `start_date` (string, 可選) - 開始日期
- `end_date` (string, 可選) - 結束日期

**響應**: CSV 文件下載

**文件格式**:
```csv
文章標題,網站,URL,閱讀數,記錄時間
文章1,juejin,https://...,1234,2025-12-09 14:30:00
```

---

### 17. 導出所有文章為 CSV

**端點**: `GET /api/export/all-csv`

**描述**: 導出所有文章的閱讀數數據為 CSV 格式

**查詢參數**:
- `start_date` (string, 可選) - 開始日期
- `end_date` (string, 可選) - 結束日期

**請求示例**:

```
GET /api/export/all-csv?start_date=2025-12-01&end_date=2025-12-09
```

**響應**: CSV 文件下載

---

## 系統監控

### 18. 獲取系統健康狀態

**端點**: `GET /api/monitor/health`

**描述**: 獲取系統資源使用情況、平台健康度和網絡連通性

**響應示例**:

```json
{
  "success": true,
  "data": {
    "system": {
      "cpu": {
        "percent": 25.5,
        "count": 4
      },
      "memory": {
        "total": 8589934592,
        "available": 4294967296,
        "percent": 50.0
      },
      "disk": {
        "total": 107374182400,
        "free": 53687091200,
        "percent": 50.0
      }
    },
    "platforms": [
      {
        "site": "juejin",
        "status": "ok",
        "message": "正常",
        "last_update": "2025-12-09 14:30:00",
        "article_count": 50,
        "failures": []
      }
    ],
    "network": [
      {
        "name": "互聯網連通性",
        "host": "www.baidu.com",
        "status": {
          "ok": true,
          "latency": 25
        }
      }
    ],
    "timestamp": "2025-12-09 15:00:00"
  }
}
```

**平台狀態說明**:
- `ok` - 正常
- `warning` - 警告（有失敗記錄或輕微延遲）
- `error` - 錯誤（嚴重延遲）
- `unknown` - 未知（無數據）

---

## 使用示例

### cURL 示例

#### 添加文章

```bash
curl -X POST http://localhost:5000/api/articles \
  -H "Content-Type: application/json" \
  -d '{"url": "https://juejin.cn/post/123456"}'
```

#### 獲取所有文章

```bash
curl http://localhost:5000/api/articles
```

#### 獲取閱讀數歷史

```bash
curl "http://localhost:5000/api/articles/1/history?start_date=2025-12-01&end_date=2025-12-09"
```

#### 手動觸發爬取

```bash
curl -X POST http://localhost:5000/api/crawl
```

#### 獲取爬取進度

```bash
curl http://localhost:5000/api/crawl/progress
```

---

### JavaScript 示例

#### 添加文章

```javascript
fetch('http://localhost:5000/api/articles', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    url: 'https://juejin.cn/post/123456'
  })
})
.then(response => response.json())
.then(data => console.log(data));
```

#### 批量添加文章

```javascript
fetch('http://localhost:5000/api/articles/batch', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    urls: [
      'https://juejin.cn/post/123456',
      'https://csdn.net/article/789012'
    ]
  })
})
.then(response => response.json())
.then(data => {
  if (data.task_id) {
    // 大批量，需要查詢任務狀態
    console.log('任務ID:', data.task_id);
    // 輪詢任務狀態
    pollTaskStatus(data.task_id);
  } else {
    // 小批量，直接返回結果
    console.log('結果:', data.results);
  }
});
```

#### 查詢任務狀態

```javascript
function pollTaskStatus(taskId) {
  const interval = setInterval(() => {
    fetch(`http://localhost:5000/api/tasks/${taskId}`)
      .then(response => response.json())
      .then(data => {
        console.log('任務狀態:', data.data.status);
        if (data.data.status === 'completed' || data.data.status === 'failed') {
          clearInterval(interval);
          if (data.data.results) {
            console.log('結果:', data.data.results);
          }
        }
      });
  }, 2000); // 每2秒查詢一次
}
```

---

### Python 示例

```python
import requests

# 添加文章
response = requests.post('http://localhost:5000/api/articles', json={
    'url': 'https://juejin.cn/post/123456'
})
print(response.json())

# 獲取所有文章
response = requests.get('http://localhost:5000/api/articles')
articles = response.json()['data']
print(f'共有 {len(articles)} 篇文章')

# 獲取閱讀數歷史
response = requests.get('http://localhost:5000/api/articles/1/history', params={
    'start_date': '2025-12-01',
    'end_date': '2025-12-09'
})
history = response.json()['data']
print(f'共有 {len(history)} 條記錄')
```

---

## 注意事項

1. **URL 格式**: 只支持 `http://` 和 `https://` 協議
2. **平台白名單**: 可以通過環境變量 `ALLOWED_PLATFORMS` 配置允許的平台
3. **批量添加**: 超過 5 個 URL 會使用異步任務，需要通過任務 API 查詢進度
4. **日期格式**: 所有日期參數使用 `YYYY-MM-DD` 格式
5. **時區**: 系統使用 `Asia/Shanghai` 時區

---

## 更新日誌

### v1.0 (2025-12-09)
- 初始版本
- 支持文章管理、爬取控制、數據導出等功能
- 支持批量添加和異步任務
- 支持系統健康監控

---

**文檔最後更新**: 2025-12-09

