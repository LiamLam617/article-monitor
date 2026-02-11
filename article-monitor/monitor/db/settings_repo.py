from typing import Optional

from .connection import get_db


def get_setting(key: str, default_value=None) -> Optional[str]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row['value']
    return default_value


def set_setting(key: str, value) -> None:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT OR REPLACE INTO settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ''',
        (key, str(value)),
    )
    conn.commit()
    conn.close()

