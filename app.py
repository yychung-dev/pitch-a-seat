from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import date, timedelta, datetime

from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import json, os, sys, shutil, uuid, io
from dotenv import load_dotenv
from dbconf import cnxpool
import mysql.connector
from PIL import Image


# ===== 基本設定 =====
load_dotenv()
app = FastAPI()

# Static templates (not actually used in API, but kept if needed)
templates = Jinja2Templates(directory="static")

# ===== 靜態 HTML 頁面路由 =====
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse("./static/index.html", media_type="text/html")

@app.get("/membership", include_in_schema=False)
async def membership():
    return FileResponse("./static/membership.html", media_type="text/html")

@app.get("/sell", include_in_schema=False)
async def sell():
    return FileResponse("./static/sell.html", media_type="text/html")

@app.get("/events", include_in_schema=False)
async def events():
    return FileResponse("./static/events.html", media_type="text/html")

@app.get("/browse", include_in_schema=False)
async def browse_page():
    return FileResponse("./static/browse.html", media_type="text/html")


# ===== 環境變數檢查 =====
required_vars = ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME"]
missing = [var for var in required_vars if os.getenv(var) is None]
if missing:
    print("缺少以下環境變數：")
    for var in missing:
        print(f" - {var}")
    print("請確認 .env 設定正確")
    sys.exit(1)

# ===== CORS 設定 =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 上線時，要限制來源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Pydantic Model =====
class Game(BaseModel):
    game_date: date
    stadium: str
    game_number: str
    team_home: str
    team_away: str
    start_time: str  # 格式為 HH:MM，已轉字串

class MatchResponse(BaseModel):
    game_id: int
    game_number: str

class TicketOut(BaseModel):
    id: int
    game_id: int
    seat_number: str
    seat_area: str
    price: int
    image_urls: List[str]
    is_sold: bool



# ===== 賽程 API =====
@app.get("/api/schedule", response_model=List[Game])
def get_schedule(year: int, month: int):
    try:
        query = """
            SELECT game_date, stadium, game_number, team_home, team_away, start_time
            FROM games
            WHERE YEAR(game_date) = %s AND MONTH(game_date) = %s
            ORDER BY game_date, start_time
        """
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, (year, month))
                results = cursor.fetchall()

                # 將 start_time（timedelta）轉為 HH:MM 格式字串
                for row in results:
                    if isinstance(row["start_time"], timedelta):
                        total_seconds = int(row["start_time"].total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        row["start_time"] = f"{hours:02}:{minutes:02}"

                return results

    except Exception as e:
        print("資料庫錯誤:", e)
        raise HTTPException(status_code=500, detail="資料庫錯誤")

# ===== 自動找出場次編號 =====
@app.get("/api/match", response_model=MatchResponse)
def get_match(date: str, stadium: str, team1: str, team2: str):
    query = """
        SELECT id, game_number FROM games
        WHERE game_date = %s AND stadium = %s
        AND ((team_home = %s AND team_away = %s) OR (team_home = %s AND team_away = %s))
        LIMIT 1
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, (date, stadium, team1, team2, team2, team1))
                row = cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="查無此場次")
                return {"game_id": row["id"], "game_number": row["game_number"]}
    except Exception as e:
        print("錯誤:", e)
        raise HTTPException(status_code=500, detail="資料庫錯誤")

# ===== 票券上架（多張） =====
@app.post("/api/sell_tickets")
async def sell_tickets(
    game_id: int = Form(...),
    tickets: str = Form(...),  # JSON 格式：[{seat_number, seat_area, price, note}, {...}]
    images: List[UploadFile] = File(...),
	seller_id:int=2
):
    try:
        # 圖片驗證設定
        allowed_exts = {"jpg", "jpeg", "png"}
        max_size_mb = 5

        # 儲存圖片
        image_folder = "static/uploads"
        os.makedirs(image_folder, exist_ok=True)
        img_map = {}

        for image in images:
            filename = image.filename
            ext = filename.split(".")[-1].lower()

            # 副檔名檢查
            if ext not in allowed_exts:
                raise HTTPException(status_code=400, detail=f"不支援的圖片格式：{filename}")

            # 大小檢查
            contents = await image.read()
            size_mb = len(contents) / 1024 / 1024
            if size_mb > max_size_mb:
                raise HTTPException(status_code=400, detail=f"圖片過大（超過5MB）：{filename}")

            # 圖片有效性檢查
            try:
                Image.open(io.BytesIO(contents)).verify()
            except Exception:
                raise HTTPException(status_code=400, detail=f"無效圖片檔案：{filename}")

            # 重新命名後儲存
            uuid_name = f"{uuid.uuid4()}.{ext}"
            filepath = os.path.join(image_folder, uuid_name)
            with open(filepath, "wb") as f:
                f.write(contents)

            index = filename.split("_")[0]  # e.g., 0_img1.jpg -> "0"
            img_map.setdefault(index, []).append(f"/static/uploads/{uuid_name}")

        # 回復游標位置，準備後續操作
        ticket_list = json.loads(tickets)

        insert_query = """
            INSERT INTO tickets_for_sale
            (seller_id, game_id, price, seat_number, seat_area, image_urls, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """

        with cnxpool.get_connection() as conn:
            with conn.cursor() as cursor:
                for idx, ticket in enumerate(ticket_list):
                    imgs = img_map.get(str(idx), [])
                    cursor.execute(insert_query, (
                        seller_id,
						game_id,
                        ticket["price"],
                        ticket["seat_number"],
                        ticket["seat_area"],
                        json.dumps(imgs),
                        ticket.get("note", "")
                    ))
            conn.commit()

        return {"status": "success", "count": len(ticket_list)}

    except HTTPException:
        raise  # 保持原樣拋出 HTTP 錯誤
    except Exception as e:
        print("其他錯誤:", e)
        raise HTTPException(status_code=500, detail="票券上架失敗")

# ===== 查詢所有可售票券 =====
@app.get("/api/tickets", response_model=List[TicketOut])
def get_all_tickets():
    try:
        query = """
            SELECT id, game_id, seat_number, seat_area, price, image_urls, is_sold
            FROM tickets_for_sale
            WHERE is_sold = FALSE
        """
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
                for row in results:
                    row["image_urls"] = json.loads(row["image_urls"])
                return results
    except Exception as e:
        print("錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢票券失敗")



# 查詢當月所有 tickets_for_sale 中 is_sold = FALSE 的票券。統計每場比賽的「熱賣中票數」。結合 games 表，回傳每場比賽資訊＋票數統計。

@app.get("/api/events")
def get_event_games(year: int, month: int):
    query = """
        SELECT
            g.id AS game_id,
            g.game_date,
            g.game_number,
            g.team_home,
            g.team_away,
            g.stadium,
            g.start_time,
            COUNT(t.id) AS ticket_count
        FROM games g
        JOIN tickets_for_sale t ON g.id = t.game_id
        WHERE t.is_sold = FALSE
          AND YEAR(g.game_date) = %s
          AND MONTH(g.game_date) = %s
        GROUP BY g.id
        ORDER BY g.game_date
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, (year, month))
                results = cursor.fetchall()

                for row in results:
                    if isinstance(row["start_time"], timedelta):
                        total_seconds = int(row["start_time"].total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        row["start_time"] = f"{hours:02}:{minutes:02}"

                return results

    except Exception as e:
        print("錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢售票場次失敗")


### FastAPI 後端 API: /api/browse_tickets
@app.get("/api/browse_tickets")
def browse_tickets(
    game_id: int,
    sort_by: Optional[str] = Query("created_at", enum=["created_at", "price", "rating"]),
    sort_order: Optional[str] = Query("desc", enum=["asc", "desc"]),
    seat_areas: Optional[str] = None  # e.g., "內野,外野"
):
    try:
        seat_filters = seat_areas.split(",") if seat_areas else []

        sort_column = {
            "created_at": "t.created_at",
            "price": "t.price",
            "rating": "IFNULL(avg_rating, 0)"
        }[sort_by]

        order = "ASC" if sort_order == "asc" else "DESC"

        query = f"""
            SELECT
                t.id, t.game_id, t.seat_number, t.seat_area, t.price,
                t.image_urls, t.note, t.created_at, g.game_date, g.stadium, g.team_home, g.team_away, g.start_time
            FROM tickets_for_sale t
			JOIN games g ON t.game_id = g.id
            WHERE t.game_id = %s AND t.is_sold = FALSE
        """
		# 等建好會員系統有seller_id之後，再加回：
		# query = f"""
        #     SELECT
        #         t.id, t.game_id, t.seat_number, t.seat_area, t.price,
        #         t.image_urls, t.note, t.created_at, g.game_date, g.stadium, g.team_home, g.team_away, g.start_time,m.name AS seller_name,
        #         AVG(r.score) AS avg_rating
        #     FROM tickets_for_sale t
		# 	  JOIN games g ON t.game_id = g.id
        #     JOIN members m ON t.seller_id = m.id
        #     LEFT JOIN ratings r ON r.ratee_id = m.id
        #     WHERE t.game_id = %s AND t.is_sold = FALSE
        # """
        params = [game_id]

        if seat_filters:
            query += f" AND t.seat_area IN ({', '.join(['%s'] * len(seat_filters))})"
            params.extend(seat_filters)

        query += " GROUP BY t.id ORDER BY " + sort_column + " " + order # 沒有seller_id的情況下，這行可有可無。

        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, tuple(params))
                results = cursor.fetchall()
                for row in results:
                    row["image_urls"] = json.loads(row["image_urls"])
                    row["start_time"] = str(row["start_time"])[:5]	# 加上這行
                return results

    except Exception as e:
        print("錯誤:", e)
        return JSONResponse(status_code=500, content={"detail": "查詢票券失敗"})


# 新增評分的 API /api/ratings
class RatingIn(BaseModel):
    rater_id: int     # 評分者（未來會員系統整合時使用）
    ratee_id: int     # 被評分者（目前為賣家）
    score: int        # 1~5 顆星
    ticket_id: int    # 對哪筆 ticket 評分

@app.post("/api/ratings")
def create_rating(rating: RatingIn):
    if not 1 <= rating.score <= 5:
        raise HTTPException(status_code=400, detail="評分需介於 1~5 顆星")
    
    query = """
        INSERT INTO ratings (rater_id, ratee_id, score, ticket_id)
        VALUES (%s, %s, %s, %s)
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (
                    rating.rater_id,
                    rating.ratee_id,
                    rating.score,
                    rating.ticket_id
                ))
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        print("評分寫入錯誤:", e)
        raise HTTPException(status_code=500, detail="評分寫入失敗")

# 用來送出「買家要求媒合」，會建立一筆 orders 訂單，狀態為「等待賣家接受或拒絕」。
# 送出媒合請求（建立新訂單）
@app.post("/api/match_request")
def request_match(ticket_id: int, buyer_id: int = 1):  # 假設 buyer_id = 1，之後建好會員系統再改從jwt取值。
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                # 確認票券存在且尚未被媒合
                cursor.execute("SELECT is_sold FROM tickets_for_sale WHERE id = %s", (ticket_id,))
                ticket = cursor.fetchone()
                if not ticket:
                    raise HTTPException(status_code=404, detail="找不到票券")
                if ticket["is_sold"]:
                    raise HTTPException(status_code=400, detail="此票券已售出")
                # 建立新訂單（狀態設為「媒合中」）
                cursor.execute("SELECT seller_id FROM tickets_for_sale WHERE id = %s", (ticket_id,))
                seller = cursor.fetchone()
                seller_id=seller["seller_id"]
                cursor.execute("""
                    INSERT INTO orders (ticket_id, buyer_id, seller_id, status, match_requested_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (ticket_id, buyer_id, seller_id,"媒合中", datetime.now()))
                conn.commit()
                return {"status": "success", "message": "媒合請求已送出"}
    except Exception as e:
        print("媒合錯誤:", e)
        raise HTTPException(status_code=500, detail="媒合請求失敗")


# 取得特定會員的所有訂單（買家為該會員）

@app.get("/api/buyerOrders")
def get_buyerOrders(member_id: int = Query(...)): 
    try:
        query = """
            SELECT
                o.id AS order_id,
                o.status AS order_status,
                o.payment_status,
                o.shipment_status,
                o.match_requested_at,
                o.matched_at,
                t.price, t.seat_number, t.seat_area, t.created_at AS listed_at,
                g.game_date, g.start_time, g.team_home, g.team_away, g.stadium
            FROM orders o
            JOIN tickets_for_sale t ON o.ticket_id = t.id
            JOIN games g ON t.game_id = g.id
            WHERE o.buyer_id = %s
            ORDER BY o.id DESC
        """
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, (member_id,))
                rows = cursor.fetchall()

                for row in rows:
                    row["start_time"] = str(row["start_time"])[:5]
                    row["weekday"] = ["一", "二", "三", "四", "五", "六", "日"][row["game_date"].weekday()]
                    row["stadium_url"] = {
                        "台北大巨蛋": "https://maps.app.goo.gl/m53dt8TAUQkWXBvD9",
                        "新莊": "https://maps.app.goo.gl/evnUECyJsLx3rkaE8",
                        "天母": "https://maps.app.goo.gl/WGsmw7y38Apdkcsm7",
                        "洲際": "https://maps.app.goo.gl/U6ZfbxwGp1t9APvN7",
                        "台南": "https://maps.app.goo.gl/Y4SgmRbEBCehqaH89",
                        "澄清湖": "https://maps.app.goo.gl/T4wG6E4ED5jKnxaz6",
                        "花蓮": "https://maps.app.goo.gl/UCvKfG29V7uEUc4G6",
                    }.get(row["stadium"], "#")
                return rows
    except Exception as e:
        print("查詢訂單錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢訂單失敗")

# 取得特定會員的所有訂單（賣家為該會員）

@app.get("/api/sellerOrders")
def get_sellerOrders(member_id: int = Query(...)):  
    try:
        query = """
            SELECT
                o.id AS order_id,
                o.status AS order_status,
                o.payment_status,
                o.shipment_status,
                o.match_requested_at,
                o.matched_at,
                t.price, t.seat_number, t.seat_area, t.created_at AS listed_at,
                g.game_date, g.start_time, g.team_home, g.team_away, g.stadium
            FROM orders o
            JOIN tickets_for_sale t ON o.ticket_id = t.id
            JOIN games g ON t.game_id = g.id
            WHERE o.seller_id = %s
            ORDER BY o.id DESC
        """
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, (member_id,))
                rows = cursor.fetchall()

                for row in rows:
                    row["start_time"] = str(row["start_time"])[:5]
                    row["weekday"] = ["一", "二", "三", "四", "五", "六", "日"][row["game_date"].weekday()]
                    row["stadium_url"] = {
                        "台北大巨蛋": "https://maps.app.goo.gl/m53dt8TAUQkWXBvD9",
                        "新莊": "https://maps.app.goo.gl/evnUECyJsLx3rkaE8",
                        "天母": "https://maps.app.goo.gl/WGsmw7y38Apdkcsm7",
                        "洲際": "https://maps.app.goo.gl/U6ZfbxwGp1t9APvN7",
                        "台南": "https://maps.app.goo.gl/Y4SgmRbEBCehqaH89",
                        "澄清湖": "https://maps.app.goo.gl/T4wG6E4ED5jKnxaz6",
                        "花蓮": "https://maps.app.goo.gl/UCvKfG29V7uEUc4G6",
                    }.get(row["stadium"], "#")
                return rows
    except Exception as e:
        print("查詢訂單錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢訂單失敗")




# 賣家接受或拒絕媒合請求：賣家點擊「成交」或「拒絕」後，更新訂單狀態（並記錄 matched_at 時間）。並新增通知：通知買家處理結果。
# 把「接受媒合」功能改成 transaction，一併更新票券狀態：把原先分開的更新合併在同一個 DB transaction，確保要嘛全成功要嘛 rollback。
# 接受 (accept) 時同步把 tickets_for_sale.is_sold 標為 TRUE，避免重複媒合。

#  POST /api/order_status

@app.post("/api/order_status")
def update_order_status(
	order_id: int = Body(...),
    action:   str = Body(...),
    seller_id:int = Body(...)
):
    """
    action: "accept" or "reject"
    在同一個 transaction 裡：
      1. 檢查訂單存在、狀態為「媒合中」、屬於這位賣家
      2. 根據 action 更新 orders.status, matched_at
      3. (accept 時) 把 tickets_for_sale.is_sold = TRUE
      4. 新增通知給買家
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                # 1. 讀訂單並驗證
                cursor.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
                order = cursor.fetchone()
                if not order:
                    raise HTTPException(404, "訂單不存在")
                if order["seller_id"] != seller_id:
                    raise HTTPException(403, "無權限操作此訂單")
                if order["status"] != "媒合中":
                    raise HTTPException(400, "目前狀態無法執行此操作")

                # 2. 決定新狀態
                if action == "accept":
                    new_status = "媒合成功"
                elif action == "reject":
                    new_status = "媒合失敗"
                else:
                    raise HTTPException(400, "無效操作")

                now = datetime.now()
                # 3. 更新訂單
                cursor.execute("""
                    UPDATE orders
                    SET status=%s, matched_at=%s
                    WHERE id=%s
                """, (new_status, now, order_id))

                # 4. 如果是 accept，就把票券標為已售
                if action == "accept":
                    cursor.execute("""
                        UPDATE tickets_for_sale
                        SET is_sold=TRUE
                        WHERE id=%s
                    """, (order["ticket_id"],))

                # 5. 新增通知
                cursor.execute("""
                    INSERT INTO notifications (member_id, message, url)
                    VALUES (%s, %s, %s)
                """, (
                    order["buyer_id"],
                    f"您對訂單 #{order_id} 的媒合結果為：{'成功' if action=='accept' else '失敗'}",
                    "/membership"
                ))

            conn.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        print("更新訂單失敗：", e)
        raise HTTPException(500, "更新失敗")


# 取得通知列表：讓會員登入後可以在右上角看到鈴鐺 icon 或通知列表（如有未讀通知）
# GET /api/notifications?member_id=1
@app.get("/api/notifications")
def get_notifications(member_id: int = 1):
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute("""
                    SELECT id, message, url, is_read, created_at
                    FROM notifications
                    WHERE member_id = %s
                    ORDER BY created_at DESC
                """, (member_id,))
                return cursor.fetchall()
    except Exception as e:
        print("查詢通知錯誤:", e)
        raise HTTPException(status_code=500, detail="通知查詢失敗")


# 買家付款：POST /api/pay_order
@app.post("/api/pay_order")
def pay_order(order_id: int = Body(..., embed=True), buyer_id: int = Body(..., embed=True)):
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                # 驗證訂單
                cursor.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
                order = cursor.fetchone()
                if not order:
                    raise HTTPException(404, "訂單不存在")
                if order["buyer_id"] != buyer_id:
                    raise HTTPException(403, "無權限操作此訂單")
                if order["status"] != "媒合成功" or order["payment_status"] != "未付款":
                    raise HTTPException(400, "目前狀態無法執行付款")

                # 更新付款
                now = datetime.now()
                cursor.execute("""
                    UPDATE orders
                    SET payment_status='已付款', paid_at=%s
                    WHERE id=%s
                """, (now, order_id))
                # 同步標綠票券已售出
                cursor.execute("""
                    UPDATE tickets_for_sale
                    SET is_sold=TRUE
                    WHERE id=%s
                """, (order["ticket_id"],))
                # 通知賣家
                cursor.execute("""
                    INSERT INTO notifications (member_id, message, url)
                    VALUES (%s, %s, %s)
                """, (order["seller_id"], f"訂單 #{order_id} 已付款，請出貨", "/membership"))
            conn.commit()
        return {"status":"success"}
    except HTTPException:
        raise
    except Exception as e:
        print("付款失敗：", e)
        raise HTTPException(500, "付款失敗")

# 賣家出貨：POST /api/mark_shipped
@app.post("/api/mark_shipped")
def mark_shipped(order_id: int = Body(..., embed=True), seller_id: int = Body(...)):
    """
    - 更新 orders.shipment_status -> '已出貨'
    - 更新 orders.shipped_at
    - 新增通知給買家
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                # 1. 驗證訂單
                cursor.execute("SELECT * FROM orders WHERE id=%s AND seller_id=%s", (order_id, seller_id))
                order = cursor.fetchone()
                if not order or order["payment_status"] != "已付款":
                    raise HTTPException(status_code=400, detail="無效訂單或尚未付款")
                # 2. 更新 orders
                now = datetime.now()
                cursor.execute("""
                    UPDATE orders
                    SET shipment_status='已出貨', shipped_at=%s
                    WHERE id=%s
                """, (now, order_id))
                # 3. 通知買家
                cursor.execute("""
                    INSERT INTO notifications (member_id, message, url)
                    VALUES (%s, %s, '/membership')
                """, (
                    order["buyer_id"],
                    f"訂單 #{order_id} 已出貨，請留意物流"
                ))
            conn.commit()
        return {"status":"success"}
    except HTTPException:
        raise
    except Exception as e:
        print("出貨錯誤：", e)
        raise HTTPException(status_code=500, detail="出貨失敗")

# 通知「已讀」機制：新增一個標記已讀的 API
@app.post("/api/mark_notifications_read")
def mark_notifications_read(member_id: int = Query(..., description="要標記已讀的會員ID")):
    """
    把所有 is_read = FALSE 的通知改成 TRUE，並回傳更新數量
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE notifications
                    SET is_read = TRUE
                    WHERE member_id = %s AND is_read = FALSE
                """, (member_id,))
                updated = cursor.rowcount
            conn.commit()
        return {"status": "success", "updated": updated}
    except Exception as e:
        print("標記通知已讀失敗：", e)
        raise HTTPException(status_code=500, detail="標記已讀失敗")




# 加這一行，讓 /static 目錄下的所有檔案都可以公開存取
app.mount("/static", StaticFiles(directory="static"), name="static")