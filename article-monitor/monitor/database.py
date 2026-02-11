"""
数据库操作門面：向後相容地 re-export 新的 db 子模組中的函式。
"""
from typing import List, Dict, Optional

from .db.connection import get_db, init_db
from .db.article_repo import (
    update_article_status,
    get_platform_failures,
    get_all_failures,
    get_failure_stats,
    add_article,
    get_all_articles,
    get_all_articles_with_latest_count,
    add_articles_batch,
    get_article_by_id,
    delete_article,
    update_article_title,
    get_article_by_url,
)
from .db.read_count_repo import (
    add_read_count,
    add_read_counts_batch,
    get_read_counts,
    get_latest_read_count,
    get_latest_read_counts_batch,
    delete_read_count_by_timestamp,
    get_aggregated_read_counts,
    get_all_read_counts_summary,
    clear_cache,
)
from .db.settings_repo import get_setting, set_setting
from .db.read_count_repo import get_platform_health


