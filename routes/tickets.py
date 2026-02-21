"""
tickets.py
Ticket listing and browsing APIs
- POST /api/sell_tickets     - Uploads tickets for sale (by seller)
- GET  /api/sellerTickets    - Retrieve seller's own listed tickets 
- POST /api/remove_ticket    - Remove a ticket from sale (soft delete)
- GET  /api/browse_tickets   - Browse available tickets for a specific game
"""


from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form, Query, Body
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json, io, uuid

from utils.auth_utils import get_current_user
from utils.s3_utils import (upload_file_to_s3, get_content_type)

from models.ticket_model import (
    get_seller_tickets, remove_ticket, create_tickets_and_collect_matches,
    count_browse_tickets, get_browse_tickets_page
)


# ================================================
# API 路徑前綴統一為 /api
router = APIRouter(prefix="/api", tags=["tickets"])
# ================================================



# ================================================
# Pydantic Models

# 瀏覽票券回應模型: 用於 GET /api/browse_tickets 的回應，包含票券列表與總筆數（供分頁使用）
class BrowseTicketsResponse(BaseModel):
    tickets: List[Dict]
    total_count: int
# ================================================



# API Routes
# ================================================

# 上架票券 API 
@router.post("/sell_tickets")
async def sell_tickets_api(
    game_id: int = Form(...),
    tickets: str = Form(...),
    images: Optional[List[UploadFile]] = File(None),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        seller_id = current_user["user_id"]

        # 1.處理圖片: 圖片相關 初始化設定
        # (1)若前端請求時沒帶圖片 (使用者未上傳圖片)，將 images 改為 空list
        if images is None:
            images = []
        
        # (2)圖片檔名 限制三種 & 圖片大小 限制為 5MB 以下
        allowed_exts = {"jpg", "jpeg", "png"}
        max_size_mb = 5
        
        # (3) 建立 img_map 變數，初始化為空字典 (之後要裝 「個別票券對應的圖片url資訊」)
        img_map: Dict[str, List[str]] = {}

        # 2.處理圖片: 驗證 並 儲存 圖片
        for image in images:
            # (1)驗證: 檢查副檔名 
            # 將副檔名轉成小寫
            ext = image.filename.rsplit(".", 1)[-1].lower()
            # 若副檔名不屬於allow的副檔名，直接 raise 400 錯誤
            if ext not in allowed_exts:
                raise HTTPException(400, f"不支援的圖片格式：{image.filename}")
            
            # (2)驗證: 檢查檔案大小 
            # 非同步讀取整個檔案內容(檔案的二進位內容) (bytes)
            contents = await image.read()
            # 若檔案大小超過允許的最大 size，直接 raise 400 錯誤 (bytes -> MB)
            if len(contents) / 1024 / 1024 > max_size_mb:
                raise HTTPException(400, f"圖片過大（超過5MB）：{image.filename}")
            
            # (3)驗證: 檢查圖片是否為有效圖片
            # 若此圖片檔不是一張有效圖片，直接 raise 400 錯誤
            try:
                Image.open(io.BytesIO(contents)).verify()
                # .verify(): Image 物件的方法，用來驗證圖片是否完整且有效。 # Image.open(): 嘗試解析為圖片。(開啟/讀取圖片的函數)。
            except:
                raise HTTPException(400, f"無效圖片檔案：{image.filename}")

            # (4)儲存: 組成圖片檔名
            # 產生隨機檔名 (避免不同圖片檔的檔名相同而撞名)
            new_name = f"{uuid.uuid4()}.{ext}"
            # 將圖片上傳到 S3
            cloudfront_url = upload_file_to_s3(
                file_content=contents,
                file_name=new_name,
                content_type=get_content_type(ext)
            )

            if cloudfront_url is None:
                raise HTTPException(500, f"圖片上傳失敗：{image.filename}")

            
            # (5)分類圖片: 從前端傳來的檔名中取出票券索引（前綴），將該圖片的 CloudFront URL 存入 img_map 對應的票券索引下。前端會將檔名格式化為 "索引_原始檔名"，例如 "0_photo.jpg"。
            # 最終 img_map 結構是: eg. {"0": ["url1", "url2"], "1": ["url3"]}
            idx = image.filename.split("_", 1)[0]
            img_map.setdefault(idx, []).append(cloudfront_url)


        # 3.處理 tickets (解析票券 JSON): 把 tickets （前端傳來的 JSON 字串），解析成 Python list，例如 [{"price": 1000, "seat_area": "...", ...}, {...}]
        ticket_list = json.loads(tickets)
        
        # 4.開啟一個資料庫連線執行 Transaction (新增票券 + 比對預約): (1)將票券資訊插入 tickets_for_sale 資料表，(2)針對 本次上架票券 與 現存預約資料表中的預約資料 做比對，(3)若比對成功，通知預約者 (站內通知 + email 通知)       
        create_tickets_and_collect_matches(
            seller_id=seller_id,
            game_id=game_id,
            ticket_list=ticket_list,
            img_map=img_map,
        )

        # 5.若 API 執行成功，return {上架狀態為 success, 這次上架票券數量 (ticket_list 的長度)}
        return {"status": "success", "count": len(ticket_list)}

    except HTTPException:
        raise
    except Exception as e:
        print("sell_tickets API 票券上架失敗：", e)
        raise HTTPException(status_code=500, detail="票券上架失敗")


# ================================================




# ================================================
# 查詢賣家本人的所有上架票券 API
@router.get("/sellerTickets")
async def get_seller_tickets_api(user: Dict[str, Any] = Depends(get_current_user)):
    try: 
        seller_id = user["user_id"]
        rows = get_seller_tickets(seller_id)
        for row in rows:
            row["start_time"] = str(row["start_time"])[:5]
        return rows
 
    except Exception as e:
        print("查詢上架票券錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢上架票券失敗")


# 查詢賣家本人的所有上架票券 (包括已售出的票券、未售出的票券、已下架的票券, 由前端依不同狀態做不同標記, eg. 渲染「下架商品」按鈕、呈現「已下架」文字、呈現「訂單已成立，不可下架」文字)

# ================================================




# ================================================
# 賣家自行下架票券 API 
@router.post("/remove_ticket")
async def remove_ticket_api(
    ticket_id: int = Body(..., embed=True),
    user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        seller_id = user["user_id"]
        result = remove_ticket(ticket_id, seller_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        print("下架票券失敗：", e)
        raise HTTPException(status_code=500, detail="下架票券失敗")

# 備註: 賣家只能刪除「自己上架的票券」

# ================================================




# ================================================
# 查詢單場比賽的所有販售中票券資訊 API 
# 支援該場比賽所有票券的「排序功能」、「座位區域篩選功能」、「分頁功能: 一頁呈現 6 張票」
# 回傳: 1.票券列表 (包括每一張票券的資訊: 賽事資訊、票券資訊、賣家評分) 2.該場比賽的票券總筆數, eg. "total_account":2 
# 回傳每張販售中票券的資訊（前端會將每筆資料渲染成一張票券卡片）
@router.get("/browse_tickets", response_model=BrowseTicketsResponse)
async def browse_tickets_api(
    game_id: int,
    sort_by: Optional[str] = Query("created_at", enum=["created_at", "price", "rating"]),
    sort_order: Optional[str] = Query("desc", enum=["asc", "desc"]),
    seat_areas: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(6, ge=1, le=100),
):

    try:
        # 1) 處理查詢條件 (搭配get_browse_tickets_page函數一起理解)

        # 將前端傳來的逗號分隔字串轉成 list，用於組 SQL 的 IN (...) 條件
        seat_filters = seat_areas.split(",") if seat_areas else [] 

        # 用 mapping 對應前端參數到 SQL 欄位（防止 SQL Injection）
        sort_column = {
            "created_at": "t.created_at",
            "price": "t.price",
            "rating": "IFNULL(avg_rating, 0)",
        }[sort_by]

        # 排序方式
        order = "ASC" if sort_order == "asc" else "DESC"

        # 計算分頁 offset
        offset = (page - 1) * per_page


        # 2) 呼叫 model 層：查詢單場比賽販售中票券的總筆數
        total_count = count_browse_tickets(
            game_id=game_id,
            seat_filters=seat_filters,
        )

        # 3) 呼叫 model 層：查詢該場比賽販售中的所有票券, 並呈現當前頁面的所有票券資訊 (一頁最多只呈現 6 張票券的資訊)
        # eg. 賽事編號 407 的販售中票券有 7 張票券販售中, 第一頁呈現前 6 張票券的資訊 
        # eg. 賽事編號 407 的販售中票券有 7 張票券販售中, 第二頁呈現 1 張票券 (第 7 張票券)的資訊
        results = get_browse_tickets_page(
            game_id=game_id,
            seat_filters=seat_filters,
            sort_column=sort_column,
            sort_order=order,
            per_page=per_page,
            offset=offset,
        )

        # 4) 資料格式處理（由 Router 層負責處理資料格式轉換）
        for row in results:
            # image_urls: JSON 字串 -> list
            row["image_urls"] = json.loads(row["image_urls"])

            # start_time: 僅保留 HH:MM
            row["start_time"] = str(row["start_time"])[:5]

            # avg_rating: 轉 float，None 保持 None
            row["avg_rating"] = (
                float(row["avg_rating"])
                if row["avg_rating"] is not None
                else None
            )

        # 5) 回傳值: 所有販售中票券的資訊 (當前頁面的至多6筆資料) & 該場比賽的販售中票券總筆數
        return {
            "tickets": results,
            "total_count": total_count,
        }

    except Exception as e:
        print("查詢單場比賽可售票券失敗:", e)
        return JSONResponse(
            status_code=500,
            content={"detail": "查詢單場比賽可售票券失敗"},
        )

# ================================================
