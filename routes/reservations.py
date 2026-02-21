"""
reservations.py
Ticket reservation APIs for upcoming games APIs 
- POST    /api/reservations                  - Create a new ticket reservation
- GET     /api/reservations                  - Retrieve current user's reservations
- DELETE  /api/reservations/{reservation_id} - Cancel a specific reservation
"""


from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Dict, Any
from datetime import date, datetime
import json
from pydantic import BaseModel

from utils.auth_utils import get_current_user
from models.reservation_model import (
    create_reservation, get_user_reservations, delete_reservation_with_lock
)



# ================================================
# API 路徑前綴統一為 /api
router = APIRouter(prefix="/api", tags=["reservations"])
# ================================================



# Pydantic Model
# ================================================

# 預約請求模型: 用於建立新的票券預約，指定場次、可接受價格範圍與座位區域
class ReservationIn(BaseModel):
    game_id: int                    # 預約的場次 ID
    price_ranges: List[str]         # 預約者可接受的價格範圍列表 (python list 資料型態), eg. ["0-400", "401-699"]
    seat_area: str                  # 預約者可接受的座位區域, 可能的值: "none" / "內野" / "外野"



# 預約回應模型: 用於回傳會員的預約資料，包含場次資訊
class ReservationOut(BaseModel):
    id: int        
    game_id: int
    game_date: str
    start_time: str
    team_home: str
    team_away: str
    price_ranges: str  # JSON 字串格式，前端需用 JSON.parse() 解析
    seat_area: str
    created_at: str
# ================================================





# API Routes 

# ================================================
# 建立新預約 API 
# 回傳值: 預約狀態是 success
@router.post("/reservations")
def create_reservation_api(
    data: ReservationIn,
    user: Dict[str, Any] = Depends(get_current_user)
):
    member_id = user["user_id"]
    game_id = data.game_id
    price_ranges = json.dumps(data.price_ranges)
    seat_area = data.seat_area

    try:
        result = create_reservation(member_id, game_id, price_ranges,seat_area)
        return result
    except Exception as e:
        print("建立預約失敗：", e)
        raise HTTPException(status_code=500, detail="建立預約失敗")

# ================================================




# ================================================
# 取得當前會員的全部有效預約資料 API
@router.get("/reservations", response_model=List[ReservationOut])
async def get_reservations_api(user: Dict[str, Any] = Depends(get_current_user)):
    try:
        member_id = user["user_id"]
        
        results = get_user_reservations(member_id)
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
        print(f"查詢預約失敗：{e}")
        raise HTTPException(status_code=500, detail="查詢預約失敗")


    # 回傳值: 預約相關資訊 (賽事資訊、預約資訊), 依「建立預約的先後順序」排序
    # price_ranges 仍是 JSON 字串格式 (因為 MySQL 會自動將 List 轉為 JSON 字串格式儲存)，回給前端後需要前端用JSON.parse()解析 
# ================================================




# ================================================
# 刪除預約場次 API (使用「資料庫鎖 - 排他鎖」)
# 參數: 預約資料 id (URL 路徑參數), 前端使用 await fetch(`/api/reservations/${reservationId}` 將 URL 路徑參數傳入
# 回傳值: 若刪除成功, 回 204 No Content, Response 為 None. 若刪除失敗, 回對應的錯誤訊息
# 邏輯: 確認該預約存在且屬於此會員, 才能執行刪除 (若該預約不存在或不屬於此會員, 回404)
# 作法: 使用資料庫排他鎖 (SELECT ... FOR UPDATE), 將確認動作與刪除動作放在同一個 transaction 來保護, 避免被其他同時發生的刪除動作弄髒資料 (極端狀況)
@router.delete("/reservations/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reservation_api(
    reservation_id: int,
    user: Dict[str, Any] = Depends(get_current_user)
):    
    try:
        member_id = user["user_id"]

        # 在同一個 transaction 裡做：
        # 1. SELECT ... FOR UPDATE 檢查訂單是否存在 & 該會員是否擁有這筆預約，並加鎖
        # 2. 若存在 → DELETE
        # 3. 若不存在 → 回傳 False
        deleted = delete_reservation_with_lock(reservation_id, member_id)

        if not deleted:
            # 刪除動作失敗 (可能因為該筆預約資料不存在，或該筆預約資料不屬於操作刪除動作的使用者, 確保只有預約者本人可以取消自己的預約)
            raise HTTPException(
                status_code=404,
                detail="預約紀錄不存在或您無權刪除"
            )

        # 刪除成功 → 204 No Content（不回 Response body）
        return None

    except HTTPException:
        # 保留既有 HTTP 錯誤（ 404 ）
        raise
    except Exception as e:
        print("刪除預約失敗：", e)
        raise HTTPException(status_code=500, detail="刪除預約失敗")


# ================================================

