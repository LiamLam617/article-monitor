from typing import List, Dict, Optional

from .connection import get_db


def add_read_count(article_id: int, count: int) -> None:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO read_counts (article_id, count, timestamp) VALUES (?, ?, datetime('now', 'localtime'))",
        (article_id, count),
    )
    conn.commit()
    conn.close()


def add_read_counts_batch(records: List[tuple]) -> None:
    if not records:
        return

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.executemany(
            "INSERT INTO read_counts (article_id, count, timestamp) VALUES (?, ?, datetime('now', 'localtime'))",
            records,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_read_counts(
    article_id: int,
    limit: int = 100,
    start_date: str = None,
    end_date: str = None,
    group_by_hour: bool = False,
) -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()

    if group_by_hour and start_date:
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
        query = 'SELECT * FROM read_counts WHERE article_id = ?'
        params = [article_id]

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
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM read_counts WHERE article_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1',
        (article_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_read_counts_batch(article_ids: List[int]) -> Dict[int, Dict]:
    if not article_ids:
        return {}

    conn = get_db()
    cursor = conn.cursor()
    placeholders = ','.join(['?'] * len(article_ids))
    cursor.execute(
        f'''
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
        ''',
        article_ids,
    )
    rows = cursor.fetchall()
    conn.close()

    result: Dict[int, Dict] = {}
    for row in rows:
        result[row['article_id']] = {
            'count': row['count'],
            'timestamp': row['timestamp'],
        }
    return result


def delete_read_count_by_timestamp(article_id: int, timestamp: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''
        DELETE FROM read_counts 
        WHERE article_id = ? AND timestamp = ?
        ''',
        (article_id, timestamp),
    )
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count


def get_aggregated_read_counts(
    days: int = None,
    start_date: str = None,
    end_date: str = None,
) -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()

    where_clause = '1=1'
    params = []

    if start_date and end_date:
        where_clause = "strftime('%Y-%m-%d', timestamp) >= ? AND strftime('%Y-%m-%d', timestamp) <= ?"
        params = [start_date, end_date]
    elif days:
        where_clause = "timestamp < datetime('now', '-' || ? || ' days')"
        params = [days]

    cursor.execute(
        f'''
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
        ''',
        params,
    )

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_read_counts_summary(
    days: int = None,
    start_date: str = None,
    end_date: str = None,
) -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()

    where_clause = '1=1'
    params = []

    if start_date and end_date:
        where_clause = "strftime('%Y-%m-%d', timestamp) >= ? AND strftime('%Y-%m-%d', timestamp) <= ?"
        params = [start_date, end_date]
    elif days:
        where_clause = "timestamp >= datetime('now', '-' || ? || ' days')"
        params = [days]

    cursor.execute(
        f'''
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
        ''',
        params,
    )

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def clear_cache(days: int = None, before_date: str = None) -> int:
    conn = get_db()
    cursor = conn.cursor()

    if before_date:
        cursor.execute(
            '''
            DELETE FROM read_counts 
            WHERE strftime('%Y-%m-%d', timestamp) < ?
            ''',
            (before_date,),
        )
    elif days:
        cursor.execute(
            '''
            DELETE FROM read_counts 
            WHERE timestamp < datetime('now', '-' || ? || ' days')
            ''',
            (days,),
        )
    else:
        conn.close()
        return 0

    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count


def get_platform_health() -> List[Dict]:
    """獲取各平台健康狀態（基於最新爬取時間）"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT 
            a.site,
            MAX(rc.timestamp) as last_update,
            COUNT(DISTINCT a.id) as article_count
        FROM articles a
        LEFT JOIN read_counts rc ON a.id = rc.article_id
        GROUP BY a.site
        '''
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


