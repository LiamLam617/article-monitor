"""
Flask应用 - 简单的RESTful API和前端
"""
from flask import Flask, render_template, request, jsonify, Response, send_file
from flask_cors import CORS
import asyncio
import csv
import io
import time
from datetime import datetime
from typing import List, Optional
from .database import (
    init_db, add_article, get_all_articles, get_all_articles_with_latest_count,
    get_read_counts, delete_article, get_latest_read_count, get_setting, set_setting,
    add_read_count, get_platform_health, get_platform_failures, get_all_failures,
    get_failure_stats, add_articles_batch, add_read_counts_batch
)
import logging

logger = logging.getLogger(__name__)
from .scheduler import start_scheduler
from .config import (
    FLASK_HOST, FLASK_PORT, FLASK_DEBUG, SUPPORTED_SITES, CRAWL_INTERVAL_HOURS,
    is_platform_allowed,
)

# Rate limit: min seconds between POST /api/bitable/sync calls (global)
BITABLE_SYNC_RATE_LIMIT_SECONDS = 60
_last_bitable_sync_time = 0.0
from .url_utils import normalize_url, validate_and_normalize_url
from .article_service import _process_urls_async, _process_urls_sync
from .export_service import export_selected_articles_csv, export_all_articles_csv
from .health_service import get_system_health_payload

app = Flask(__name__)
CORS(app)

# 初始化数据库
init_db()

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    """处理 favicon 请求，避免 404 错误"""
    return Response(status=204)  # 204 No Content

@app.route('/api/articles', methods=['GET'])
def get_articles():
    """获取所有文章（优化：使用批量查询避免N+1问题）"""
    articles = get_all_articles_with_latest_count()
    return jsonify({'success': True, 'data': articles})

@app.route('/api/articles/batch', methods=['POST'])
def create_articles_batch():
    """批量添加文章（优化：使用异步任务队列，立即返回任务ID）"""
    data = request.json
    urls = data.get('urls', [])
    
    if not urls:
        return jsonify({'success': False, 'error': 'URL列表不能为空'}), 400
    
    # 去重、過濾空值、規範化 URL
    urls = list(set([normalize_url(u.strip()) for u in urls if u.strip()]))
    
    if not urls:
        return jsonify({'success': False, 'error': '有效URL不能为空'}), 400
        
    # 如果URL数量较少（<=5），直接处理；否则使用异步任务
    if len(urls) <= 5:
        # 小批量：直接处理
        try:
            results = asyncio.run(_process_urls_sync(urls))
            return jsonify({'success': True, 'results': results})
        except ValueError as e:
            logger.warning(f"批量添加文章參數錯誤: {e}")
            return jsonify({'success': False, 'error': f'參數錯誤: {str(e)}'}), 400
        except Exception as e:
            logger.error(f"批量添加文章失敗: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    else:
        # 大批量：使用异步任务队列
        from .task_manager import get_task_manager
        task_manager = get_task_manager()
        task_id = task_manager.submit_task(_process_urls_async, urls)
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': f'已提交 {len(urls)} 个URL，正在后台处理',
            'status_url': f'/api/tasks/{task_id}'
        })

async def _process_urls_async(task_id: str, urls: List[str]):
    """異步處理 URL 列表（委派給 article_service）"""
    from .article_service import _process_urls_async as svc_async
    await svc_async(task_id, urls)


async def _process_urls_sync(urls: List[str]):
    """同步處理 URL 列表（委派給 article_service）"""
    from .article_service import _process_urls_sync as svc_sync
    return await svc_sync(urls)

@app.route('/api/articles', methods=['POST'])
def create_article():
    """添加文章"""
    data = request.json
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': 'URL不能为空'}), 400
    
    # 验证并规范化URL，检测平台
    is_valid, normalized_url, site = validate_and_normalize_url(url)
    if not is_valid:
        return jsonify({'success': False, 'error': '无效的URL格式（只支持 http/https）'}), 400
    
    # 检查平台是否在白名单中
    if not is_platform_allowed(site):
        return jsonify({
            'success': False,
            'error': f'平台 "{site or "未知"}" 不在允许列表中，已跳过'
        }), 400
    
    # 立即爬取一次获取标题和阅读数（使用统一的提取函数）
    title = None
    count = None
    try:
        from .extractors import extract_article_info, create_shared_crawler
        
        async def fetch_title_and_count():
            crawler = await create_shared_crawler()
            try:
                info = await extract_article_info(normalized_url, crawler)
                return info.get('title'), info.get('read_count')
            finally:
                await crawler.__aexit__(None, None, None)
        
        title, count = asyncio.run(fetch_title_and_count())
    except Exception as e:
        logger.warning(f"初次爬取失败 {normalized_url}: {e}")
        count = None
        title = None
    
    try:
        article_id = add_article(normalized_url, title=title, site=site)
        
        # 立即保存初始阅读数（如果爬取失败则为0）
        initial_count = count if count is not None else 0
        add_read_count(article_id, initial_count)
        
        return jsonify({
            'success': True,
            'data': {'id': article_id, 'url': normalized_url, 'title': title, 'site': site, 'initial_count': initial_count}
        })
    except ValueError as e:
        logger.warning(f"添加文章參數錯誤: {e}")
        return jsonify({'success': False, 'error': f'參數錯誤: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"添加文章失敗: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/articles/<int:article_id>', methods=['DELETE'])
def remove_article(article_id):
    """删除文章"""
    try:
        delete_article(article_id)
        return jsonify({'success': True})
    except ValueError as e:
        logger.warning(f"刪除文章參數錯誤: {e}")
        return jsonify({'success': False, 'error': f'參數錯誤: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"刪除文章失敗: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/articles/<int:article_id>/history', methods=['GET'])
def get_history(article_id):
    """获取阅读数历史"""
    try:
        limit = request.args.get('limit', 100, type=int)
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        group_by_hour = request.args.get('group_by_hour', 'false').lower() == 'true'
        
        history = get_read_counts(article_id, limit=limit, start_date=start_date, end_date=end_date, group_by_hour=group_by_hour)
        
        # 获取文章信息（优化：直接查询单篇文章，避免获取所有文章）
        from .database import get_article_by_id
        article = get_article_by_id(article_id)
        
        if not article:
            return jsonify({'success': False, 'error': '文章不存在'}), 404
        
        # 如果指定了日期范围但数据为空，检查是否有任何历史数据
        # 如果没有指定日期范围，或者有数据，直接返回
        # 如果指定了日期范围但数据为空，也返回空数组（前端会处理）
        
        return jsonify({
            'success': True,
            'data': history,  # 可能为空数组，前端会处理
            'title': article.get('title', ''),
            'url': article.get('url', ''),
            'site': article.get('site', '')
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/crawl', methods=['POST'])
def manual_crawl():
    """手动触发爬取"""
    try:
        from .crawler import crawl_all_sync
        # 在后台执行
        import threading
        thread = threading.Thread(target=crawl_all_sync)
        thread.start()
        return jsonify({'success': True, 'message': '爬取任务已启动'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/crawl/stop', methods=['POST'])
def stop_crawl():
    """停止爬取"""
    try:
        from .crawler import stop_crawling
        stop_crawling()
        return jsonify({'success': True, 'message': '正在停止爬取...'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """获取设置"""
    try:
        interval_hours = get_setting('crawl_interval_hours', str(CRAWL_INTERVAL_HOURS))
        # 确保返回整数
        try:
            interval_hours = int(interval_hours)
        except (ValueError, TypeError):
            interval_hours = CRAWL_INTERVAL_HOURS
        
        return jsonify({
            'success': True,
            'data': {
                'crawl_interval_hours': interval_hours
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """更新设置"""
    try:
        data = request.json
        interval_hours = data.get('crawl_interval_hours')
        
        if interval_hours is None:
            return jsonify({'success': False, 'error': '缺少 crawl_interval_hours 参数'}), 400
        
        try:
            interval_hours = int(interval_hours)
            if interval_hours < 1:
                return jsonify({'success': False, 'error': '爬取间隔必须大于0'}), 400
        except ValueError:
            return jsonify({'success': False, 'error': '爬取间隔必须是数字'}), 400
        
        set_setting('crawl_interval_hours', interval_hours)
        
        # 更新定时任务
        from .scheduler import update_schedule
        update_schedule()
        
        return jsonify({
            'success': True,
            'message': '设置已更新'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/statistics', methods=['GET'])
def get_statistics():
    """获取统计数据 - 返回日期或小时范围"""
    try:
        from datetime import datetime, timedelta

        # 支持 days 参数（兼容旧版本）或 start_date/end_date
        days = request.args.get('days', type=int)
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        group_by_hour = request.args.get('group_by_hour', 'false').lower() == 'true'

        # 如果没有指定日期范围，默认7天
        if not days and not (start_date and end_date):
            days = 7

        # 生成时间序列
        date_list = []
        
        # 如果是按小时分组（今天视图）
        if group_by_hour and start_date and start_date == end_date:
            # 生成今天的24小时时间点
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            for hour in range(24):
                time_point = start_dt + timedelta(hours=hour)
                date_list.append(time_point.strftime('%Y-%m-%d %H:00:00'))
        elif start_date and end_date:
            # 使用自定义日期范围
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            current = start_dt
            while current <= end_dt:
                date_list.append(current.strftime('%Y-%m-%d'))
                current += timedelta(days=1)
            days = len(date_list)
        else:
            # 使用days参数
            for i in range(days):
                date = (datetime.now() - timedelta(days=days-1-i)).strftime('%Y-%m-%d')
                date_list.append(date)

        return jsonify({
            'success': True,
            'data': {
                'dates': date_list,
                'date_range': {
                    'start': date_list[0] if date_list else '',
                    'end': date_list[-1] if date_list else ''
                },
                'group_by_hour': group_by_hour
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/crawl/progress', methods=['GET'])
def get_crawl_progress():
    """获取爬取进度"""
    try:
        from .crawler import get_crawl_progress
        progress = get_crawl_progress()
        return jsonify({'success': True, 'data': progress})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """获取任务状态"""
    try:
        from .task_manager import get_task_manager
        task_manager = get_task_manager()
        task = task_manager.get_task(task_id)
        if task:
            return jsonify({'success': True, 'data': task})
        else:
            return jsonify({'success': False, 'error': '任务不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def cancel_task(task_id):
    """取消任务"""
    try:
        from .task_manager import get_task_manager
        task_manager = get_task_manager()
        if task_manager.cancel_task(task_id):
            return jsonify({'success': True, 'message': '任务已取消'})
        else:
            return jsonify({'success': False, 'error': '无法取消任务'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/failures', methods=['GET'])
def get_failures():
    """获取失败列表"""
    try:
        limit = request.args.get('limit', 100, type=int)
        site = request.args.get('site', None)
        
        failures = get_all_failures(limit=limit, site=site)
        stats = get_failure_stats()
        
        return jsonify({
            'success': True,
            'data': {
                'failures': failures,
                'stats': stats
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/failures/retry/<int:article_id>', methods=['POST'])
def retry_failure(article_id):
    """重试失败的文章"""
    try:
        from .crawler import crawl_all_sync
        from .database import get_article_by_id
        
        # 检查文章是否存在
        article = get_article_by_id(article_id)
        if not article:
            return jsonify({'success': False, 'error': '文章不存在'}), 404
        
        # 在后台执行爬取
        import threading
        thread = threading.Thread(target=lambda: crawl_all_sync())
        thread.start()
        
        return jsonify({
            'success': True,
            'message': '已加入爬取队列，请稍后查看结果'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/export/csv', methods=['POST'])
def export_csv():
    """导出数据为CSV格式"""
    try:
        data = request.json
        article_ids = data.get('article_ids', [])
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not article_ids:
            return jsonify({'success': False, 'error': '请选择要导出的文章'}), 400

        content, filename = export_selected_articles_csv(article_ids, start_date, end_date)

        return Response(
            content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename={filename}',
                'Content-Type': 'text/csv; charset=utf-8-sig'
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/export/all-csv', methods=['GET'])
def export_all_csv():
    """导出所有文章数据为CSV"""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        content, filename = export_all_articles_csv(start_date, end_date)

        return Response(
            content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename={filename}',
                'Content-Type': 'text/csv; charset=utf-8-sig'
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bitable/sync', methods=['POST'])
def bitable_sync():
    """从飞书 Bitable 拉取发布链接 → 爬取 → 写回总阅读量/失败原因。"""
    global _last_bitable_sync_time
    try:
        now = time.time()
        if now - _last_bitable_sync_time < BITABLE_SYNC_RATE_LIMIT_SECONDS:
            return jsonify({
                'success': False,
                'error': '请求过于频繁，请稍后再试',
            }), 429
        _last_bitable_sync_time = now

        data = request.json or {}
        app_token = (data.get('app_token') or '').strip()
        table_id = (data.get('table_id') or '').strip()
        field_url = data.get('field_url')
        field_total_read = data.get('field_total_read')
        field_read_24h = data.get('field_read_24h')
        field_read_72h = data.get('field_read_72h')
        field_error = data.get('field_error')

        result = None
        try:
            from .bitable_sync import sync_from_bitable
            result = sync_from_bitable(
                app_token=app_token or None,
                table_id=table_id or None,
                field_url=field_url,
                field_total_read=field_total_read,
                field_read_24h=field_read_24h,
                field_read_72h=field_read_72h,
                field_error=field_error,
            )
        except Exception as e:
            logger.exception("Bitable 同步异常")
            return jsonify({
                'success': False,
                'error': '同步处理失败，请稍后重试',
                'processed': 0,
                'updated': 0,
                'failed': 0,
                'errors': [],
            }), 500

        if not result.get('success') and result.get('message'):
            return jsonify({
                'success': False,
                'error': result.get('message'),
                'processed': result.get('processed', 0),
                'updated': result.get('updated', 0),
                'failed': result.get('failed', 0),
                'errors': result.get('errors', []),
            }), 400

        return jsonify({
            'success': True,
            'data': {
                'processed': result.get('processed', 0),
                'updated': result.get('updated', 0),
                'failed': result.get('failed', 0),
                'errors': result.get('errors', []),
            }
        })
    except Exception as e:
        logger.exception("Bitable sync 请求处理异常")
        return jsonify({'success': False, 'error': '服务器内部错误，请稍后重试'}), 500


@app.route('/api/monitor/health', methods=['GET'])
def get_system_health():
    """获取系统健康状态"""
    try:
        payload = get_system_health_payload()

        return jsonify({
            'success': True,
            'data': payload
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # 启动定时任务
    start_scheduler()
    
    # 启动Flask
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)

