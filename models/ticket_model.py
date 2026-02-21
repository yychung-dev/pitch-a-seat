from config.database import get_connection

from typing import Dict, List, Any
from fastapi import HTTPException
import json

from utils.email_utils import send_email_async


# ================================================
# 查詢賣家本人的所有上架票券
# 回傳值： 賣家本人所有上架票券的 list (每一張上架票券的資訊包括 : ticket_id, price, is_removed, order_id 等等
# eg. [{"ticket_id": 20, "price": 600, ..., "is_removed":0, "order_id": 15 }, {"ticket_id": 22, "price": 400, ..., "is_removed":0, "order_id": null}](若尚未成立訂單就是 None, 前端JS會呈現 "order_id":null))
def get_seller_tickets(seller_id: int) -> List[Dict]:
    query = """
            SELECT
                t.id AS ticket_id,
                t.price,
                t.seat_number,
                t.seat_area,
                t.created_at,
                t.is_removed,
                g.game_date,
                g.start_time,
                g.team_home,
                g.team_away,
                o.id AS order_id
            FROM tickets_for_sale t
            JOIN games g ON t.game_id = g.id
            LEFT JOIN orders o ON o.ticket_id = t.id
            WHERE t.seller_id = %s
            ORDER BY t.created_at DESC
        """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (seller_id,))
            rows = cursor.fetchall()
            return rows
                    

# ================================================




# ================================================
# 賣家自行下架票券 (將 is_removed 欄位標記為 TRUE)  
# 回傳值: 下架狀態為 success
def remove_ticket(ticket_id: int, seller_id: int) -> Dict[str, Any]:    
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            # 1. 先驗證票券存在且屬於該賣家 (驗證權限, 確保賣家只能刪除「自己上架的票券」)
            cursor.execute("""
                SELECT t.id, t.seller_id, t.is_removed, o.id AS order_id
                FROM tickets_for_sale t
                LEFT JOIN orders o ON o.ticket_id = t.id
                WHERE t.id = %s
            """, (ticket_id,))
            ticket = cursor.fetchone()
            if not ticket:
                raise HTTPException(status_code=404, detail="票券不存在")
            if ticket["seller_id"] != seller_id:
                raise HTTPException(status_code=403, detail="無權限操作此票券")
            if ticket["order_id"]:
                raise HTTPException(status_code=400, detail="訂單已成立，不可下架")
            if ticket["is_removed"]:
                raise HTTPException(status_code=400, detail="票券已下架")

            # 2. 更新 is_removed 欄位
            cursor.execute("""
                UPDATE tickets_for_sale
                SET is_removed = TRUE
                WHERE id = %s
            """, (ticket_id,))
                
        conn.commit()
        
    return {"status": "success"}
# ================================================




# ================================================
# 開啟一個資料庫連線執行 transaction (上架票券、比對預約、通知匹配的預約者) 
# 步驟:
# - 1.查詢 game_number（用於通知訊息中的賽事編號呈現）

# - 2.新增所有票券到 tickets_for_sale 資料表（資料表欄位設計: is_sold 欄位 DEFAULT FALSE）

# - 3. 查詢該場比賽的所有預約資料
# 回傳值: 預約id, 會員id, 預約的票價範圍, 預約的座位區範圍,會員 email
    
# - 4. 對每一張本次新上架的票進行比對
# - 比較價格：上架票券價格是否在任何預約的 price_ranges 範圍內(eg.["0-0"]表示所有價格都接受, ["401-699", "700-999"]表示這筆預約的期望價格在401-999元之間)
# - 比較座位：上架票券的座位區域是否與預約的seat_area 完全相符 (eg."內野"或"外野"), 或預約的 seat_area 是 "none" (表示這筆預約接受內野和外野區座位) 
    
# - 5. 符合條件的預約者執行兩個動作：
    # a. 新增通知到 notifications 表
    #     - member_id, message, url="/buy"
    # b. 收集 Email 通知資料
    #     - 收件人：預約者 email
    #     - 信件標題
    #     - 信件內容：比賽編號(game_number)、座位區、價格 

# - 6. 最後一起 commit

# - 7. commit 成功後，才使用send_email_async寄送所有email (發到 SQS Queue 裡)



def create_tickets_and_collect_matches(
    seller_id: int,
    game_id: int,
    ticket_list: List[Dict[str, Any]],
    img_map: Dict[str, List[str]]
) -> None:

    email_notifications = [] # 在 with conn 外面先初始化 email_notifications (「先初始化」是防禦性設計)
    # email_notifications 變數本身的目的: 收集所有需要發送的 Email 通知的相關資訊 (若有多筆預約符合這張上架票券, 需要收集各個不同預約者的 Email 資訊, 並使用 loop 一一發送 email)

    insert_sql = """
        INSERT INTO tickets_for_sale
        (seller_id, game_id, price, seat_number, seat_area, image_urls, note)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """

    # 開一個連線，用同一個 transaction 同步 上架 + 比對 + 插入通知 + 收集email資訊
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            # 查詢 game_number
            cursor.execute("SELECT game_number FROM games WHERE id = %s", (game_id,))
            game = cursor.fetchone()
            if not game:
                raise HTTPException(status_code=404, detail="賽事不存在")
            game_number = game["game_number"]
            
            # 1. 新增票券資訊 (將本次上架的所有票券插入 tickets_for_sale 資料表)
            for idx, ticket in enumerate(ticket_list):
                imgs = img_map.get(str(idx), [])
                cursor.execute(insert_sql, (
                    seller_id,
                    game_id,
                    ticket["price"],
                    ticket["seat_number"],
                    ticket["seat_area"],
                    json.dumps(imgs),
                    ticket.get("note", "")
                ))

            # 2. 抓出目前 reservations 資料表中，與「本次上架票券的場次」匹配的預約資料
            cursor.execute("""
                SELECT r.id, r.member_id, r.price_ranges, r.seat_area, m.email
                FROM reservations r
                JOIN members m ON r.member_id = m.id
                WHERE r.game_id = %s
            """, (game_id,))
            reservations = cursor.fetchall()

            # 3. 針對每一張剛上架的票券，和每筆同場次的預約資料比對「價格與座位條件是否符合」（資料處理 + DB操作）
            for ticket in ticket_list:
                price = ticket["price"]
                area  = ticket["seat_area"]
                for r in reservations:
                    price_ranges = json.loads(r["price_ranges"])

                    # 檢查價格是否符合
                    def in_range(pr: str) -> bool:
                        lo, hi = map(int, pr.split("-"))
                        # "0-0" 是「預約者沒設價格要求條件 (預約者接受所有價格) 」
                        return (lo == hi == 0) or (lo <= price <= hi)

                    matched_price = any(in_range(pr) for pr in price_ranges)
                    # 檢查座位是否符合
                    matched_area = (r["seat_area"] == "none") or (r["seat_area"] == area)

                    if matched_price and matched_area:
                        msg = f"賽事 {game_number} 有新票：{area} / {price} 元"

                        # 4. 新增通知 (插入 notifications 資料表）
                        cursor.execute("""
                            INSERT INTO notifications (member_id, message, url)
                            VALUES (%s, %s, %s)
                        """, (r["member_id"], msg, "/buy"))

                        # 5. 收集 Email 通知資料                        
                        email_notifications.append({
                            "to": r["email"],
                            "subject": "Pitch-A-Seat 預約通知",
                            "body": (
                                f"您預約的場次 {game_number} 有新票：\n"
                                f"座位：{area}\n價格：{price} 元"
                            )
                        })
                        # 可能需要寄多封 Email（多筆預約都匹配本次上架票券條件的情形），所以用列表 email_notifications, 在loop內收集每一筆通知資料，commit 成功後再寄信

        # 最後一起 commit（前面任何地方丟 Exception，都不會執行到這行）
        conn.commit()
    
    
    # 6. commit 成功後，才寄送所有 Email (發到 SQS Queue 裡)
    for notification in email_notifications:
        send_email_async(
            to = notification["to"],
            subject = notification["subject"],
            body = notification["body"]
        )

# ================================================




# ================================================
# 查詢並回傳 「該場比賽正在販售中的所有票券總筆數」
# 負責組 SQL 指令 + 執行查詢 + 回傳 total_count
def count_browse_tickets(game_id: int, seat_filters: List[str]) -> int:
    count_query = """
        SELECT COUNT(DISTINCT t.id) AS total_count
        FROM tickets_for_sale t
        JOIN games g ON t.game_id = g.id
        JOIN members m ON t.seller_id = m.id
        LEFT JOIN ratings r ON r.ratee_id = m.id
        WHERE t.game_id = %s AND t.is_sold = FALSE AND t.is_removed = FALSE
    """
    count_params: List = [game_id]

    # 若有篩選座位區，附加 AND t.seat_area IN (...)
    if seat_filters:
        placeholders = ", ".join(["%s"] * len(seat_filters))
        count_query += f" AND t.seat_area IN ({placeholders})"
        count_params.extend(seat_filters)

    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(count_query, tuple(count_params))
            row = cursor.fetchone()
            return row["total_count"]
# ================================================




# ================================================
# 查詢並回傳該場比賽販售中的所有票券資訊 (只呈現當前頁面的所有票券資訊: 一頁最多只呈現 6 張票券的資訊)
# 負責組 SQL 指令 + 執行查詢 + 回傳 raw rows（不做 JSON / 時間格式轉換等資料格式處理）
# 回傳每張販售中票券的資訊（前端會將每筆資料渲染成一張票券卡片）
def get_browse_tickets_page(
    game_id: int,
    seat_filters: List[str],
    sort_column: str,
    sort_order: str,
    per_page: int,
    offset: int,
) -> List[Dict]:

    # 查詢該場比賽販售中的所有票券的 SQL 指令
    data_query = f"""
        SELECT
            t.id, t.game_id, t.seat_number, t.seat_area, t.price,
            t.image_urls, t.note, t.created_at, g.game_date, g.stadium,
            g.team_home, g.team_away, g.start_time, m.name AS seller_name,
            AVG(r.score) AS avg_rating
        FROM tickets_for_sale t
        JOIN games g ON t.game_id = g.id
        JOIN members m ON t.seller_id = m.id
        LEFT JOIN ratings r ON r.ratee_id = m.id
        WHERE t.game_id = %s AND t.is_sold = FALSE AND t.is_removed = FALSE
    """
    data_params: List = [game_id]


    # 依各種篩選條件進一步組出客製化的 SQL 查詢指令
    
    # 1.若有座位區篩選條件，動態組出 IN (%s, %s, ...) 
    if seat_filters:
        placeholders = ", ".join(["%s"] * len(seat_filters))   # placeholders 是字串, eg. "%s, %s" 
        
        data_query += f" AND t.seat_area IN ({placeholders})"  # data_query 是字串, eg. "AND t.seat_area IN (%s, %s)" 

        data_params.extend(seat_filters)  # data_params 是 list, eg. cursor.execute(data_query, tuple(data_params))

    # 2.其他篩選條件: 「上架時間、價格高低、評分高低 (sort_column)」 搭配 「排序條件 (sort_order)(DESC 或 ASC: 最新上架、最舊上架、價格由低至高、價格由高至低、評分由低至高、評分由高至低)」 
    data_query += " GROUP BY t.id ORDER BY " + sort_column + " " + sort_order

    # 3.LIMIT + OFFSET（分頁: 一頁 6 筆）
    data_query += " LIMIT %s OFFSET %s"
    data_params.extend([per_page, offset])

    # 執行客製化的 SQL 查詢指令
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(data_query, tuple(data_params))  # 執行查詢（list 轉 tuple 作為參數化查詢的參數）
            rows = cursor.fetchall()
            return rows
# ================================================




