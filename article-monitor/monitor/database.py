"""
数据库操作 - 简单的SQLite，没有ORM的废话
"""
import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional
from .config import DATABASE_PATH

# 确保数据目录存在
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

def _apply_db_optimizations(conn: sqlite3.Connection):
    """应用数据库性能优化设置（每次新连接都需要设置）"""
    # 启用 WAL 模式，提升并发读写性能（持久化，但每次连接仍需设置以确保）
    conn.execute('PRAGMA journal_mode=WAL')
    # 优化性能设置（每次连接都需要设置）
    conn.execute('PRAGMA synchronous=NORMAL')  # 平衡性能和安全性
    conn.execute('PRAGMA cache_size=-64000')  # 64MB 缓存（负值表示 KB）
    conn.execute('PRAGMA temp_store=MEMORY')  # 临时表存储在内存中
    # 其他优化
    conn.execute('PRAGMA foreign_keys=ON')  # 启用外键约束

def get_db():
    """获取数据库连接（优化：启用 WAL 模式提升并发性能）"""
    conn = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    _apply_db_optimizations(conn)
    return conn

def init_db():
    """初始化数据库 - 就三个表，简单到不能再简单"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 文章表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            title TEXT,
            site TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 阅读数记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS read_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            count INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    ''')
    
    # 设置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 索引 - 性能优化
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_article_id ON read_counts(article_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON read_counts(timestamp)')
    
    # 初始化默认设置
    from .config import CRAWL_INTERVAL_HOURS
    cursor.execute('SELECT COUNT(*) as count FROM settings WHERE key = ?', ('crawl_interval_hours',))
    if cursor.fetchone()['count'] == 0:
        cursor.execute('''
            INSERT INTO settings (key, value) VALUES (?, ?)
        ''', ('crawl_interval_hours', str(CRAWL_INTERVAL_HOURS)))
    
    # 检查并添加新字段（用于记录爬取状态）
    cursor.execute("PRAGMA table_info(articles)")
    columns = [info['name'] for info in cursor.fetchall()]
    
    if 'last_status' not in columns:
        cursor.execute('ALTER TABLE articles ADD COLUMN last_status TEXT DEFAULT "PENDING"')
    if 'last_error' not in columns:
        cursor.execute('ALTER TABLE articles ADD COLUMN last_error TEXT')
    if 'last_crawl_time' not in columns:
        cursor.execute('ALTER TABLE articles ADD COLUMN last_crawl_time TIMESTAMP')
        
    conn.commit()
    conn.close()

def update_article_status(article_id: int, status: str, error: Optional[str] = None):
    """更新文章爬取状态（优化：支持 PENDING 状态）
    
    Args:
        article_id: 文章ID
        status: 'OK'、'ERROR' 或 'PENDING'
        error: 错误信息（如果是 ERROR 或 PENDING）
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE articles 
        SET last_status = ?, last_error = ?, last_crawl_time = datetime('now', 'localtime')
        WHERE id = ?
    ''', (status, error, article_id))
    conn.commit()
    conn.close()

def get_platform_failures() -> List[Dict]:
    """获取各平台最近的失败记录（优化：包括 PENDING 状态）"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            id, title, url, site, last_error, last_crawl_time
        FROM articles 
        WHERE last_status = 'ERROR' OR (last_status = 'PENDING' AND last_error IS NOT NULL)
        ORDER BY last_crawl_time DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_all_failures(limit: int = 100, site: Optional[str] = None) -> List[Dict]:
    """获取所有失败记录（支持分页和平台筛选）
    
    Args:
        limit: 返回记录数限制
        site: 平台筛选（可选）
        
    Returns:
        失败记录列表（包括 ERROR 状态和最近爬取失败但状态未更新的文章）
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # 优化：不仅查询 ERROR 状态，还查询最近爬取失败但可能状态未及时更新的文章
    # 条件：last_status = 'ERROR' 或者 (last_status != 'OK' 且有 last_error)
    if site:
        cursor.execute('''
            SELECT 
                id, title, url, site, last_error, last_crawl_time, last_status
            FROM articles 
            WHERE (last_status = 'ERROR' OR (last_status != 'OK' AND last_error IS NOT NULL))
            AND site = ?
            ORDER BY last_crawl_time DESC, id DESC
            LIMIT ?
        ''', (site, limit))
    else:
        cursor.execute('''
            SELECT 
                id, title, url, site, last_error, last_crawl_time, last_status
            FROM articles 
            WHERE last_status = 'ERROR' OR (last_status != 'OK' AND last_error IS NOT NULL)
            ORDER BY last_crawl_time DESC, id DESC
            LIMIT ?
        ''', (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_failure_stats() -> Dict:
    """获取失败统计信息（优化：包括所有失败状态）
    
    Returns:
        包含总数、按平台分组等统计信息
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # 总失败数（包括 ERROR 状态和最近失败但状态未及时更新的）
    cursor.execute('''
        SELECT COUNT(*) as count 
        FROM articles 
        WHERE last_status = 'ERROR' OR (last_status != 'OK' AND last_error IS NOT NULL)
    ''')
    total = cursor.fetchone()['count']
    
    # 按平台分组统计
    cursor.execute('''
        SELECT 
            site, COUNT(*) as count
        FROM articles 
        WHERE last_status = 'ERROR' OR (last_status != 'OK' AND last_error IS NOT NULL)
        GROUP BY site
        ORDER BY count DESC
    ''')
    by_site = {row['site']: row['count'] for row in cursor.fetchall()}
    
    # 最近24小时失败数
    cursor.execute('''
        SELECT COUNT(*) as count
        FROM articles 
        WHERE (last_status = 'ERROR' OR (last_status != 'OK' AND last_error IS NOT NULL))
        AND last_crawl_time >= datetime('now', '-24 hours')
    ''')
    recent_24h = cursor.fetchone()['count']
    
    conn.close()
    
    return {
        'total': total,
        'by_site': by_site,
        'recent_24h': recent_24h
    }

def add_article(url: str, title: Optional[str] = None, site: Optional[str] = None) -> int:
    """添加文章，返回文章ID"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            'INSERT INTO articles (url, title, site) VALUES (?, ?, ?)',
            (url, title, site)
        )
        article_id = cursor.lastrowid
        conn.commit()
        return article_id
    except sqlite3.IntegrityError:
        # URL已存在，返回现有ID
        cursor.execute('SELECT id FROM articles WHERE url = ?', (url,))
        row = cursor.fetchone()
        return row['id'] if row else None
    finally:
        conn.close()

def get_all_articles() -> List[Dict]:
    """获取所有文章"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_all_articles_with_latest_count() -> List[Dict]:
    """获取所有文章及其最新阅读数（批量查询，避免N+1问题）"""
    conn = get_db()
    cursor = conn.cursor()
    # 使用 LEFT JOIN 和子查询一次性获取所有数据
    cursor.execute('''
        SELECT 
            a.*,
            rc.count as latest_count,
            rc.timestamp as latest_timestamp
        FROM articles a
        LEFT JOIN (
            SELECT 
                article_id,
                count,
                timestamp,
                ROW_NUMBER() OVER (PARTITION BY article_id ORDER BY timestamp DESC, id DESC) as rn
            FROM read_counts
        ) rc ON a.id = rc.article_id AND rc.rn = 1
        ORDER BY a.created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    articles = []
    for row in rows:
        article = dict(row)
        # 处理可能的 None 值
        if article.get('latest_count') is None:
            article['latest_count'] = 0
            article['latest_timestamp'] = None
        articles.append(article)
    return articles

def add_read_count(article_id: int, count: int):
    """添加阅读数记录 - 使用本地时间"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO read_counts (article_id, count, timestamp) VALUES (?, ?, datetime('now', 'localtime'))",
        (article_id, count)
    )
    conn.commit()
    conn.close()

def add_read_counts_batch(records: List[tuple]):
    """批量添加阅读数记录（优化性能，使用事务）
    
    Args:
        records: [(article_id, count), ...] 列表
    """
    if not records:
        return
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        # 使用事务批量插入
        cursor.executemany(
            "INSERT INTO read_counts (article_id, count, timestamp) VALUES (?, ?, datetime('now', 'localtime'))",
            records
        )
        conn.commit()
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"批量插入 {len(records)} 条阅读数记录")
    except Exception as e:
        conn.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"批量插入失败: {e}")
        raise
    finally:
        conn.close()

def add_articles_batch(articles: List[tuple]) -> List[int]:
    """批量添加文章（优化性能，使用事务）
    
    Args:
        articles: [(url, title, site), ...] 列表
        
    Returns:
        文章ID列表（已存在的文章返回现有ID）
    """
    if not articles:
        return []
    
    conn = get_db()
    cursor = conn.cursor()
    article_ids = []
    
    try:
        for url, title, site in articles:
            try:
                cursor.execute(
                    'INSERT INTO articles (url, title, site) VALUES (?, ?, ?)',
                    (url, title, site)
                )
                article_ids.append(cursor.lastrowid)
            except sqlite3.IntegrityError:
                # URL已存在，获取现有ID
                cursor.execute('SELECT id FROM articles WHERE url = ?', (url,))
                row = cursor.fetchone()
                article_ids.append(row['id'] if row else None)
        
        conn.commit()
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"批量添加 {len(articles)} 篇文章")
    except Exception as e:
        conn.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"批量添加文章失败: {e}")
        raise
    finally:
        conn.close()
    
    return article_ids

def get_read_counts(article_id: int, limit: int = 100, start_date: str = None, end_date: str = None, group_by_hour: bool = False) -> List[Dict]:
    """获取文章阅读数历史 - 使用timestamp和id双重排序确保稳定性

    Args:
        article_id: 文章ID
        limit: 返回记录数限制
        start_date: 开始日期 (可选, 格式: YYYY-MM-DD)
        end_date: 结束日期 (可选, 格式: YYYY-MM-DD)
        group_by_hour: 是否按小时分组 (用于今天视图)
    """
    conn = get_db()
    cursor = conn.cursor()

    if group_by_hour and start_date:
        # 按小时分组，获取每小时的最新记录
        query = '''
            SELECT 
                article_id,
                MAX(count) as count,
                strftime('%Y-%m-%d %H:00:00', timestamp) as timestamp
            FROM read_counts 
            WHERE article_id = ? AND DATE(timestamp) = ?
            GROUP BY strftime('%H', timestamp)
            ORDER BY timestamp ASC
        '''
        cursor.execute(query, (article_id, start_date))
    else:
        # 原有逻辑：按日期查询
        query = 'SELECT * FROM read_counts WHERE article_id = ?'
        params = [article_id]

        # 添加日期过滤
        if start_date:
            query += ' AND DATE(timestamp) >= ?'
            params.append(start_date)

        if end_date:
            query += ' AND DATE(timestamp) <= ?'
            params.append(end_date)

        query += ' ORDER BY timestamp DESC, id DESC LIMIT ?'
        params.append(limit)

        cursor.execute(query, tuple(params))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_latest_read_count(article_id: int) -> Optional[Dict]:
    """获取最新阅读数 - 使用timestamp和id双重排序确保稳定性"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM read_counts WHERE article_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1',
        (article_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_latest_read_counts_batch(article_ids: List[int]) -> Dict[int, Dict]:
    """批量获取最新阅读数（优化性能）
    
    Args:
        article_ids: 文章ID列表
        
    Returns:
        字典：{article_id: {'count': int, 'timestamp': str}}
    """
    if not article_ids:
        return {}
    
    conn = get_db()
    cursor = conn.cursor()
    # 使用窗口函数获取每个文章的最新记录
    placeholders = ','.join(['?'] * len(article_ids))
    cursor.execute(f'''
        SELECT 
            article_id,
            count,
            timestamp
        FROM (
            SELECT 
                article_id,
                count,
                timestamp,
                ROW_NUMBER() OVER (PARTITION BY article_id ORDER BY timestamp DESC, id DESC) as rn
            FROM read_counts
            WHERE article_id IN ({placeholders})
        )
        WHERE rn = 1
    ''', article_ids)
    rows = cursor.fetchall()
    conn.close()
    
    result = {}
    for row in rows:
        result[row['article_id']] = {
            'count': row['count'],
            'timestamp': row['timestamp']
        }
    return result

def get_article_by_id(article_id: int) -> Optional[Dict]:
    """根据ID获取文章信息（优化：避免获取所有文章）"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_article(article_id: int):
    """删除文章及所有记录"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM read_counts WHERE article_id = ?', (article_id,))
    cursor.execute('DELETE FROM articles WHERE id = ?', (article_id,))
    conn.commit()
    conn.close()


def update_article_title(article_id: int, title: str) -> bool:
    """更新文章标题
    
    Args:
        article_id: 文章ID
        title: 新标题
        
    Returns:
        是否更新成功
    """
    if not title or not title.strip():
        return False
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE articles SET title = ? WHERE id = ?',
        (title.strip(), article_id)
    )
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def delete_read_count_by_timestamp(article_id: int, timestamp: str) -> int:
    """删除指定文章的指定时间点的阅读数记录
    
    Args:
        article_id: 文章ID
        timestamp: 时间戳 (格式: YYYY-MM-DD HH:MM:SS)
    
    Returns:
        删除的记录数
    """
    conn = get_db()
    cursor = conn.cursor()
    # 精确匹配时间戳（允许小的时间差）
    cursor.execute('''
        DELETE FROM read_counts 
        WHERE article_id = ? AND timestamp = ?
    ''', (article_id, timestamp))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count

def get_article_by_url(url: str) -> Optional[Dict]:
    """根据URL获取文章信息"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE url = ?', (url,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_setting(key: str, default_value=None):
    """获取设置 - 返回原始字符串值，由调用者负责类型转换"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row['value']
    return default_value

def set_setting(key: str, value):
    """设置配置"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    ''', (key, str(value)))
    conn.commit()
    conn.close()

def get_aggregated_read_counts(days: int = None, start_date: str = None, end_date: str = None) -> List[Dict]:
    """获取聚合阅读数数据（按日期和网站分组）- 每篇文章只取最大阅读数"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 构建 WHERE 条件
    where_clause = "1=1"
    params = []
    
    if start_date and end_date:
        where_clause = "strftime('%Y-%m-%d', timestamp) >= ? AND strftime('%Y-%m-%d', timestamp) <= ?"
        params = [start_date, end_date]
    elif days:
        where_clause = "timestamp >= datetime('now', '-' || ? || ' days')"
        params = [days]
    
    # 使用子查询获取每篇文章在指定日期的最大阅读数
    cursor.execute(f'''
        SELECT 
            max_counts.date,
            a.site,
            SUM(max_counts.max_count) as total_count,
            COUNT(DISTINCT max_counts.article_id) as article_count
        FROM (
            SELECT 
                article_id,
                strftime('%Y-%m-%d', timestamp) as date,
                MAX(count) as max_count
            FROM read_counts
            WHERE {where_clause}
            GROUP BY article_id, strftime('%Y-%m-%d', timestamp)
        ) max_counts
        JOIN articles a ON max_counts.article_id = a.id
        GROUP BY max_counts.date, a.site
        ORDER BY max_counts.date ASC, a.site ASC
    ''', params)
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_all_read_counts_summary(days: int = None, start_date: str = None, end_date: str = None) -> List[Dict]:
    """获取所有阅读数汇总（按日期）- 每篇文章只取最大阅读数"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 构建 WHERE 条件
    where_clause = "1=1"
    params = []
    
    if start_date and end_date:
        where_clause = "strftime('%Y-%m-%d', timestamp) >= ? AND strftime('%Y-%m-%d', timestamp) <= ?"
        params = [start_date, end_date]
    elif days:
        where_clause = "timestamp >= datetime('now', '-' || ? || ' days')"
        params = [days]
    
    # 使用子查询获取每篇文章每天的最大阅读数，然后求和
    cursor.execute(f'''
        SELECT 
            date,
            SUM(max_count) as total_count,
            COUNT(*) as article_count,
            AVG(max_count) as avg_count
        FROM (
            SELECT 
                article_id,
                strftime('%Y-%m-%d', timestamp) as date,
                MAX(count) as max_count
            FROM read_counts
            WHERE {where_clause}
            GROUP BY article_id, strftime('%Y-%m-%d', timestamp)
        )
        GROUP BY date
        ORDER BY date ASC
    ''', params)
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def clear_cache(days: int = None, before_date: str = None) -> int:
    """清除缓存 - 删除指定天数之前或指定日期之前的数据"""
    conn = get_db()
    cursor = conn.cursor()
    
    if before_date:
        # 删除指定日期之前的数据
        cursor.execute('''
            DELETE FROM read_counts 
            WHERE strftime('%Y-%m-%d', timestamp) < ?
        ''', (before_date,))
    elif days:
        # 删除指定天数之前的数据
        cursor.execute('''
            DELETE FROM read_counts 
            WHERE timestamp < datetime('now', '-' || ? || ' days')
        ''', (days,))
    else:
        # 如果没有指定条件，返回0
        conn.close()
        return 0
    
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count

def get_platform_health() -> List[Dict]:
    """獲取各平台健康狀態（基於最新爬取時間）
    
    Returns:
        包含 site, last_update, article_count 的列表
    """
    conn = get_db()
    cursor = conn.cursor()
    # 獲取每個平台最新的一條記錄的時間
    cursor.execute('''
        SELECT 
            a.site,
            MAX(rc.timestamp) as last_update,
            COUNT(DISTINCT a.id) as article_count
        FROM articles a
        LEFT JOIN read_counts rc ON a.id = rc.article_id
        GROUP BY a.site
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

