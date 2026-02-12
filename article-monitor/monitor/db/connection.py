import os
import sqlite3
import logging

from ..config import DATABASE_PATH, SQLITE_CACHE_SIZE_KB


logger = logging.getLogger(__name__)


os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)


def _apply_db_optimizations(conn: sqlite3.Connection) -> None:
    """应用数据库性能优化设置（每次新连接都需要设置）"""
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    # 負值表示頁數（約 1 頁=1KB），由 config 控制；低資源時 2MB 減少記憶體
    conn.execute(f'PRAGMA cache_size=-{SQLITE_CACHE_SIZE_KB}')
    conn.execute('PRAGMA temp_store=MEMORY')
    conn.execute('PRAGMA foreign_keys=ON')


def get_db() -> sqlite3.Connection:
    """获取数据库连接（启用 WAL 模式提升并发性能）"""
    conn = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    _apply_db_optimizations(conn)
    return conn


def init_db() -> None:
    """初始化数据库和基础表结构"""
    from datetime import datetime  # noqa: F401  保留與原檔一致的依賴
    from ..config import CRAWL_INTERVAL_HOURS

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            title TEXT,
            site TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS read_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            count INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_article_id ON read_counts(article_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON read_counts(timestamp)')

    cursor.execute('SELECT COUNT(*) as count FROM settings WHERE key = ?', ('crawl_interval_hours',))
    if cursor.fetchone()['count'] == 0:
        cursor.execute(
            '''
            INSERT INTO settings (key, value) VALUES (?, ?)
            ''',
            ('crawl_interval_hours', str(CRAWL_INTERVAL_HOURS)),
        )

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

