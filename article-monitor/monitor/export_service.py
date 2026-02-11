import csv
import io
from datetime import datetime
from typing import List, Optional, Tuple

from .database import get_all_articles, get_read_counts


def export_selected_articles_csv(
    article_ids: List[int],
    start_date: Optional[str],
    end_date: Optional[str],
) -> Tuple[bytes, str]:
    """生成選定文章的 CSV 資料 bytes 與檔名。"""
    output = io.StringIO()
    writer = csv.writer(output)

    output.write('\ufeff')
    writer.writerow(['文章标题', '网站', 'URL', '阅读数', '记录时间'])

    all_articles = get_all_articles()
    articles_dict = {a['id']: a for a in all_articles}

    for article_id in article_ids:
        article = articles_dict.get(article_id)
        if not article:
            continue

        history = get_read_counts(article_id, start_date=start_date, end_date=end_date)
        for record in history:
            writer.writerow(
                [
                    article.get('title', 'N/A'),
                    article.get('site', 'N/A'),
                    article.get('url', 'N/A'),
                    record['count'],
                    record['timestamp'],
                ]
            )

    output.seek(0)
    filename = f"article_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return output.getvalue().encode('utf-8-sig'), filename


def export_all_articles_csv(
    start_date: Optional[str],
    end_date: Optional[str],
) -> Tuple[bytes, str]:
    """生成所有文章的 CSV 資料 bytes 與檔名。"""
    output = io.StringIO()
    writer = csv.writer(output)

    output.write('\ufeff')
    writer.writerow(['文章标题', '网站', 'URL', '阅读数', '记录时间'])

    articles = get_all_articles()
    for article in articles:
        history = get_read_counts(article['id'], start_date=start_date, end_date=end_date)

        for record in history:
            writer.writerow(
                [
                    article.get('title', 'N/A'),
                    article.get('site', 'N/A'),
                    article.get('url', 'N/A'),
                    record['count'],
                    record['timestamp'],
                ]
            )

    output.seek(0)
    filename = f"all_articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return output.getvalue().encode('utf-8-sig'), filename

