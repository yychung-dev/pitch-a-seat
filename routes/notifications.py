"""
notifications.py
User notification APIs
- GET  /api/notifications             - Retrieve current user's notifications 
- POST /api/mark_notifications_read   - mark all unread notifications as read
"""


from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any

from utils.auth_utils import get_current_user
from models.notification_model import (
    get_notifications, mark_all_notifications_read
)



# ================================================
# API 路徑前綴統一為 /api
router = APIRouter(prefix="/api", tags=["notifications"])
# ================================================




# API routes
# ================================================
# 取得通知列表 API
@router.get("/notifications")
async def get_notifications_api(user: Dict[str, Any] = Depends(get_current_user)):
    try:
        member_id = user["user_id"] 
        notifications = get_notifications(member_id)

        return notifications
    except Exception as e:
        print("查詢通知錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢通知失敗")
    

# ================================================





# ================================================
# 標記所有未讀通知為已讀的 API
# 回傳:「標記狀態為 success」, 「本次標記的筆數」
@router.post("/mark_notifications_read")
async def mark_all_notifications_read_api(    
    user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        member_id = user["user_id"]
        result = mark_all_notifications_read(member_id)
        return result        
    except Exception as e:
        print("標記通知已讀失敗：", e)
        raise HTTPException(status_code=500, detail="標記已讀失敗")

# ================================================

