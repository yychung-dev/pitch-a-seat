from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Body, Depends, Request, Header, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, ValidationError
from typing import List, Optional, Dict, Any, Union
from datetime import date, timedelta, datetime, time

from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import json, os, sys, shutil, uuid, io, asyncio
import bcrypt
import jwt
from dotenv import load_dotenv
from dbconf import cnxpool
import mysql.connector
from mysql.connector.pooling import PooledMySQLConnection

from PIL import Image
import httpx
from fastapi.responses import StreamingResponse

from email.message import EmailMessage
import smtplib
import math



# ===== 基本設定 =====
load_dotenv()
SECRET_KEY = os.getenv("JWT_SECRET_KEY") 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  

if not SECRET_KEY:
    print("❌ 必須在 .env 裡設定 JWT_SECRET_KEY")
    sys.exit(1)



SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

# SSE 全域佇列
reservation_subscribers: List[asyncio.Queue] = []

# 寄信函式
def send_email(to: str, subject: str, body: str):
    try:
        msg = EmailMessage()
        msg["From"]    = f"Pitch-A-Seat <{SMTP_USER}>"
        msg["To"]      = to
        msg["Subject"] = subject
        msg.set_content(body)
        # 連到 Gmail SMTP，啟用 TLS
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()           
            smtp.starttls()       
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
    except Exception as e:
        print(f"寄送 Email 至 {to} 失敗：{e}")


def get_member_email(cursor, member_id: int) -> str:
    cursor.execute("SELECT email FROM members WHERE id = %s", (member_id,))
    member = cursor.fetchone()
    if not member:
        raise HTTPException(status_code=404, detail=f"會員 ID {member_id} 不存在")
    return member["email"]


app = FastAPI()



# Static templates (not actually used in API, but kept if needed)
templates = Jinja2Templates(directory="static")

# Static Pages
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse("./static/index.html", media_type="text/html")

@app.get("/sell", include_in_schema=False)
async def sell():
    return FileResponse("./static/sell.html", media_type="text/html")

@app.get("/buy", include_in_schema=False)
async def buy_page():
    return FileResponse("./static/buy.html", media_type="text/html")

@app.get("/payment", include_in_schema=False)
async def payment_page():
    return FileResponse("./static/payment.html", media_type="text/html")

@app.get("/register", include_in_schema=False)
async def register_page():
    return FileResponse("./static/register.html", media_type="text/html")

@app.get("/reservation", include_in_schema=False)
async def reservation_page():
    return FileResponse("./static/reservation.html", media_type="text/html")

@app.get("/member_profile", include_in_schema=False)
async def member_profile():
    return FileResponse("./static/member_profile.html", media_type="text/html")

@app.get("/member_sell", include_in_schema=False)
async def member_sell():
    return FileResponse("./static/member_sell.html", media_type="text/html")

@app.get("/member_buy", include_in_schema=False)
async def member_buy():
    return FileResponse("./static/member_buy.html", media_type="text/html")

@app.get("/member_reservation", include_in_schema=False)
async def member_reservation():
    return FileResponse("./static/member_reservation.html", media_type="text/html") 

@app.get("/member_launch", include_in_schema=False)
async def member_launch():
    return FileResponse("./static/member_launch.html", media_type="text/html")    

# 環境變數檢查
required_vars = ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME"]
missing = [var for var in required_vars if os.getenv(var) is None]
if missing:
    print("缺少以下環境變數：")
    for var in missing:
        print(f" - {var}")
    print("請確認 .env 設定正確")
    sys.exit(1)

# TapPay 環境變數 
TAPPAY_PARTNER_KEY = os.getenv("TAPPAY_PARTNER_KEY")
TAPPAY_MERCHANT_ID = os.getenv("TAPPAY_MERCHANT_ID")
TAPPAY_ENV = os.getenv("TAPPAY_ENV", "sandbox")  
if not TAPPAY_PARTNER_KEY or not TAPPAY_MERCHANT_ID:
    print("缺少 TapPay 環境變數，請確認 .env 是否設定 TAPPAY_PARTNER_KEY / TAPPAY_MERCHANT_ID")
    sys.exit(1)

# ===== CORS 設定 =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 上線時改成限定網域
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Pydantic Model =====
class UserRegisterIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)   
    confirm_password: str
    phone: str = Field(..., pattern=r"^09\d{8}$")  
    city: Optional[str] = None
    favorite_teams: Optional[List[str]] = None   
    # subscribe_newsletter: Optional[bool] = False

class UserLoginIn(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserProfileOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    phone: str
    city: Optional[str]
    favorite_teams: Optional[List[str]]
    # subscribe_newsletter: bool
    created_at: datetime
    updated_at: datetime
    avg_rating: Union[float, None] = None  # 明確允許 None

class UserProfileUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)
    phone: Optional[str] = Field(None, pattern=r"^09\d{8}$")
    city: Optional[str] = None
    favorite_teams: Optional[List[str]] = None


class Game(BaseModel):
    id: int
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

class ReservationIn(BaseModel):
    game_id: int
    price_ranges: List[str]         
    seat_area: str                  # "none" / "內野" / "外野"


# JWT 相關函式 
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(authorization: str = Header(None)) -> Dict[str, Any]:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token payload invalid")
        return {"user_id": user_id, "name": payload.get("name"), "email": payload.get("email")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已過期，請重新登入")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="無效的 token")



# 會員註冊 API
@app.post("/api/user/register", response_model=TokenResponse)
def user_register(data: UserRegisterIn):
    if data.password != data.confirm_password:
        raise HTTPException(status_code=400, detail="密碼與確認密碼不符")
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute("SELECT id FROM members WHERE email = %s", (data.email,))
                if cursor.fetchone():
                    raise HTTPException(status_code=400, detail="此電子郵件已被註冊")
                cursor.execute("SELECT id FROM members WHERE name = %s", (data.name,))
                if cursor.fetchone():
                    raise HTTPException(status_code=400, detail="此姓名已被使用，請換一個")
                salt = bcrypt.gensalt()
                password_hash = bcrypt.hashpw(data.password.encode("utf-8"), salt).decode("utf-8")
                insert_query = """
                    INSERT INTO members
                    (name, email, password_hash, phone, city, favorite_teams)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                favorite_json = json.dumps(data.favorite_teams) if data.favorite_teams else None
                cursor.execute(insert_query, (
                    data.name,
                    data.email,
                    password_hash,
                    data.phone,
                    data.city,
                    favorite_json,
                ))
                conn.commit()
                new_id = cursor.lastrowid
    except HTTPException:
        raise
    except Exception as e:
        print("註冊時資料庫錯誤：", e)
        raise HTTPException(status_code=500, detail="註冊失敗，請稍後再試")


    access_token = create_access_token(
        data={"id": new_id, "email": data.email, "name": data.name},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token}


# 會員登入 API 
@app.post("/api/user/login", response_model=TokenResponse)
def user_login(data: UserLoginIn):
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute("SELECT id, name, email, password_hash FROM members WHERE email = %s", (data.email,))
                row = cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=400, detail="帳號或密碼錯誤")
                stored_hash = row["password_hash"].encode("utf-8")
                if not bcrypt.checkpw(data.password.encode("utf-8"), stored_hash):
                    raise HTTPException(status_code=400, detail="帳號或密碼錯誤")
                user_id = row["id"]
                name = row["name"]
    except HTTPException:
        raise
    except Exception as e:
        print("登入時資料庫錯誤：", e)
        raise HTTPException(status_code=500, detail="系統錯誤，請稍後再試")


    access_token = create_access_token(
        data={"id": user_id, "email": data.email, "name": name},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token}


# 檢查目前登入狀態 API
@app.get("/api/user/auth", response_model=Optional[UserProfileOut])
def check_auth(user: Dict[str, Any] = Depends(get_current_user)):
    user_id = user["user_id"]
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute("""
                    SELECT id, name, email, phone, city, favorite_teams, subscribe_newsletter, created_at, updated_at
                    FROM members WHERE id = %s
                """, (user_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                row["favorite_teams"] = json.loads(row["favorite_teams"]) if row["favorite_teams"] else []
                return row
    except Exception as e:
        print("檢查登入狀態時錯誤：", e)
        raise HTTPException(status_code=500, detail="伺服器錯誤")


# 取得或更新會員個人資料 API 
@app.get("/api/user/profile", response_model=UserProfileOut)
def get_profile(user: Dict[str, Any] = Depends(get_current_user)):
    user_id = user["user_id"]
    try:
        with cnxpool.get_connection() as conn:
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
                if not row:
                    raise HTTPException(status_code=404, detail="使用者不存在")
                row["favorite_teams"] = json.loads(row["favorite_teams"]) if row["favorite_teams"] else []
                row["avg_rating"] = float(row["avg_rating"]) if row["avg_rating"] is not None else None
                return row
    except Exception as e:
        print("取得個人資料時錯誤：", e)
        raise HTTPException(status_code=500, detail="伺服器錯誤")

# 取得或更新會員個人資料 API
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
import json
import bcrypt

@app.put("/api/user/profile", response_model=UserProfileOut)
def update_profile(
    data: UserProfileUpdateIn,
    user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = user["user_id"]
    update_fields = []
    update_vals = []

    try:
        # 檢查 email 唯一性
        if data.email is not None and data.email != user["email"]:
            try:
                with cnxpool.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT id FROM members WHERE email = %s AND id != %s", (data.email, user_id))
                        if cursor.fetchone():
                            raise HTTPException(status_code=409, detail="此電子郵件已被其他帳號使用")
            except HTTPException:
                raise
            except Exception as e:
                print("檢查 email 唯一性失敗：", e)
                raise HTTPException(status_code=500, detail="伺服器錯誤")

        # 建立更新部分
        if data.name is not None:
            update_fields.append("name = %s")
            update_vals.append(data.name)
        if data.email is not None:
            update_fields.append("email = %s")
            update_vals.append(data.email)
        if data.password is not None:
            salt = bcrypt.gensalt()
            pwd_hash = bcrypt.hashpw(data.password.encode("utf-8"), salt).decode("utf-8")
            update_fields.append("password_hash = %s")
            update_vals.append(pwd_hash)
        if data.phone is not None:
            update_fields.append("phone = %s")
            update_vals.append(data.phone)
        if data.city is not None:
            update_fields.append("city = %s")
            update_vals.append(data.city)
        if data.favorite_teams is not None:
            fav_json = json.dumps(data.favorite_teams)
            update_fields.append("favorite_teams = %s")
            update_vals.append(fav_json)

        if not update_fields:
            raise HTTPException(status_code=400, detail="沒有要更新的欄位")

        # 更新資料庫
        try:
            with cnxpool.get_connection() as conn:
                with conn.cursor() as cursor:
                    set_clause = ", ".join(update_fields)
                    update_vals.append(user_id)
                    query = f"UPDATE members SET {set_clause}, updated_at = NOW() WHERE id = %s"
                    cursor.execute(query, tuple(update_vals))
                    conn.commit()
        except Exception as e:
            print("更新個人資料失敗：", e)
            raise HTTPException(status_code=500, detail="更新失敗")

        # 更新後回傳最新資料
        return get_profile(user)

    except ValidationError as e:
        # 記錄驗證錯誤詳細資料
        print("Pydantic 驗證錯誤：", e.errors(), "輸入數據：", data.dict())
        return JSONResponse(
            status_code=422,
            content={"detail": [
                {"loc": err["loc"], "msg": err["msg"], "type": err["type"]}
                for err in e.errors()
            ]}
        )



# 賽程 API
@app.get("/api/schedule", response_model=List[Game])
def get_schedule(year: int, month: int):
    try:
        query = """
            SELECT id, game_date, stadium, game_number, team_home, team_away, start_time
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



# 取得累積交易次數 API
@app.get("/api/total_trades")
def get_total_trades():
    query = """
        SELECT COUNT(*) AS total_trades
        FROM orders
        WHERE shipment_status IN ('已出貨', '已結案')
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query)
                return cursor.fetchone()
    except Exception as e:
        print("錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢交易次數失敗")


# 取得累積交易金額 API
@app.get("/api/total_amount")
def get_total_amount():
    query = """
        SELECT SUM(p.amount) AS total_amount
        FROM orders o
        INNER JOIN payments p ON o.id = p.order_id
        WHERE o.shipment_status = '已出貨'
        AND p.tappay_status = 'PAID'
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query)
                result = cursor.fetchone()
                return {"total_amount": result["total_amount"] or 0}
    except Exception as e:
        print("錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢交易金額失敗")





# 自動找出場次編號 API
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


# 取得本月熱賣場次前五名排行榜 API
@app.get("/api/top_games")
def get_top_games():
    query = """
        SELECT 
            g.id AS game_id,
            g.game_date,
            g.team_home,
            g.team_away,
            COUNT(o.id) AS trade_count
        FROM games g
        JOIN tickets_for_sale t ON g.id = t.game_id
        JOIN orders o ON t.id = o.ticket_id
        WHERE o.payment_status = '已付款'
          AND o.shipment_status = '已出貨'
          AND YEAR(o.created_at) = YEAR(CURDATE())
          AND MONTH(o.created_at) = MONTH(CURDATE())
        GROUP BY g.id, g.game_date, g.team_home, g.team_away
        ORDER BY trade_count DESC
        LIMIT 5
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
                for row in results:
                    # 格式化 game_date 為 YYYY-MM-DD
                    if isinstance(row["game_date"], date):
                        row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
                return results
    except Exception as e:
        print("錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢排行榜失敗")


# 取得本月熱賣場次前五名票價中位數 API
@app.get("/api/top_games_median_prices")
def get_top_games_median_prices():
    query = """
        SELECT 
            g.id AS game_id,
            g.game_date,
            g.team_home,
            g.team_away,
            (
                SELECT AVG(tfs_inner.price)
                FROM tickets_for_sale tfs_inner
                JOIN orders o_inner ON tfs_inner.id = o_inner.ticket_id
                WHERE tfs_inner.game_id = g.id
                  AND o_inner.payment_status = '已付款'
                  AND o_inner.shipment_status = '已出貨'
                  AND YEAR(o_inner.created_at) = YEAR(CURDATE())
                  AND MONTH(o_inner.created_at) = MONTH(CURDATE())
                ORDER BY tfs_inner.price
                LIMIT 2
            ) AS median_price
        FROM games g
        JOIN tickets_for_sale t ON g.id = t.game_id
        JOIN orders o ON t.id = o.ticket_id
        WHERE o.payment_status = '已付款'
          AND o.shipment_status = '已出貨'
          AND YEAR(o.created_at) = YEAR(CURDATE())
          AND MONTH(o.created_at) = MONTH(CURDATE())
        GROUP BY g.id, g.game_date, g.team_home, g.team_away
        ORDER BY COUNT(o.id) DESC
        LIMIT 5
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
                for row in results:
                    # 格式化 game_date 為 YYYY-MM-DD
                    if isinstance(row["game_date"], date):
                        row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
                    # 確保 median_price 為整數
                    row["median_price"] = int(row["median_price"]) if row["median_price"] else 0
                return results
    except Exception as e:
        print("錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢票價中位數失敗")


# 取得本月球隊交易熱度排行 API
@app.get("/api/team_trade_rank")
def get_team_trade_rank():
    query = """
        SELECT 
            team,
            COUNT(*) AS trade_count
        FROM (
            SELECT g.team_home AS team
            FROM games g
            JOIN tickets_for_sale t ON g.id = t.game_id
            JOIN orders o ON t.id = o.ticket_id
            WHERE o.payment_status = '已付款'
              AND o.shipment_status = '已出貨'
              AND YEAR(o.created_at) = YEAR(CURDATE())
              AND MONTH(o.created_at) = MONTH(CURDATE())
            UNION ALL
            SELECT g.team_away AS team
            FROM games g
            JOIN tickets_for_sale t ON g.id = t.game_id
            JOIN orders o ON t.id = o.ticket_id
            WHERE o.payment_status = '已付款'
              AND o.shipment_status = '已出貨'
              AND YEAR(o.created_at) = YEAR(CURDATE())
              AND MONTH(o.created_at) = MONTH(CURDATE())
        ) AS teams
        GROUP BY team
        ORDER BY trade_count DESC
        LIMIT 6
    """
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
                return results
    except Exception as e:
        print("錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢球隊交易熱度失敗")



# 票券上架（多張）API
@app.post("/api/sell_tickets")
async def sell_tickets(
    game_id: int = Form(...),
    tickets: str = Form(...),                
    images: Optional[List[UploadFile]] = File(None),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        seller_id = current_user["user_id"]

        # 圖片相關初始化
        if images is None:
            images = []
        allowed_exts = {"jpg", "jpeg", "png"}
        max_size_mb = 5
        image_folder = "static/uploads"
        os.makedirs(image_folder, exist_ok=True)
        img_map: Dict[str, List[str]] = {}

        # 驗證並儲存圖片
        for image in images:
            ext = image.filename.rsplit(".", 1)[-1].lower()
            if ext not in allowed_exts:
                raise HTTPException(400, f"不支援的圖片格式：{image.filename}")
            contents = await image.read()
            if len(contents) / 1024 / 1024 > max_size_mb:
                raise HTTPException(400, f"圖片過大（超過5MB）：{image.filename}")
            try:
                Image.open(io.BytesIO(contents)).verify()
            except:
                raise HTTPException(400, f"無效圖片檔案：{image.filename}")

            new_name = f"{uuid.uuid4()}.{ext}"
            path = os.path.join(image_folder, new_name)
            with open(path, "wb") as f:
                f.write(contents)

            idx = image.filename.split("_", 1)[0]  
            img_map.setdefault(idx, []).append(f"/static/uploads/{new_name}")

        
        ticket_list = json.loads(tickets)

        insert_sql = """
            INSERT INTO tickets_for_sale
            (seller_id, game_id, price, seat_number, seat_area, image_urls, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """

        # 開一個連線，用同一個 transaction 同步上架 + 匹配
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                # 查詢 game_number
                cursor.execute("SELECT game_number FROM games WHERE id = %s", (game_id,))
                game = cursor.fetchone()
                if not game:
                    raise HTTPException(status_code=404, detail="賽事不存在")
                game_number = game["game_number"]
                
                # 1. 新增所有票券
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

                # 2. 抓出所有當前場次的訂閱紀錄
                cursor.execute("""
                    SELECT r.id, r.member_id, r.price_ranges, r.seat_area, m.email
                    FROM reservations r
                    JOIN members m ON r.member_id = m.id
                    WHERE r.game_id = %s
                """, (game_id,))
                reservations = cursor.fetchall()

                # 3. 針對每一張剛上架的票，和每筆預約比對
                for ticket in ticket_list:
                    price = ticket["price"]
                    area  = ticket["seat_area"]
                    for r in reservations:
                        price_ranges = json.loads(r["price_ranges"])
                        # 檢查價格是否符合
                        def in_range(pr: str) -> bool:
                            lo, hi = map(int, pr.split("-"))
                            # "0-0" 視為無要求
                            return (lo == hi == 0) or (lo <= price <= hi)
                        matched_price = any(in_range(pr) for pr in price_ranges)
                        # 檢查座位是否符合
                        matched_area = (r["seat_area"] == "none") or (r["seat_area"] == area)

                        if matched_price and matched_area:
                            msg = f"賽事 {game_number} 有新票：{area} / {price} 元"
                            # 4. 新增網站通知
                            cursor.execute("""
                                INSERT INTO notifications (member_id, message, url)
                                VALUES (%s, %s, %s)
                            """, (r["member_id"], msg, "/buy"))
                            # 5. 發送 Email
                            send_email(
                                to = r["email"],
                                subject = "Pitch-A-Seat 預約通知",
                                body = f"您預約的場次 {game_number} 有新票：\n座位：{area}\n價格：{price} 元"
                            )
                            # 6. 推送到所有 SSE 訂閱者
                            for q in reservation_subscribers:
                                q.put_nowait({
                                    "member_id": r["member_id"],
                                    "message": msg,
                                    "url": "/buy"
                                })

                # 最後一起 commit
                conn.commit()

        return {"status": "success", "count": len(ticket_list)}

    except HTTPException:
        raise
    except Exception as e:
        print("sell_tickets 失敗：", e)
        raise HTTPException(500, "票券上架失敗")




# 查詢所有可售票券 API
@app.get("/api/tickets", response_model=List[TicketOut])
def get_all_tickets():
    try:
        query = """
            SELECT id, game_id, seat_number, seat_area, price, image_urls, is_sold
            FROM tickets_for_sale
            WHERE is_sold = FALSE AND is_removed = FALSE
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


# 查詢賣家所有上架票券 API
@app.get("/api/sellerTickets")
def get_seller_tickets(user: Dict[str, Any] = Depends(get_current_user)):
    try:
        seller_id = user["user_id"]
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
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, (seller_id,))
                rows = cursor.fetchall()
                for row in rows:
                    row["start_time"] = str(row["start_time"])[:5]
                return rows
    except Exception as e:
        print("查詢上架票券錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢上架票券失敗")



@app.post("/api/remove_ticket")
def remove_ticket(
    ticket_id: int = Body(..., embed=True),
    user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        seller_id = user["user_id"]
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                # 1. 驗證票券存在且屬於該賣家
                cursor.execute("""
                    SELECT t.id, t.seller_id, o.id AS order_id
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
                if ticket.get("is_removed", False):
                    raise HTTPException(status_code=400, detail="票券已下架")

                # 2. 更新 is_removed
                cursor.execute("""
                    UPDATE tickets_for_sale
                    SET is_removed = TRUE
                    WHERE id = %s
                """, (ticket_id,))
                conn.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        print("下架票券失敗：", e)
        raise HTTPException(status_code=500, detail="下架票券失敗")



# 查詢當月所有 tickets_for_sale 中 is_sold = FALSE 的票券 API
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
        WHERE t.is_sold = FALSE AND t.is_removed = FALSE
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



# 查票 API

class BrowseTicketsResponse(BaseModel):
    tickets: List[dict]
    total_count: int

@app.get("/api/browse_tickets", response_model=BrowseTicketsResponse)
def browse_tickets(
    game_id: int,
    sort_by: Optional[str] = Query("created_at", enum=["created_at", "price", "rating"]),
    sort_order: Optional[str] = Query("desc", enum=["asc", "desc"]),
    seat_areas: Optional[str] = None,
    page: int = Query(1, ge=1),  
    per_page: int = Query(6, ge=1, le=100),  
):
    try:
        seat_filters = seat_areas.split(",") if seat_areas else []

        sort_column = {
            "created_at": "t.created_at",
            "price": "t.price",
            "rating": "IFNULL(avg_rating, 0)"
        }[sort_by]

        order = "ASC" if sort_order == "asc" else "DESC"

        # 查詢總筆數
        count_query = """
            SELECT COUNT(DISTINCT t.id) AS total_count
            FROM tickets_for_sale t
            JOIN games g ON t.game_id = g.id
            JOIN members m ON t.seller_id = m.id
            LEFT JOIN ratings r ON r.ratee_id = m.id
            WHERE t.game_id = %s AND t.is_sold = FALSE AND t.is_removed = FALSE
        """
        count_params = [game_id]
        if seat_filters:
            count_query += f" AND t.seat_area IN ({', '.join(['%s'] * len(seat_filters))})"
            count_params.extend(seat_filters)

        # 查詢當前頁資料
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
        data_params = [game_id]
        if seat_filters:
            data_query += f" AND t.seat_area IN ({', '.join(['%s'] * len(seat_filters))})"
            data_params.extend(seat_filters)

        data_query += " GROUP BY t.id ORDER BY " + sort_column + " " + order
        data_query += " LIMIT %s OFFSET %s"
        data_params.extend([per_page, (page - 1) * per_page])

        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                # 執行總筆數查詢
                cursor.execute(count_query, tuple(count_params))
                total_count = cursor.fetchone()["total_count"]

                # 執行資料查詢
                cursor.execute(data_query, tuple(data_params))
                results = cursor.fetchall()
                for row in results:
                    row["image_urls"] = json.loads(row["image_urls"])
                    row["start_time"] = str(row["start_time"])[:5]
                    row["avg_rating"] = float(row["avg_rating"]) if row["avg_rating"] is not None else None

                return {
                    "tickets": results,
                    "total_count": total_count
                }
    except Exception as e:
        print("錯誤:", e)
        return JSONResponse(status_code=500, content={"detail": "查詢票券失敗"})



# 評分 API 
class RatingIn(BaseModel):
    # rater_id: int     # 評分者
    ratee_id: int     # 被評分者（賣家）
    score: int        
    order_id:int      # 對哪筆 order 評分
    comment: Optional[str] = None

@app.post("/api/ratings")
def create_rating(
    rating: RatingIn,
    user: Dict[str, Any] = Depends(get_current_user)
):
    rater_id = user["user_id"]
    if not 1 <= rating.score <= 5:
        raise HTTPException(status_code=400, detail="評分需介於 1~5 顆星")

    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                # 檢查訂單是否存在且為「已出貨」狀態
                cursor.execute("""
                    SELECT id, shipment_status, buyer_id, seller_id, ticket_id
                    FROM orders
                    WHERE id = %s AND buyer_id = %s
                """, (rating.order_id, rater_id))
                order = cursor.fetchone()
                if not order:
                    raise HTTPException(status_code=404, detail="訂單不存在或您無權評分")
                if order["shipment_status"] != "已出貨":
                    raise HTTPException(status_code=400, detail="訂單尚未出貨，無法評分")
                if order["seller_id"] == rater_id:
                    raise HTTPException(status_code=400, detail="不能對自己評分")
                if rating.ratee_id != order["seller_id"]:
                    raise HTTPException(status_code=400, detail="被評分者與賣家不符")

                # 檢查是否已對該 order_id 評分
                cursor.execute("""
                    SELECT id FROM ratings WHERE order_id = %s AND rater_id = %s
                """, (rating.order_id, rater_id))
                if cursor.fetchone():
                    raise HTTPException(status_code=400, detail="此訂單已評分")

                # 插入評分
                query = """
                    INSERT INTO ratings (rater_id, ratee_id, score, comment, order_id, ticket_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                cursor.execute(query, (
                    rater_id,
                    order["seller_id"],
                    rating.score,
                    rating.comment or "",
                    rating.order_id,
                    order["ticket_id"],  # 使用 orders 表的 ticket_id
                ))
                conn.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        print("評分寫入錯誤：", e)
        raise HTTPException(status_code=500, detail="評分寫入失敗")



# 送出媒合請求 API (建立一筆 orders 訂單，狀態為「等待賣家接受或拒絕」)

@app.post("/api/match_request")
def request_match(
    ticket_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):  
    try:
        buyer_id = current_user["user_id"]
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute("SELECT is_sold FROM tickets_for_sale WHERE id = %s", (ticket_id,))
                ticket = cursor.fetchone()
                if not ticket:
                    raise HTTPException(status_code=404, detail="找不到票券")
                if ticket["is_sold"]:
                    raise HTTPException(status_code=400, detail="此票券已售出")
                cursor.execute("SELECT seller_id FROM tickets_for_sale WHERE id = %s", (ticket_id,))
                seller = cursor.fetchone()
                seller_id = seller["seller_id"]
                cursor.execute("""
                    INSERT INTO orders (ticket_id, buyer_id, seller_id, status, match_requested_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (ticket_id, buyer_id, seller_id, "媒合中", datetime.now()))
                conn.commit()
                return {"status": "success", "message": "媒合請求已送出"}
    except Exception as e:
        print("媒合錯誤:", e)
        raise HTTPException(status_code=500, detail="媒合請求失敗")


 


# 取得特定會員的所有訂單 API（買家為該會員）
@app.get("/api/buyerOrders")
def get_buyerOrders(
    user: Dict[str, Any] = Depends(get_current_user)
): 
    try:
        buyer_id = user["user_id"]
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
                AVG(r.score) AS seller_rating
            FROM orders o
            JOIN tickets_for_sale t ON o.ticket_id = t.id
            JOIN games g ON t.game_id = g.id
            LEFT JOIN ratings r ON r.order_id = o.id AND r.rater_id = o.buyer_id
            WHERE o.buyer_id = %s
            GROUP BY o.id
            ORDER BY o.id DESC
        """
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, (buyer_id,))
                rows = cursor.fetchall()

                for row in rows:
                    row["start_time"] = str(row["start_time"])[:5]
                    # 先計算 weekday，然後再格式化 game_date
                    if isinstance(row["game_date"], date):
                        row["weekday"] = ["一", "二", "三", "四", "五", "六", "日"][row["game_date"].weekday()]
                        row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
                    else:
                        row["weekday"] = "--"  # 若 game_date 不是 date 物件，給予預設值
                    row["stadium_url"] = {
                        "台北大巨蛋": "https://maps.app.goo.gl/m53dt8TAUQkWXBvD9",
                        "新莊": "https://maps.app.goo.gl/evnUECyJsLx3rkaE8",
                        "天母": "https://maps.app.goo.gl/WGsmw7y38Apdkcsm7",
                        "洲際": "https://maps.app.goo.gl/U6ZfbxwGp1t9APvN7",
                        "台南": "https://maps.app.goo.gl/Y4SgmRbEBCehqaH89",
                        "澄清湖": "https://maps.app.goo.gl/T4wG6E4ED5jKnxaz6",
                        "花蓮": "https://maps.app.goo.gl/UCvKfG29V7uEUc4G6",
                    }.get(row["stadium"], "#")
                    row["seller_rating"] = float(row["seller_rating"]) if row["seller_rating"] is not None else None
                    row["image_urls"] = json.loads(row["image_urls"]) if row["image_urls"] else []
                    row["note"] = row["note"] if row["note"] else ""
                return rows
    except Exception as e:
        print("查詢訂單錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢訂單失敗")


# 取得特定會員的所有訂單 API（賣家為該會員）
@app.get("/api/sellerOrders")
def get_sellerOrders(user: Dict[str, Any] = Depends(get_current_user)):  
    try:
        seller_id = user["user_id"]
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
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, (seller_id,))
                rows = cursor.fetchall()

                for row in rows:
                    row["start_time"] = str(row["start_time"])[:5]
                    # 先計算 weekday，然後再格式化 game_date
                    if isinstance(row["game_date"], date):
                        row["weekday"] = ["一", "二", "三", "四", "五", "六", "日"][row["game_date"].weekday()]
                        row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
                    else:
                        row["weekday"] = "--"  # 若 game_date 不是 date 物件，給予預設值
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





@app.post("/api/order_status")
def update_order_status(
	order_id: int = Body(...),
    action:   str = Body(...),
    current_user: Dict[str,Any] = Depends(get_current_user)
):

    try:
        seller_id = current_user["user_id"]
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
                msg = f"您對訂單 #{order_id} 的媒合結果為：{'成功' if action=='accept' else '失敗'}"
                cursor.execute("""
                    INSERT INTO notifications (member_id, message, url)
                    VALUES (%s, %s, %s)
                """, (order["buyer_id"], msg, "/member_buy"))
                # 查詢買家 Email 並寄送通知
                buyer_email = get_member_email(cursor, order["buyer_id"])
                send_email(
                    to=buyer_email,
                    subject="Pitch-A-Seat 訂單媒合結果通知",
                    body=f"您的訂單 #{order_id} 媒合結果為：{'成功' if action=='accept' else '失敗'}\n請至我的購買頁查看詳情"
                )
                # 推送 SSE 給買家
                for q in reservation_subscribers:
                    q.put_nowait({
                        "member_id": order["buyer_id"],
                        "message": msg,
                        "url": "/member_buy"
                    })

            conn.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        print("更新訂單失敗：", e)
        raise HTTPException(500, "更新失敗")


# 取得通知列表 api
@app.get("/api/notifications")
def get_notifications(
    user: Dict[str,Any] = Depends(get_current_user)
):
    try:
        member_id = user["user_id"]
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

# TapPay 付款 API 
@app.post("/api/tappay_pay")
async def tappay_pay(
    prime: str = Body(...),
    order_id: int = Body(...),
    user: Dict[str,Any] = Depends(get_current_user)
):
    # 1. 先檢查訂單存在性、狀態是否符合「可付款」，查詢訂單並確認可付款
    try:
        buyer_id = user["user_id"]
        with cnxpool.get_connection() as conn:
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
                # 只有在「媒合成功」且「未付款」才能進行付款
                if order["status"] != "媒合成功" or order["payment_status"] != "未付款":
                    raise HTTPException(status_code=400, detail="目前訂單狀態無法執行付款")
                # 取得訂單金額
                amount = order["price"]
    except HTTPException:
        raise
    except Exception as e:
        print("查詢訂單時錯誤：", e)
        raise HTTPException(status_code=500, detail="伺服器內部錯誤")

    # 2. 在 payments 表先插入一筆 UNPAID 紀錄
    payment_id = None
    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor() as cursor:
                insert_pay = """
                    INSERT INTO payments
                    (order_id, amount, tappay_status)
                    VALUES (%s, %s, %s)
                """
                cursor.execute(insert_pay, (order_id, amount, "UNPAID"))
                payment_id = cursor.lastrowid
            conn.commit()
    except Exception as e:
        print("建立 payments 記錄錯誤：", e)
        raise HTTPException(status_code=500, detail="伺服器內部錯誤")

    # 3. 呼叫 TapPay Pay By Prime API
    tappay_api_url = (
        "https://sandbox.tappaysdk.com/tpc/payment/pay-by-prime"
        if TAPPAY_ENV == "sandbox"
        else "https://prod.tappaysdk.com/tpc/payment/pay-by-prime"
    )

    headers = {
        "Content-Type": "application/json",
        "x-api-key": TAPPAY_PARTNER_KEY,
    }

    body = {
        "prime": prime,
        "partner_key": TAPPAY_PARTNER_KEY,
        "merchant_id": TAPPAY_MERCHANT_ID,
        "details": f"Order #{order_id} 支付",  # 自定義交易細節
        "amount": amount,
        "currency": "TWD",   
        "order_number": str(order_id),  # TapPay 在回傳物件中附上訂單編號
        # cardholder 資訊（可帶可不帶，但 TapPay 建議帶上）
        "cardholder": {
            "phone_number": "",      # 若前端有帶 cardholder 資訊，可補上
            "name": "",
            "email": "",
            "zip_code": "",
            "address": "",
            "national_id": "",
        },
        "remember": False  # 是否要記錄付款卡片，不需要就設成 False
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(tappay_api_url, headers=headers, json=body)
            tappay_result = resp.json()
    except Exception as e:
        print("呼叫 TapPay API 失敗：", e)
        # 若 TapPay API 本身沒回來，也要更新 payments 為 FAILED
        try:
            with cnxpool.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE payments SET tappay_status=%s, tappay_status_message=%s WHERE id=%s",
                        ("FAILED", "TapPay API 呼叫失敗", payment_id),
                    )
                conn.commit()
        except Exception as ex:
            print("更新 payments 失敗：", ex)
        raise HTTPException(status_code=500, detail="呼叫 TapPay 金流失敗")

    # 4. 根據 TapPay 回傳結果決定後續更新
    #    TapPay 回傳 JSON
    tappay_status = tappay_result.get("status")
    tappay_msg = tappay_result.get("msg", "")
    tappay_rec_trade_id = tappay_result.get("rec_trade_id", "")
    tappay_bank_txn_id = tappay_result.get("bank_transaction_id", "")

    if tappay_status == 0:
        # 成功：更新 payments.status、orders.payment_status、orders.paid_at
        try:
            with cnxpool.get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    # 4.1 更新 payments
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
                            datetime.now(),
                            tappay_rec_trade_id,
                            tappay_bank_txn_id,
                            tappay_status,
                            tappay_msg,
                            payment_id,
                        ),
                    )
                    # 4.2 更新 orders.payment_status, orders.paid_at
                    cursor.execute(
                        """
                        UPDATE orders
                        SET payment_status=%s,
                            paid_at=%s
                        WHERE id=%s
                        """,
                        ("已付款", datetime.now(), order_id),
                    )
                    # 4.2.1 通知賣家「訂單#X(編號) 已付款，請出貨」
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
                    # 查詢賣家 Email 並寄送通知
                    seller_email = get_member_email(cursor, order["seller_id"])
                    send_email(
                        to=seller_email,
                        subject="Pitch-A-Seat 訂單付款通知",
                        body=f"訂單 #{order_id} 已付款，金額：{amount} 元\n請盡快安排出貨，詳情請至：我的售票頁"
                    )
                    # 推送 SSE 給賣家
                    for q in reservation_subscribers:
                        q.put_nowait({
                            "member_id": order["seller_id"],
                            "message": msg,
                            "url": "/member_sell"
                        })

                conn.commit()
            return {"status": "success", "order_id": order_id}
        except Exception as e:
                # 顯式回滾交易
                try:
                    conn.rollback()
                except NameError:
                    # 如果 conn 未定義（例如，異常發生在 with 區塊之前），忽略回滾
                    pass
                print("更新付款結果到資料庫失敗：", e)
                raise HTTPException(status_code=500, detail="付款處理失敗，請聯繫客服")
    else:
        # 失敗：更新 payments 為 FAILED，並將失敗原因寫入 tappay_status_message
        try:
            with cnxpool.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE payments
                        SET tappay_status=%s,
                            tappay_status_code=%s,
                            tappay_status_message=%s
                        WHERE id=%s
                        """,
                        ("FAILED", tappay_status, tappay_msg, payment_id),
                    )
                conn.commit()
        except Exception as e:
            print("更新 payments 失敗：", e)
        # 把錯誤訊息回前端，前端顯示「付款失敗：訊息」
        return JSONResponse(
            status_code=400,
            content={"status": "failed", "message": f"TapPay 金流失敗：{tappay_msg}"},
        )
       


# 賣家出貨 api
@app.post("/api/mark_shipped")
def mark_shipped(
    order_id: int = Body(..., embed=True),
    user: Dict[str,Any] = Depends(get_current_user)
):

    try:
        seller_id = user["user_id"]
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
                msg = f"訂單 #{order_id} 已出貨，請確認物流"
                cursor.execute("""
                    INSERT INTO notifications (member_id, message, url)
                    VALUES (%s, %s, %s)
                """, (
                    order["buyer_id"],
                    msg,
                    "/member_buy"
                ))
                # 查詢買家 Email 並寄送通知
                buyer_email = get_member_email(cursor, order["buyer_id"])
                send_email(
                    to=buyer_email,
                    subject="Pitch-A-Seat 訂單出貨通知",
                    body=f"訂單 #{order_id} 已出貨，請留意物流資訊\n詳情請至：我的購買頁"
                )
                # 推送 SSE 給買家
                for q in reservation_subscribers:
                    q.put_nowait({
                        "member_id": order["buyer_id"],
                        "message": msg,
                        "url": "/member_buy"
                    })                
            conn.commit()
        return {"status":"success"}
    except HTTPException:
        raise
    except Exception as e:
        print("出貨錯誤：", e)
        raise HTTPException(status_code=500, detail="出貨失敗")

# 標記已讀的 API
@app.post("/api/mark_notifications_read")
def mark_notifications_read(
    user: Dict[str,Any] = Depends(get_current_user)
):

    try:
        member_id = user["user_id"]
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


# 訂閱 API：POST /api/reservations
@app.post("/api/reservations")
def create_reservation(
    data: ReservationIn,
    user: Dict[str, Any] = Depends(get_current_user)
):

    try:
        with cnxpool.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO reservations (member_id, game_id, price_ranges, seat_area)
                    VALUES (%s, %s, %s, %s)
                """, (
                    user["user_id"],
                    data.game_id,
                    json.dumps(data.price_ranges),
                    data.seat_area
                ))
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        print("建立預約失敗：", e)
        raise HTTPException(status_code=500, detail="建立預約失敗")


# Server-Sent Events（SSE）端點
@app.get("/api/notifications/stream")
async def notifications_stream(user: Dict[str, Any] = Depends(get_current_user)):

    queue: asyncio.Queue = asyncio.Queue()
    reservation_subscribers.append(queue)
    async def event_generator():
        try:
            while True:
                data = await queue.get()
                # 只推送給相同 member_id
                if data["member_id"] == user["user_id"]:
                    yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            reservation_subscribers.remove(queue)
    return StreamingResponse(event_generator(), media_type="text/event-stream")



# 取得預約場次資料 api
class ReservationOut(BaseModel):
    id: int        
    game_id: int
    game_date: str
    start_time: str
    team_home: str
    team_away: str
    price_ranges: str  # JSON string
    seat_area: str
    created_at: str

@app.get("/api/reservations", response_model=List[ReservationOut])
def get_reservations(user: Dict[str, Any] = Depends(get_current_user)):
    try:
        member_id = user["user_id"]
        query = """
            SELECT 
                r.id, r.game_id, r.price_ranges, r.seat_area, r.created_at,
                g.game_date, g.start_time, g.team_home, g.team_away
            FROM reservations r
            JOIN games g ON r.game_id = g.id
            WHERE r.member_id = %s
            ORDER BY r.created_at DESC
        """
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, (member_id,))
                results = cursor.fetchall()
                for row in results:
                    # 格式化 start_time 為 HH:MM
                    row["start_time"] = str(row["start_time"])[:5]
                    # 格式化 game_date 為 YYYY-MM-DD
                    if isinstance(row["game_date"], date):
                        row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
                    # 格式化 created_at 為 YYYY-MM-DD HH:MM:SS
                    if isinstance(row["created_at"], datetime):
                        row["created_at"] = row["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                return results
    except Exception as e:
        print("查詢預約錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢預約失敗")


# 刪除預約場次 api
@app.delete("/api/reservations/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reservation(
    reservation_id: int,
    user: Dict[str, Any] = Depends(get_current_user)
):

    try:
        member_id = user["user_id"]
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                # 1. 檢查預約是否存在且屬於該使用者
                cursor.execute(
                    "SELECT id FROM reservations WHERE id = %s AND member_id = %s",
                    (reservation_id, member_id)
                )
                reservation = cursor.fetchone()
                if not reservation:
                    raise HTTPException(
                        status_code=404,
                        detail="預約記錄不存在或您無權刪除"
                    )
                
                # 2. 刪除預約
                cursor.execute(
                    "DELETE FROM reservations WHERE id = %s",
                    (reservation_id,)
                )
                conn.commit()
                
        return None  # 回傳 204 No Content
    except HTTPException:
        raise
    except Exception as e:
        print("刪除預約失敗：", e)
        raise HTTPException(status_code=500, detail="刪除預約失敗")



# 個人化推薦
class RecommendedGame(BaseModel):
    game_id: int
    game_date: str
    start_time: str
    team_home: str
    team_away: str
    stadium: str
    ticket_count: int
    recommendation_score: float
    trade_count: int
    favorite_team_match: bool

# 個人化推薦 API
@app.get("/api/recommendations", response_model=List[RecommendedGame])
def get_recommendations(
    user: Optional[Dict[str, Any]] = Depends(get_current_user, use_cache=False)
):
    try:
        today = datetime.now().date()
        past_90_days = today - timedelta(days=90)
        future_30_days = today + timedelta(days=30)

        # Step 1: 取得用戶喜好球隊
        favorite_teams = []
        if user:
            with cnxpool.get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(
                        "SELECT favorite_teams FROM members WHERE id = %s",
                        (user["user_id"],)
                    )
                    member = cursor.fetchone()
                    if member and member["favorite_teams"]:
                        favorite_teams = json.loads(member["favorite_teams"])

        # 初始化隊伍得分dictionary
        team_scores = {team: 2.0 for team in favorite_teams}

        # Step 2: 查詢交易紀錄
        trade_query = """
            SELECT g.team_home, g.team_away, o.created_at
            FROM orders o
            JOIN tickets_for_sale t ON o.ticket_id = t.id
            JOIN games g ON t.game_id = g.id
            WHERE o.shipment_status = '已出貨'
              AND o.created_at >= %s
        """
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(trade_query, (past_90_days,))
                trades = cursor.fetchall()

                trade_contributions = []
                for trade in trades:
                    days_diff = (today - trade["created_at"].date()).days
                    weight = 1.2 * math.exp(-0.01 * days_diff)
                    trade_contributions.append(weight)
                    for team in [trade["team_home"], trade["team_away"]]:
                        team_scores[team] = team_scores.get(team, 0) + weight

                # 正規化交易得分
                if trade_contributions:
                    mean_trade = sum(trade_contributions) / len(trade_contributions)
                    for team in team_scores:
                        if team not in favorite_teams:
                            team_scores[team] = max(0, team_scores[team] - mean_trade)

        # Step 3: 查詢預約紀錄
        reservation_query = """
            SELECT g.team_home, g.team_away, r.created_at
            FROM reservations r
            JOIN games g ON r.game_id = g.id
            WHERE r.created_at >= %s
        """
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(reservation_query, (past_90_days,))
                reservations = cursor.fetchall()

                reservation_contributions = []
                for res in reservations:
                    days_diff = (today - res["created_at"].date()).days
                    weight = 1.0 * math.exp(-0.01 * days_diff)
                    reservation_contributions.append(weight)
                    for team in [res["team_home"], res["team_away"]]:
                        team_scores[team] = team_scores.get(team, 0) + weight

                # 正規化預約得分
                if reservation_contributions:
                    mean_res = sum(reservation_contributions) / len(reservation_contributions)
                    for team in team_scores:
                        if team not in favorite_teams:
                            team_scores[team] = max(0, team_scores[team] - mean_res)

        # Step 4: 查詢未來 30 天比賽
        games_query = """
            SELECT
                g.id AS game_id,
                g.game_date,
                g.start_time,
                g.team_home,
                g.team_away,
                g.stadium,
                COUNT(t.id) AS ticket_count,
                COUNT(DISTINCT o.id) AS trade_count
            FROM games g
            LEFT JOIN tickets_for_sale t ON g.id = t.game_id
            LEFT JOIN orders o ON t.id = o.ticket_id AND o.shipment_status = '已出貨'
            WHERE g.game_date BETWEEN %s AND %s
            GROUP BY g.id
        """
        with cnxpool.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(games_query, (today, future_30_days))
                games = cursor.fetchall()

        # Step 5: 計算推薦分數
        recommended_games = []
        for game in games:
            score = team_scores.get(game["team_home"], 0) + team_scores.get(game["team_away"], 0)
            # 加權熱門比賽
            score += 0.1 * game["trade_count"]
            favorite_team_match = any(
                team in [game["team_home"], game["team_away"]] for team in favorite_teams
            )
            recommended_games.append({
                "game_id": game["game_id"],
                "game_date": game["game_date"].strftime("%Y-%m-%d"),
                "start_time": str(game["start_time"])[:5],
                "team_home": game["team_home"],
                "team_away": game["team_away"],
                "stadium": game["stadium"],
                "ticket_count": game["ticket_count"],
                "recommendation_score": round(score, 2),
                "trade_count": game["trade_count"],
                "favorite_team_match": favorite_team_match
            })

        # 按推薦分數降序排序
        recommended_games.sort(key=lambda x: x["recommendation_score"], reverse=True)
        top_games = recommended_games[:5]

        # Step 6: 冷啟動處理
        if len(top_games) < 5:
            # 查詢熱門比賽（參考 /api/top_games 邏輯）
            hot_games_query = """
                SELECT
                    g.id AS game_id,
                    g.game_date,
                    g.start_time,
                    g.team_home,
                    g.team_away,
                    g.stadium,
                    COUNT(t.id) AS ticket_count,
                    COUNT(DISTINCT o.id) AS trade_count
                FROM games g
                JOIN tickets_for_sale t ON g.id = t.game_id
                JOIN orders o ON t.id = o.ticket_id
                WHERE o.shipment_status = '已出貨'
                  AND g.game_date BETWEEN %s AND %s
                GROUP BY g.id
                ORDER BY trade_count DESC
                LIMIT %s
            """
            with cnxpool.get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(hot_games_query, (today, future_30_days, 5 - len(top_games)))
                    hot_games = cursor.fetchall()

                for game in hot_games:
                    if game["game_id"] not in {g["game_id"] for g in top_games}:
                        favorite_team_match = any(
                            team in [game["team_home"], game["team_away"]] for team in favorite_teams
                        )
                        top_games.append({
                            "game_id": game["game_id"],
                            "game_date": game["game_date"].strftime("%Y-%m-%d"),
                            "start_time": str(game["start_time"])[:5],
                            "team_home": game["team_home"],
                            "team_away": game["team_away"],
                            "stadium": game["stadium"],
                            "ticket_count": game["ticket_count"],
                            "recommendation_score": 0.0,  # 冷啟動分數設為 0
                            "trade_count": game["trade_count"],
                            "favorite_team_match": favorite_team_match
                        })

        # 印出前五場比賽的推薦分數和其他資訊
        print("\n=== Top 5 Recommended Games ===")
        for idx, game in enumerate(top_games[:5], 1):
            print(f"Rank {idx}:")
            print(f"  Game ID: {game['game_id']}")
            print(f"  Date: {game['game_date']}")
            print(f"  Teams: {game['team_home']} vs {game['team_away']}")
            print(f"  Stadium: {game['stadium']}")
            print(f"  Recommendation Score: {game['recommendation_score']}")
            print(f"  Trade Count: {game['trade_count']}")
            print(f"  Favorite Team Match: {game['favorite_team_match']}")
            print(f"  Ticket Count: {game['ticket_count']}")
            print("-" * 40)
    
        return top_games[:5]

    except Exception as e:
        print(f"查詢推薦場次錯誤: {e}")
        raise HTTPException(status_code=500, detail="查詢推薦場次失敗")



# 讓 /static 目錄下的所有檔案都可以公開存取
app.mount("/static", StaticFiles(directory="static"), name="static")