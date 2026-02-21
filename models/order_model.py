from config.database import get_connection

from typing import Optional, Dict, List, Any
from datetime import date, datetime, timezone
from fastapi import HTTPException
import json

from utils.email_utils import send_email_async
from utils.time_utils import utc_now 

# 因為在 order_model.py 中的某些函數裡，有呼叫 get_member_email 函數，所以特別在 order_model.py 檔中，從 user_model 引入 get_member_email 函數
from models.user_model import get_member_email




# ================================================
# 送出票券媒合請求的同時, 建立一筆新訂單 (先檢查票券狀態、取得賣家id、檢查買賣雙方不得為同一人、建立一筆新訂單)
# 使用 Transaction 完成三個資料庫動作: (1)先檢查票券狀態(select from tickets_for_sale table) (2)取得賣家id (select from tickets_for_sale table) (3) 建立一筆新訂單 (insert into orders table) (狀態設為「媒合中」) (4) commit
# 無回傳值, Transaction commit 後，函數結束，流程自動返回 router 層

def create_order(ticket_id: int, buyer_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            # 1) 先檢查這張票是否存在、是否已售出 
            # 信任邊界: 必須在後端驗證，不能信任前端傳來的資料 (不能信任前端傳來的 ticket_id 是合法的，必須在後端再次驗證票券狀態)
            # Race Condition 風險說明:
            # - 此處檢查和 INSERT 之間有時間差，多人同時發送媒合請求可能產生多筆「媒合中」訂單
            # - 影響較小：因為「媒合中」只是請求狀態，賣家只會接受其中一筆
            # - 真正決定誰買到票的是「賣家接受媒合」，而非「發送媒合請求」
            
            cursor.execute("SELECT is_sold FROM tickets_for_sale WHERE id = %s", (ticket_id,))
            ticket = cursor.fetchone()
            if not ticket:
                raise HTTPException(status_code=404, detail="找不到票券")
            if ticket["is_sold"]:
                raise HTTPException(status_code=400, detail="此票券已售出")
            
            # 2) 取得 seller_id
            cursor.execute("SELECT seller_id FROM tickets_for_sale WHERE id = %s", (ticket_id,))
            seller = cursor.fetchone()
            seller_id = seller["seller_id"]   # eg. {"seller_id": 3}

            # 2-1) 檢查買家與賣家不可同一人
            if seller_id == buyer_id:
                raise HTTPException(status_code=400, detail="不能對自己販售的票發送媒合請求")
            
            
            # 3) 將新一筆訂單資料插入 orders 資料表 (建立一筆新訂單，訂單狀態設為「媒合中」)
            cursor.execute("""
                INSERT INTO orders (ticket_id, buyer_id, seller_id, status, match_requested_at)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, buyer_id, seller_id, "媒合中", utc_now()))


            # 4) transaction commit ( 每一個資料庫動作都成功完成, 再一起 commit )
            conn.commit()


# --------------

# 除了 insert 指令有插入的欄位之外, orders table 的 matched_at、paid_at、shipped_at 欄位是建表時設計成 DATETIME NULL，之後其他 API 執行到相關動作時才會插入資料
# payment_status 和 shipment_status 欄位是建表時設計成 「 NOT NULL DEFAULT '未付款' 」和 「 NOT NULL DEFAULT '未出貨' 」, 雖未插入資料, 但資料表會自動填入預設值
# status 欄位建表時沒有設計 DEFAULT，只有設計「 NOT NULL 」, 所以必須在 insert指令時記得手動設定 status 的值

# ================================================





# ================================================
# 查詢當下登入會員的所有訂單 API（該會員作為買家的所有訂單）
# 回傳值: 
# List (內含每一筆訂單的 dict) 
# 個別訂單內容包含: 1. 訂單資料 (賽事資訊、媒合狀態、訂單編號、訂單金額、訂單成立時間、付款時間、付款狀態、出貨時間、出貨狀態、商品備註、票券圖片url、該筆訂單的賣家評分...等等)  2. 依訂單成立日期由新至舊排序
def get_buyer_orders(buyer_id: int) -> List[Dict]:
    query = """
        SELECT
            o.id AS order_id,
            o.status AS order_status,
            o.payment_status,
            o.shipment_status,
            o.match_requested_at,
            o.matched_at,
            o.created_at,
            o.paid_at,
            o.shipped_at,
            t.id AS ticket_id,
            t.price,
            t.seat_number,
            t.seat_area,
            t.note,
            t.image_urls,
            t.created_at AS listed_at,
            g.game_date,
            g.start_time,
            g.team_home,
            g.team_away,
            g.stadium,
            t.seller_id,
            r.score AS seller_rating
        FROM orders o
        JOIN tickets_for_sale t ON o.ticket_id = t.id
        JOIN games g ON t.game_id = g.id
        LEFT JOIN ratings r ON r.order_id = o.id AND r.rater_id = o.buyer_id
        WHERE o.buyer_id = %s
        ORDER BY o.id DESC
    """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (buyer_id,))
            rows = cursor.fetchall()
            return rows


# ================================================




    

# ================================================
# 查詢當下登入會員的所有訂單 API（該會員作為賣家的所有訂單）
# 回傳值: 
# List (內含每一筆訂單的 dict) 
# 個別訂單內容包含: 1. 訂單資料 (賽事資訊、媒合狀態、訂單編號、訂單金額、訂單成立時間、付款時間、付款狀態、出貨時間、出貨狀態、商品備註、票券圖片url、該筆訂單的賣家評分...等等)  2. 依訂單成立日期由新至舊排序

def get_seller_orders(seller_id: int) -> List[Dict]:
    query = """
        SELECT
            o.id AS order_id,
            o.status AS order_status,
            o.payment_status,
            o.shipment_status,
            o.match_requested_at,
            o.matched_at,
            o.created_at,
            o.paid_at,
            o.shipped_at,
            t.price,
            t.seat_number,
            t.seat_area,
            t.note,
            t.image_urls,
            t.created_at AS listed_at,
            g.game_date,
            g.start_time,
            g.team_home,
            g.team_away,
            g.stadium,
            r.score AS rating
        FROM orders o
        JOIN tickets_for_sale t ON o.ticket_id = t.id
        JOIN games g ON t.game_id = g.id
        LEFT JOIN ratings r ON r.order_id = o.id AND r.rater_id = o.buyer_id
        WHERE o.seller_id = %s
        ORDER BY o.created_at DESC
    """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query,(seller_id,))
            rows = cursor.fetchall()
            return rows

# ----------------
# orders, tickets_for_sale, games 三張表 LEFT JOIN ratings 表: 
# 1.確保若該筆訂單還沒有賣家評分 (右表 ratings 無對應資料), 仍會列出左表資料 (orders, tickets_for_sale, games), 並在右表(ratings)沒對應資料的欄位補上 NULL
# 2.語意正確：一筆訂單 -> 一筆評分 (若一筆訂單有多筆評分, 就要用AVG和GROUP_BY做聚合)
# 3.可讀性高：一看就知道 rating 是單筆資料
# ================================================
            



# ================================================
# 更新訂單狀態、更新票券販售狀態、插入通知、寄信通知
# Database Transaction: 
# (1)先 SELECT orders 確認訂單存在、有操作權限、且訂單狀態現為媒合中 (2) (決定要更新的訂單狀態是什麼,)再 UPDATE 訂單狀態為「媒合成功」或「媒合失敗」(3)若訂單狀態更新為媒合成功, 將票券 is_sold UPDATE 為 True (4) 然後 INSERT 一筆通知進通知資料表 (5) 最後 SELECT members 查詢買家資料(同時先暫存買家資料進 notification_data變數) (6) Commit (7) Commit 成功後，才寄信 (呼叫 send_email_async 發送 SQS 任務（或 fallback 同步寄信）)

# 流程說明：
# - conn.commit() 執行完畢後，才呼叫 send_email_async
# - send_email_async 是同步函數，執行完畢後才會返回
# - send_email_async 內部設計為「永不 raise」，無論成功或失敗都正常結束
# - send_email_async 返回後，本函數到達尾端，流程返回 router 層
# - 真正的「非同步」是 Lambda 從 SQS 取出任務並寄信，與本函數無關

# 本函數無回傳值

def update_order_and_ticket_status(order_id: int, seller_id: int, action: str) -> None:
    notification_data = None       # 在 with conn 外面先初始化 notification_data (「先初始化」是防禦性設計)
    
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            # 1. 確認訂單存在、有操作權限(只有賣家可以更新訂單狀態)、且訂單狀態現為媒合中
            cursor.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            order = cursor.fetchone()
            if not order:
                raise HTTPException(404, "訂單不存在")
            if order["seller_id"] != seller_id:
                raise HTTPException(403, "無權限操作此訂單")
            if order["status"] != "媒合中":
                raise HTTPException(400, "目前狀態無法執行此操作")

            # 2. 決定新狀態是「媒合成功」或「媒合失敗」
            if action == "accept":
                new_status = "媒合成功"
            elif action == "reject":
                new_status = "媒合失敗"
            else:
                raise HTTPException(400, "無效操作")
            
            # 3. 更新訂單狀態為「媒合成功」或「媒合失敗」
            now = utc_now()

            cursor.execute("""
                UPDATE orders
                SET status=%s, matched_at=%s
                WHERE id=%s
            """, (new_status, now, order_id))

            # 4. 如果新狀態是 accept (媒合成功)，就把此票券標為「已售出」(將 tickets_for_sale 表的 is_sold 欄位更新為 True )
            if action == "accept":
                cursor.execute("""
                    UPDATE tickets_for_sale
                    SET is_sold=TRUE
                    WHERE id=%s
                """, (order["ticket_id"],))

            # 5. 新增一筆通知 (通知買家 媒合結果是「成功」或「失敗」)
            msg = f"您的訂單 #{order_id} 的媒合結果為：{'成功' if action=='accept' else '失敗'}"
            cursor.execute("""
                INSERT INTO notifications (member_id, message, url)
                VALUES (%s, %s, %s)
            """, (order["buyer_id"], msg, "/member_buy"))
            
            
            # 6. 查詢買家 Email (SELECT email FROM members)
            buyer_email = get_member_email(cursor, order["buyer_id"])
            
            # 暫存通知資料，等 commit 後再寄信 (提升 API 回應效率, 避免因寄信問題影響前述核心功能的操作)
            notification_data = {
                "to": buyer_email,
                "subject": "Pitch-A-Seat 訂單媒合結果通知",
                "body": f"您的訂單 #{order_id} 媒合結果為：{'成功' if action=='accept' else '失敗'}\n請至我的購買頁查看詳情"
            }

        conn.commit()  # 7. 先 commit

    # commit 成功後，才寄信 (發送任務到 SQS Queue 裡) 
    if notification_data:
        send_email_async(
            to=notification_data["to"],
            subject=notification_data["subject"],
            body=notification_data["body"]
        )
    


    # 在 with conn 外面初始化 notification_data (防禦性設計):
    # 原寫法是「把 notification_data={...} 寫在 with 裡面」: 依目前的程式碼, 沒有先初始化也不會有問題. 但若之後修改 with 區塊裡的程式碼邏輯而發生「程式碼沒跑到 notification_data={...} 這行, 卻又在 commit之後走到 if notification_data:這行」的情形時, 就會發生 NameError, 因為這時候 notification_data 根本還沒被宣告(定義/賦值). 新寫法有先在with區塊外面初始化notification_data = None, 若發生前述情形, 也會因為有先初始化為None, 變成 if None, 也就是 if Falsy, 結果是「不進入 if 區塊」也「不報錯」)


# ================================================





# ================================================
# 要執行付款前, 先檢查訂單是否存在、有操作訂單權限(只有買家有權限付款)、訂單狀態現為「媒合成功」、付款狀態現為「未付款」
# 然後取得訂單金額存入 amount 變數後, 回傳 amount (int) 和 order (dict)

def get_payable_orders(order_id:int, buyer_id:int) -> tuple[int, Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT
                    o.*,
                    t.price
                FROM orders o
                JOIN tickets_for_sale t ON o.ticket_id = t.id
                WHERE o.id = %s
            """, (order_id,))
            order = cursor.fetchone()
            if not order:
                raise HTTPException(status_code=404, detail="訂單不存在")
            if order["buyer_id"] != buyer_id:
                raise HTTPException(status_code=403, detail="無權限操作此訂單")
            # 只有在「媒合成功」且「未付款」的狀態下, 才能進行付款
            if order["status"] != "媒合成功" or order["payment_status"] != "未付款":
                raise HTTPException(status_code=400, detail="目前訂單狀態無法執行付款")
            # 取得訂單金額
            amount = order["price"]
            
            return amount, order

# 此函數只執行一次 SELECT，不涉及多個操作的原子性需求，不需要 Transaction
# ================================================





# ================================================            
# 在 payments 表先建立一筆新的付款資料 (INSERT INTO payments 建立一筆付款紀錄), 作法: 
# 1. 將 payments 資料表的該筆付款資料的 tappay_status 設為 UNPAID
# 2. 插入本筆付款的金額 (DB 的 amount 欄位設定為 NOT NULL, 所以建立新一筆付款紀錄時必須記得手動插入amount) 

# 回傳值: 這筆付款資料的 id, 目的: API 後續流程會使用 payment_id 來更新付款資料 (eg. 「更新該筆付款資料的tappay_status 為 FAILED」或「更新該筆付款資料的 tappay 相關付款資訊」)
def create_payment_unpaid(order_id: int, amount: int) -> int:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            insert_pay = """
                INSERT INTO payments
                (order_id, amount, tappay_status)
                VALUES (%s, %s, %s)
            """
            cursor.execute(insert_pay, (order_id, amount, "UNPAID"))
            payment_id = cursor.lastrowid
        conn.commit() 
    return payment_id 
# ================================================




# ================================================ 
# (1)第三方 TAPPAY API 呼叫失敗: Called by「mark_payment_failed_due_to_api_error 函數」, 不傳入tappay_status_code, 走進 if
# 更新 付款資料 的 tappay_status欄位、tappay_status_message欄位 

# (2)TapPay 授權付款失敗 (TapPay API 呼叫成功, 但後續付款失敗): Called by「mark_payment_failed_due_to_decline 函數」, 會傳入tappay_status_code, 走進 else
# 更新 付款資料 的 tappay_status欄位、tappay_status_message欄位、 tappay_status_code欄位
def mark_payment_failed(payment_id: int, tappay_status_message:str, tappay_status_code: Optional[int] = None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:            
            if tappay_status_code is None: 
                cursor.execute("""
                    UPDATE payments 
                    SET tappay_status=%s, 
                        tappay_status_message=%s 
                    WHERE id=%s
                """,("FAILED", tappay_status_message, payment_id)
                )
            else:
                cursor.execute("""
                    UPDATE payments 
                    SET tappay_status=%s,
                        tappay_status_code=%s,
                        tappay_status_message=%s 
                    WHERE id=%s
                """,("FAILED", tappay_status_code, tappay_status_message, payment_id)
                )
        conn.commit()

# mark_payment_failed 函數不算 Transaction, 因為只會有一個資料庫操作 (if or else)
# mark_payment_failed 函數不會有 race condition
# commit 原因: 確保 UPDATE 被持久化寫入資料庫
# ================================================




# ================================================
# 因呼叫第三方 TapPay API 失敗 (eg. DNS問題、網路中斷、TapPay本身掛掉), 而必須 UPDATE payments 資料表:
# (1) 將 付款資料 的 tappay_status 欄位更新為 FAILED (2) 將 付款資料 的 tappay_status_message 欄位更新為「"TapPay API 呼叫失敗"」(自定義的錯誤訊息)
# 無回傳值。UPDATE 完成後，函數結束，流程自動返回 router 層

def mark_payment_failed_due_to_api_error(payment_id: int, tappay_status_message:str) -> None:
    mark_payment_failed(payment_id, tappay_status_message)
# ================================================




# ================================================
# 因 TapPay 授權付款失敗 (呼叫 TapPay API 成功, 但後續付款失敗) (eg. 信用卡額度不足), 而必須 UPDATE payments 資料表:
# (1) 將 付款資料 的 tappay_status 欄位更新為 FAILED (2) 將 付款資料 的 tappay_status_code 欄位更新為「TapPay 回傳的官方付款結果碼」(3)將 付款資料 的 tappay_status_message 欄位更新為「TapPay 回傳的官方訊息 (非自定義的錯誤訊息)」
# 無回傳值。UPDATE 完成後，函數結束，流程自動返回 router 層

def mark_payment_failed_due_to_decline(payment_id: int, tappay_status_message:str, tappay_status_code: int) -> None:
    mark_payment_failed(payment_id, tappay_status_message, tappay_status_code)
# ================================================



# ================================================
# TapPay官方授權付款成功後, 更新 該筆付款資料的各個欄位內容

# Transaction: 
# (1) 將 付款資料 的 tappay_status 欄位更新為 「PAID」、payed_at 欄位更新為「現在(UTC時間)」、tappay_transaction_id 欄位更新為「TapPay官方 rec 交易識別碼」、tappay_bank_transaction_id 欄位更新為「TapPay官方 bank 交易識別碼」、tappay_status_code 欄位更新為「TapPay官方付款結果碼」、tappay_status_message 欄位更新為「TapPay官方訊息內容 (非自定義內容)」(UPDATE payments)
# (2) 將 訂單資料 的 payment_status 欄位更新為「已付款」、paid_at 欄位更新為「現在(UTC時間)」(UPDATE orders)
# (3) 新增一筆通知 (INSERT INTO notifications)
# (4) 取得賣家 email (SELECT email FROM members) & 暫存通知資訊到 notification_data 變數中
# (5) Transaction Commit
# (6) Commit 成功後，才寄信 (發送任務到 SQS Queue 裡)


# 流程說明：
# - conn.commit() 執行完畢後，才呼叫 send_email_async
# - send_email_async 是同步函數，執行完畢後才會返回
# - send_email_async 內部設計為「永不 raise」，無論成功或失敗都正常結束
# - send_email_async 返回後，本函數到達尾端，流程返回 router 層
# - 真正的「非同步」是 Lambda 從 SQS 取出任務並寄信，與本函數無關

# 此函數無回傳值


def commit_payment_success_tx(
    payment_id:int, 
    order_id:int, 
    order: Dict[str, Any], 
    amount:int, 
    tappay_rec_trade_id:str, 
    tappay_bank_txn_id:str, 
    tappay_status_code:int, 
    tappay_official_msg:str 
) -> None:
    
    notification_data = None  # 在 with conn 外面先初始化 notification_data (「先初始化」是防禦性設計)

    with get_connection() as conn:
        try:
            with conn.cursor(dictionary=True) as cursor:
                # 1. 更新 付款資料 的 tappay_status 、payed_at 、tappay_transaction_id 、tappay_bank_transaction_id、tappay_status_code、tappay_status_message (UPDATE payments)
                cursor.execute(
                    """
                    UPDATE payments
                    SET tappay_status=%s,
                        payed_at=%s,
                        tappay_transaction_id=%s,
                        tappay_bank_transaction_id=%s,
                        tappay_status_code=%s,
                        tappay_status_message=%s
                    WHERE id=%s
                    """,
                    (
                        "PAID",
                        utc_now(),
                        tappay_rec_trade_id,
                        tappay_bank_txn_id,
                        tappay_status_code,
                        tappay_official_msg,
                        payment_id,
                    ),
                )
                # 2. 更新 訂單資料 的 payment_status、paid_at (UPDATE orders)
                cursor.execute(
                    """
                    UPDATE orders
                    SET payment_status=%s,
                        paid_at=%s
                    WHERE id=%s
                    """,
                    ("已付款", utc_now(), order_id),
                )
                # 3. 新增一筆通知 (INSERT INTO notifications), 通知賣家「訂單#X(編號) 已付款，請出貨」
                msg = f"訂單 #{order_id} 已付款，請出貨"
                cursor.execute(
                    """
                    INSERT INTO notifications (member_id, message, url)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        order["seller_id"],
                        msg,
                        "/member_sell"
                    ),
                )
                
                # 4.1 查詢賣家 Email（在 commit 前查，因為 SELECT email FROM members 需要 cursor）
                seller_email = get_member_email(cursor, order["seller_id"])

                # 4.2 暫存通知資訊到 notification_data 變數中. Commit 成功後，才寄信
                notification_data = {
                    "to": seller_email,
                    "subject": "Pitch-A-Seat 訂單付款通知",
                    "body": f"訂單 #{order_id} 已付款，金額：{amount} 元\n請盡快安排出貨，詳情請至：我的售票頁"
                }
            
            # 5. Transaction Commit
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # 6. Commit 成功後，才寄信 (發送任務到 SQS Queue 裡)
    if notification_data:
        send_email_async(
            to=notification_data["to"],
            subject=notification_data["subject"],
            body=notification_data["body"]
        )        
# ================================================




# ================================================
# 更新 訂單資料 的 出貨狀態為「已出貨」、更新出貨時間為「現在(UTC時間)」
# 使用「原子更新 (防止 race condition: eg. 使用者連擊兩次出貨按鈕, 可能導致買家重複收到兩封出貨通知信, 但第一次點擊按鈕時就已經出貨了, 只需要一封通知信即可)」

# 「原子更新」作法: 只針對「存在的訂單」、「操作出貨者為賣家本人」、「付款狀態為已付款」且「出貨狀態為未出貨」的訂單資料, 進行「出貨狀態的更新」
# 1.若任一條件不符合, 就不會執行更新, cursor.rowcount 會是 0 (表示沒操作任何資料), 再由 router層 檢查實際問題並回傳對應的不同狀態碼)
# 2.若條件符合, 才會進行「訂單資料的出貨狀態更新」, 並回傳 cursor.rowcount 是 1 (表示操作資料筆數為 1)

# 回傳值: 受影響的行數 (操作資料筆數)（ 0 表示資料庫更新失敗, 1 表示資料庫成功更新一筆資料 ）
def update_order_shipped_atom(cursor, shipped_time: datetime, order_id: int, seller_id: int) -> int:
    cursor.execute("""
        UPDATE orders
        SET shipment_status='已出貨', shipped_at=%s
        WHERE id=%s
        AND seller_id=%s
        AND payment_status='已付款'
        AND shipment_status='未出貨'
    """, (shipped_time, order_id, seller_id))

    return cursor.rowcount
# ================================================




# ================================================
# 依 訂單編號 查詢 該筆訂單資料, 在 router 層檢查是訂單的什麼問題導致原子更新失敗
# 回傳值: 訂單資料的 dict
def get_order_by_id(cursor, order_id: int) -> Optional[Dict[str, Any]]:
    cursor.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
    order = cursor.fetchone()

    return order
# ================================================




# ================================================
# 新增一筆通知進資料表 (INSERT INTO notifications)
def notify_shipped(cursor, member_id: int, message: str, url: str) -> None:
    cursor.execute("""
        INSERT INTO notifications (member_id, message, url)
        VALUES (%s, %s, %s)
    """, (member_id, message, url))
# ================================================


