from config.database import get_connection
from mysql.connector import Error

from typing import Dict, List, Any


# ================================================
# 建立預約: 將預約資料插入 reservations 資料表
def create_reservation(member_id: int, game_id: int, price_ranges: str,
                      seat_area: str) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO reservations (member_id, game_id, price_ranges, seat_area)
                VALUES (%s, %s, %s, %s)
            """, (
                member_id,
                game_id,
                price_ranges,
                seat_area
            ))
        conn.commit()
    return {"status": "success"}


    # 回傳值: 若建立成功, 回傳「預約狀態為 success」. 若建立失敗, 原樣拋出資料庫錯誤給 router層, 由 router 層接住後包成 500
    # 提醒：price_ranges 這個 list 會自動被 MySQL 轉為 JSON 字串儲存到資料庫裡

# ================================================





# ================================================
# 查詢會員的預約資料
# 回傳預約相關資訊: 賽事資訊、預約資訊
def get_user_reservations(member_id: int) -> List[Dict]:
    query = """
            SELECT 
                r.id, r.game_id, r.price_ranges, r.seat_area, r.created_at,
                g.game_date, g.start_time, g.team_home, g.team_away
            FROM reservations r
            JOIN games g ON r.game_id = g.id
            WHERE r.member_id = %s
            ORDER BY r.created_at DESC
        """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (member_id,))
            results = cursor.fetchall()
            
            return results
# ================================================




# ================================================
# 使用「資料庫鎖 - 排他鎖」
def delete_reservation_with_lock(reservation_id: int, member_id: int) -> bool:
    """
    使用 SELECT ... FOR UPDATE + DELETE，在同一個 transaction 裡完成：
    1. 檢查該預約是否存在且該預約屬於此會員
    2. 若存在 -> 執行 DELETE
    3. 若不存在 -> 直接回傳 False 給 router 層做後續錯誤處理

    回傳值：
    - True  -> 有刪到一筆（預約資料存在且屬於該會員）
    - False -> 找不到符合條件的預約（預約資料不存在或不屬於該會員）
    發生例外錯誤則原樣拋出，交由上層 router 層處理
    """
    with get_connection() as conn:
        try:
            # 明確開始 transaction，確保鎖到 DELETE / COMMIT 期間都有效
            conn.start_transaction()

            with conn.cursor(dictionary=True) as cursor:
                # 1. SELECT ... FOR UPDATE：
                #    - 檢查預約資料表中, 該筆預約資料是否存在 (以「預約資料id 與 member_id」為條件, 確保只有預約者本人可以取消自己的預約) 
                #    - 同時對這筆預約資料 row 加「排他鎖」，避免其他 transaction 同時修改 / 刪除 (其他 transaction 指「其他同時發生的資料庫操作」)
                cursor.execute(
                    """
                    SELECT id FROM reservations
                    WHERE id = %s AND member_id = %s
                    FOR UPDATE
                    """,
                    (reservation_id, member_id)
                )
                row = cursor.fetchone()

                if not row:
                    # 沒查到這筆 row（這筆預約資料不存在 or 這筆預約資料不屬於操作刪除動作的使用者）
                    # rollback 這個 transaction (Rollback 不只能撤銷資料修改, 此處還能釋放鎖並結束 transaction. 即使沒有修改資料，也需要明確釋放鎖，否則若不做 rollback，鎖會一直持有到連線關閉, 其他 transaction 會一直等待)
                    conn.rollback()
                    return False

                # 2. 若前一步驟確認有這筆預約資料, 這時才執行 DELETE 指令, 真正刪除這筆預約
                #同一個 connection、同一個 transaction: 因為鎖綁定在 transaction 上，只有在同一個 transaction 內，鎖才有效. 若另開新連線, 就一定已經不在同一個 transaction中了, 而已經是「新的 connection, 新的 connection」，之前的鎖已無效, 這時其他人(其他 transaction)可能已經修改了資料
                # 使用 ROLLBACK 表達「這個 transaction 沒有成功完成」的語意
                cursor.execute(
                    "DELETE FROM reservations WHERE id = %s",
                    (reservation_id,)
                )

            # 3. 刪除成功 -> commit, 釋放鎖 (MySQL 在 COMMIT 或 ROLLBACK 後，會自動釋放該 transaction 持有的所有鎖。)
            conn.commit()
            return True  # 回傳 True, 供 router 層拿來判斷

        except Error as e:
            # DB 錯誤：rollback，讓 router 層包成 HTTP 500
            print("delete_reservation_with_lock DB error:", e)
            conn.rollback()
            raise
        except Exception as e:
            # 其他非 MySQL 相關的例外錯誤：也 rollback
            print("delete_reservation_with_lock error:", e)
            conn.rollback()
            raise
        
        # 不需要 finally: conn.close(), 因為 with get_connection() 會自動處理
# ================================================