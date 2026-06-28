# models/recommendation_event_model.py
# 推薦事件記錄：曝光(impression) 與 點擊(click)。
# 注意：記錄是 best-effort，刻意吞掉例外，絕不讓記錄失敗影響推薦主流程。

import logging
from typing import Any, Dict, List

from mysql.connector import Error
from config.database import get_connection

logger = logging.getLogger(__name__)


# 批次寫入曝光：一次推薦 = 多筆 impression，共用同一個 request_id
def log_impressions(request_id: str, member_id: int, variant: str,
                    recommendations: List[Dict[str, Any]]) -> None:
    if not recommendations:
        return
    rows = [
        (request_id, member_id, rec["game_id"], rank, variant, rec.get("recommendation_score"))
        for rank, rec in enumerate(recommendations, start=1)
    ]
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.executemany("""
                    INSERT INTO recommendation_events
                        (request_id, member_id, game_id, rank_pos, variant, recommendation_score, event_type)
                    VALUES (%s, %s, %s, %s, %s, %s, 'impression')
                """, rows)
            conn.commit()
    except Error as e:
        logger.warning(f"log_impressions 失敗（已忽略，不影響推薦）: {e}")


# 寫入單筆點擊
def log_click(request_id: str, member_id: int, game_id: int,
              rank_pos: int, variant: str) -> None:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO recommendation_events
                        (request_id, member_id, game_id, rank_pos, variant, event_type)
                    VALUES (%s, %s, %s, %s, %s, 'click')
                """, (request_id, member_id, game_id, rank_pos, variant))
            conn.commit()
    except Error as e:
        logger.warning(f"log_click 失敗（已忽略）: {e}")