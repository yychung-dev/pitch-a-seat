from config.database import get_connection
from typing import Dict, List, Any


# ================================================
# 查詢會員的所有通知資料 (依通知建立時間, 由新到舊排序)
def get_notifications(member_id: int) -> List[Dict]:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT id, message, url, is_read, created_at
                FROM notifications
                WHERE member_id = %s
                ORDER BY created_at DESC
            """, (member_id,))
            return cursor.fetchall()    
    
    # 回傳值: 通知列表 (包含每一筆通知的相關資訊). 
    # eg. [{"id": 1, "message": "訂單 #1 已付款，請出貨", "url": "/member_sell", "is_read": 1, "created_at": "2025-02-05T21:53:16"}, {"id": 2, "message": "訂單 #2 已出貨，請確認物流", "url": "/member_buy", "is_read": 1, "created_at": "2025-02-04T21:51:27"}]
    # is_read 0 表示未讀，1 表示已讀
# ================================================




# ================================================
# 將所有所有未讀通知標記為已讀 API
def mark_all_notifications_read(member_id: int) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE notifications
                SET is_read = TRUE
                WHERE member_id = %s AND is_read = FALSE
            """, (member_id,))
            updated = cursor.rowcount                # cursor.rowcount 是本次 UPDATE 的資料筆數, 表示: 本次「從未讀被標記為已讀」的通知筆數
        conn.commit()
    return {"status": "success", "updated": updated} # 回傳:「標記狀態為 success」, 「本次標記的筆數」
# ================================================

