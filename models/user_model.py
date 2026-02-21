from config.database import get_connection

from typing import Optional, Dict, List, Any
from fastapi import HTTPException



# ================================================
# 取得會員 email (用於寄信通知功能)
# 參數說明：
#   - cursor: 由呼叫端傳入，用於在同一個 transaction 中執行查詢, 確保「更新訂單 → 查詢 email → 寄信」整個流程的資料一致性
def get_member_email(cursor, member_id: int) -> str:
    cursor.execute("SELECT email FROM members WHERE id = %s", (member_id,))
    member = cursor.fetchone()
    if not member:
        raise HTTPException(status_code=404, detail=f"會員 ID {member_id} 不存在")
    return member["email"]

# 呼叫者 : POST api/mark_shipped API、update_order_and_ticket_status 函數、commit_payment_success_tx 函數

# 提醒 : 呼叫 get_member_email 函數前，要先開好資料庫連線且確認該 cursor 有效。因為 get_member_email 函數沿用同一個資料庫 cursor 來執行「取得使用者 email 」 ( 用在「 transaction 確保一致性 」的情形中 )
# ================================================




# ================================================
# 根據 user_id 查詢完整會員資料
# 回傳值: 會員完整個人資料 (若會員存在) 或 None (若會員不存在)
def get_user_profile(user_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT
                    m.id, m.name, m.email, m.phone, m.city, m.favorite_teams,
                        m.created_at, m.updated_at,
                        AVG(r.score) AS avg_rating
                FROM members m
                LEFT JOIN ratings r ON r.ratee_id = m.id
                WHERE m.id = %s
                GROUP BY m.id
            """, (user_id,))
            row = cursor.fetchone()
            return row
# ================================================





# ================================================
# 檢查會員想更新的 email 是否已被其他帳號使用
# 若有重複, 回傳 409 (HTTP 409 Conflict: 用戶端錯誤回應狀態碼, 表示「請求與目標資源的當前狀態存在衝突」)
def ensure_email_unique_for_update(new_email: str, user_id: int) -> None:        
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM members WHERE email = %s AND id != %s",
                    (new_email, user_id)
                )
                if cursor.fetchone():
                    raise HTTPException(status_code=409, detail="此電子郵件已被其他帳號使用")
    except HTTPException:
        # 保留原本拋出的 409
        raise
    except Exception as e:
        print("檢查 email 唯一性失敗：", e)
        raise HTTPException(status_code=500, detail="伺服器錯誤")
# ================================================




# ================================================
# 檢查會員想更新的 name 是否已被其他帳號使用
# 若有重複, 回傳 409 (HTTP 409 Conflict: 用戶端錯誤回應狀態碼, 表示「請求與目標資源的當前狀態存在衝突」)
def ensure_name_unique_for_update(new_name: str, user_id: int) -> None:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM members WHERE name = %s AND id != %s",
                    (new_name, user_id)
                )
                if cursor.fetchone():
                    raise HTTPException(status_code=409, detail="此姓名已被其他帳號使用")
    except HTTPException:
        raise
    except Exception as e:
        print("檢查姓名唯一性失敗：", e)
        raise HTTPException(status_code=500, detail="伺服器錯誤")
# ================================================





# ================================================
# 更新資料庫內的會員個人資料
def update_member_profile(set_clause: str, values: List[Any]) -> None:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                query = f"UPDATE members SET {set_clause}, updated_at = NOW() WHERE id = %s"
                cursor.execute(query, tuple(values))
                conn.commit()
    except Exception as e:
        print("更新個人資料失敗：", e)
        raise HTTPException(status_code=500, detail="更新失敗")
# ================================================


