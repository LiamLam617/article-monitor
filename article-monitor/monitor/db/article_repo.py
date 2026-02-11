from typing import List, Dict, Optional

from .connection import get_db


def update_article_status(article_id: int, status: str, error: Optional[str] = None) -> None:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''
        UPDATE articles 
        SET last_status = ?, last_error = ?, last_crawl_time = datetime('now', 'localtime')
        WHERE id = ?
        ''',
        (status, error, article_id),
    )
    conn.commit()
    conn.close()


def get_platform_failures() -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT 
            id, title, url, site, last_error, last_crawl_time
        FROM articles 
        WHERE last_status = 'ERROR' OR (last_status = 'PENDING' AND last_error IS NOT NULL)
        ORDER BY last_crawl_time DESC
        '''
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_failures(limit: int = 100, site: Optional[str] = None) -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()

    if site:
        cursor.execute(
            '''
            SELECT 
                id, title, url, site, last_error, last_crawl_time, last_status
            FROM articles 
            WHERE (last_status = 'ERROR' OR (last_status != 'OK' AND last_error IS NOT NULL))
            AND site = ?
            ORDER BY last_crawl_time DESC, id DESC
            LIMIT ?
            ''',
            (site, limit),
        )
    else:
        cursor.execute(
            '''
            SELECT 
                id, title, url, site, last_error, last_crawl_time, last_status
            FROM articles 
            WHERE last_status = 'ERROR' OR (last_status != 'OK' AND last_error IS NOT NULL)
            ORDER BY last_crawl_time DESC, id DESC
            LIMIT ?
            ''',
            (limit,),
        )

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_failure_stats() -> Dict:
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        '''
        SELECT COUNT(*) as count 
        FROM articles 
        WHERE last_status = 'ERROR' OR (last_status != 'OK' AND last_error IS NOT NULL)
        '''
    )
    total = cursor.fetchone()['count']

    cursor.execute(
        '''
        SELECT 
            site, COUNT(*) as count
        FROM articles 
        WHERE last_status = 'ERROR' OR (last_status != 'OK' AND last_error IS NOT NULL)
        GROUP BY site
        ORDER BY count DESC
        '''
    )
    by_site = {row['site']: row['count'] for row in cursor.fetchall()}

    cursor.execute(
        '''
        SELECT COUNT(*) as count
        FROM articles 
        WHERE (last_status = 'ERROR' OR (last_status != 'OK' AND last_error IS NOT NULL))
        AND last_crawl_time >= datetime('now', '-24 hours')
        '''
    )
    recent_24h = cursor.fetchone()['count']

    conn.close()

    return {
        'total': total,
        'by_site': by_site,
        'recent_24h': recent_24h,
    }


def add_article(url: str, title: Optional[str] = None, site: Optional[str] = None) -> int:
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            'INSERT INTO articles (url, title, site) VALUES (?, ?, ?)',
            (url, title, site),
        )
        article_id = cursor.lastrowid
        conn.commit()
        return article_id
    except Exception:
        cursor.execute('SELECT id FROM articles WHERE url = ?', (url,))
        row = cursor.fetchone()
        return row['id'] if row else None
    finally:
        conn.close()


def get_all_articles() -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_articles_with_latest_count() -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''
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
        '''
    )
    rows = cursor.fetchall()
    conn.close()
    articles: List[Dict] = []
    for row in rows:
        article = dict(row)
        if article.get('latest_count') is None:
            article['latest_count'] = 0
            article['latest_timestamp'] = None
        articles.append(article)
    return articles


def add_articles_batch(articles: List[tuple]) -> List[int]:
    if not articles:
        return []

    conn = get_db()
    cursor = conn.cursor()
    article_ids: List[int] = []

    try:
        for url, title, site in articles:
            try:
                cursor.execute(
                    'INSERT INTO articles (url, title, site) VALUES (?, ?, ?)',
                    (url, title, site),
                )
                article_ids.append(cursor.lastrowid)
            except Exception:
                cursor.execute('SELECT id FROM articles WHERE url = ?', (url,))
                row = cursor.fetchone()
                article_ids.append(row['id'] if row else None)

        conn.commit()
    except Exception as e:
        conn.rollback()
        from .. import database as legacy_db  # noqa: F401  保留日誌行為
        raise
    finally:
        conn.close()

    return article_ids


def get_article_by_id(article_id: int) -> Optional[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_article(article_id: int) -> None:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM read_counts WHERE article_id = ?', (article_id,))
    cursor.execute('DELETE FROM articles WHERE id = ?', (article_id,))
    conn.commit()
    conn.close()


def update_article_title(article_id: int, title: str) -> bool:
    if not title or not title.strip():
        return False

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE articles SET title = ? WHERE id = ?',
        (title.strip(), article_id),
    )
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_article_by_url(url: str) -> Optional[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE url = ?', (url,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

