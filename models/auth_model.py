from config.database import get_connection

from typing import Optional, Dict, List, Any
from datetime import date, datetime



# ================================================
# 根據 email 查詢會員資料
# 回傳值 : 會員資料 (Dict) 或 None

def get_user_by_email(email: str) -> Optional[Dict]:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT id, name, email, password_hash, phone, city, favorite_teams, created_at, updated_at FROM members WHERE email = %s",
                (email,)
            )
            return cursor.fetchone()

# Optional[Dict] : 「回傳值可以是 Dict 或 None」 , 不是指「回傳值可以是 dictionary 也可以是其他任意型別」
# 若型別註記沒有寫 Optional、但實際回傳 None，不會報錯 (因為Python 的型別註記（type hint）不是強制檢查機制。)；若寫 Optional[Dict]，但回傳既不是 Dict 也不是 None，而是其他型別，也不會報錯。
# 寫 Optional 的目的只是「未來維護時能更清楚程式意圖」


# 若其他 API 都不會用到 phone, city, favorite_teams, created_at, updated_at , 建議刪掉, 不拿多餘不會用到的資料
# ================================================





# ================================================
# 根據 name 查詢會員資料
# 回傳值 : 會員資料 (Dict) 或 None
def get_user_by_name(name: str) -> Optional[Dict]:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT id, name, email, password_hash, phone, city, favorite_teams, created_at, updated_at FROM members WHERE name = %s",
                (name,)
            )
            return cursor.fetchone()
# ================================================






# ================================================
# 建立新註冊會員的資料
# 回傳值 : 新會員的 id
def create_member(
    name: str,
    email: str,
    password_hash: str,
    phone: str,
    city: Optional[str],
    favorite_teams_json: Optional[str], 
) -> int:
    
    insert_query = """
        INSERT INTO members
        (name, email, password_hash, phone, city, favorite_teams)
        VALUES (%s, %s, %s, %s, %s, %s)
    """

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(insert_query, (
                name,
                email,
                password_hash,
                phone,
                city,
                favorite_teams_json,
            ))
            conn.commit()
            return cursor.lastrowid
# ================================================





# ================================================
# 根據 會員 id 查詢會員資料
# 回傳值 : 會員資料 (Dict) 或 None
def get_member_row_by_id(user_id:int)-> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:            
            cursor.execute("""
                SELECT id, name, email, phone, city, favorite_teams, subscribe_newsletter, created_at, updated_at
                FROM members WHERE id = %s
                """,(user_id,))
            row = cursor.fetchone()
            return row

# model 層只做資料庫查詢(或其他資料庫指令)，不做「json.loads / HTTPException 」等處理, 「json.loads / HTTPException 」統一到 router 層處理 
# ================================================




# ================================================
# GET /api/user/auth 本就沒打算回傳使用者的 avg_rating 給前端 (20250620 版就是這樣) (因為 GET api/user/auth 只是為了每次進頁面要驗證使用者身份時使用，但身份驗證這種動作不需要拿 avg_rating 也沒關係)，只是因為 auth.py 的 UserProfileOut pydantic model 不小心多寫了 avg_rating 欄位並允許 None，所以 devtool 中的 Response 才會出現 avg_rating:null。
# 目前先這樣 (目前沒有負面影響)，但記得 avg_rating 只有在渲染個人資料頁時需要用到，會由 GET api/user/profile 去資料庫拿 avg_rating 並渲染。
# ================================================