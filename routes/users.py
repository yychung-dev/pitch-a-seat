"""
users.py
Member profile management APIs
- GET /api/user/profile  - Retrieve current user's profile
- PUT /api/user/profile  - Update current user's profile
"""


from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import json

from utils.auth_utils import get_current_user, hash_password
from models.user_model import (get_user_profile, ensure_email_unique_for_update, ensure_name_unique_for_update,update_member_profile)





# ================================================
# API 路徑前綴統一為 /api/user
router = APIRouter(prefix="/api/user", tags=["users"])   # 「user.py 的 API 前綴」 與 「auth.py 的 API 前綴」 同為 /api/user
# ================================================



# Pydantic Models
# ================================================

# 會員個人資料回應模型 (用於 GET/PUT /api/user/profile 的回應, 包含完整個人資料與賣家平均評分)
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



# 會員個人資料更新請求模型 (用於 PUT /api/user/profile 的請求. 所有欄位皆為 Optional, 僅更新有傳入的欄位)
class UserProfileUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)
    phone: Optional[str] = Field(None, pattern=r"^09\d{8}$")
    city: Optional[str] = None
    favorite_teams: Optional[List[str]] = None
# ================================================





# API Routes
# ================================================
# 取得會員個人資料 API 
@router.get("/profile", response_model=UserProfileOut)
async def get_profile(user: Dict[str, Any] = Depends(get_current_user)):
    # 1. 參數使用 get_current_user 函數依賴注入, 取得目前使用者的資訊 (user_id, name, email) 
    user_id = user["user_id"]
    try:
        # 2. 根據 user_id 查詢會員的個人資料 
        user_data = get_user_profile(user_id)
        if not user_data:
            raise HTTPException(status_code=404, detail="使用者不存在")
        
        try:
            user_data["favorite_teams"] = json.loads(user_data["favorite_teams"]) if user_data["favorite_teams"] else []
        except json.JSONDecodeError as e:
            print(f"favorite_teams JSON 解析錯誤 (user_id={user_id}): {e}")  
            user_data["favorite_teams"] = []
        

        user_data["avg_rating"] = float(user_data["avg_rating"]) if user_data["avg_rating"] is not None else None
        
        # 3.回傳使用者的會員資料或 None
        return user_data
    
    except HTTPException:
        raise

    except Exception as e:
        print("取得個人資料時錯誤：", e)
        raise HTTPException(status_code=500, detail="伺服器錯誤")

# 呼叫 GET /api/profile API 的地方:
# (1) 前端個人資料頁: 載入渲染時呼叫一次。個人資料更新完成後會再呼叫一次。
# (2) PUT /api/profile API: 更新個人資料 API 的 回傳值是呼叫 get_user(user)
# ================================================




# ================================================
# 更新會員個人資料 API 
@router.put("/profile", response_model=UserProfileOut)
async def update_profile(
    data: UserProfileUpdateIn,
    user: Dict[str, Any] = Depends(get_current_user)
):  
    user_id = user["user_id"]
    update_fields = []
    update_vals = []
    
    try:
        # 檢查會員想更新的 email 是否已被其他帳號使用
        if data.email is not None and data.email != user["email"]:
            ensure_email_unique_for_update(data.email, user_id)

        # 檢查會員想更新的 name 是否已被其他帳號使用
        if data.name is not None and data.name != user["name"]:
            ensure_name_unique_for_update(data.name, user_id)

        # 建立要更新的會員資料內容
        if data.name is not None:
            update_fields.append("name = %s")
            update_vals.append(data.name)
        if data.email is not None:
            update_fields.append("email = %s")
            update_vals.append(data.email)
        if data.password is not None:
            pwd_hash = hash_password(data.password)
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

        # 更新資料庫內容 (執行 UPDATE SQL 指令)
        set_clause = ", ".join(update_fields)
        update_vals_with_id = update_vals + [user_id]
        update_member_profile(set_clause, update_vals_with_id)

        # 更新後回傳更新後的最新個人資料
        return await get_profile(user)

    except HTTPException:
        raise
    
    except Exception as e:
        print(f"更新個人資料時錯誤：{e}")
        raise HTTPException(status_code=500, detail="更新失敗，請稍後再試")
# ================================================

