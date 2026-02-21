"""
auth.py
Member authentication APIs (register / login / auth check)
- POST /api/user/register
- POST /api/user/login
- GET /api/user/auth
"""


from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional,  Dict, Any, Union
from datetime import timedelta,datetime
import json

from config.settings import ACCESS_TOKEN_EXPIRE_MINUTES

from utils.auth_utils import (hash_password, verify_password, create_access_token,get_current_user)
from models.auth_model import (get_user_by_email, get_user_by_name, create_member, get_member_row_by_id)


# ================================================
# API 路徑前綴統一為 /api/user
router = APIRouter(prefix="/api/user", tags=["auth"])

# prefix="/api/user"：幫這組 API 全部加上 /api/user 路徑，是實務專案中常用且必要的 API 分組方式。可以統一管理 API 路徑，避免路徑重複與混亂，拆檔案、拆模組時特別重要 (每個功能模組可以擁有自己的 prefix，整合時不會路徑衝突)
# 前端呼叫寫 /api/user/login 是由 prefix + /login 合併而成
# tags=["auth"]：讓 API 文件更清楚。Swagger UI（/docs）裡分類清楚，方便 前後端開發者 與 QA 找到 API
# ================================================




# ================================================
# Pydantic Model 


# 使用者註冊請求資料模型
# 用於驗證前端傳入的註冊表單資料，包含：姓名、Email、密碼、確認密碼、手機、城市、支持球隊
class UserRegisterIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    confirm_password: str
    phone: str = Field(..., pattern=r"^09\d{8}$")
    city: Optional[str] = None
    favorite_teams: Optional[List[str]] = None



# 使用者登入請求資料模型
# 用於驗證前端傳入的登入表單資料，包含：Email、密碼
class UserLoginIn(BaseModel):
    email: EmailStr
    password: str



# JWT Token 回應資料模型
# 登入或註冊成功後，回傳給前端的 JWT access token，讓前端存入 localStorage 用於後續 API 驗證
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# 使用者資料回應模型
# 用於 /api/user/auth GET API 的回應，回傳已登入使用者的完整個人資料
# 前端用此資料渲染導覽列的使用者名稱、下拉選單等 UI
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
    avg_rating: Union[float, None] = None   # 明確允許 None (回傳給前端 JS 時，這個值可以是 null)

# ================================================




# API routes
# ================================================
# 會員註冊 API
@router.post("/register", response_model=TokenResponse)
async def user_register(data: UserRegisterIn):    
    # 驗證密碼是否一致
    if data.password != data.confirm_password:
        raise HTTPException(status_code=400, detail="密碼與確認密碼不一致")
    try:
        # 檢查 email 是否已存在（呼叫 get_user_by_email）
        existing_useremail = get_user_by_email(data.email)
        if existing_useremail:
            raise HTTPException(status_code=400, detail="此電子郵件已被註冊")
        
        # 檢查 name 是否已存在（呼叫 get_user_by_name）
        existing_username = get_user_by_name(data.name)
        if existing_username:
            raise HTTPException(status_code=400, detail="此姓名已被使用，請換一個")
        
        # 雜湊加密密碼（呼叫 hash_password）
        hashed_password = hash_password(data.password)
        
        # 新增會員到資料庫
        # 先將 Python 物件 轉成 JSON 字串
        favorite_teams_json = json.dumps(data.favorite_teams) if data.favorite_teams else None       
        # json.dumps(List[str]) -> 會變成 JSON 字串，例如：["中信兄弟", "樂天桃猿"] (Python List) → "["中信兄弟", "樂天桃猿"]"（字串）

        user_id = create_member(
            name=data.name,
            email=data.email,
            password_hash=hashed_password,
            phone=data.phone,
            city=data.city,
            favorite_teams_json=favorite_teams_json,
        )

    except HTTPException:
        raise    
    except Exception as e:
        print(f"註冊時資料庫錯誤：{e}")
        raise HTTPException(status_code=500, detail="註冊失敗，請稍後再試")
    
    # 生成 JWT token（呼叫 create_access_token）
    access_token = create_access_token(
        data={"id": user_id, "email": data.email, "name": data.name},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )    
    return {"access_token": access_token}
# ================================================





# ================================================
# 會員登入 API
@router.post("/login", response_model=TokenResponse)
async def user_login(data: UserLoginIn):
    try:
        # 1.根據 email 查詢會員
        user = get_user_by_email(data.email)
        # print(user)
        # 用 E-Mail 查無會員資料
        if not user:
            raise HTTPException(status_code=400, detail="帳號或密碼錯誤")
        
        # 2.比對密碼
        stored_hash = user["password_hash"]
        if not verify_password(data.password, stored_hash):
            raise HTTPException(status_code=400, detail="帳號或密碼錯誤")
        
        # 3.抓必要欄位以便之後生成 token
        user_id = user["id"]
        name = user["name"]
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"登入時資料庫錯誤：{e}")
        raise HTTPException(status_code=500, detail="系統錯誤，請稍後再試")
    
    # 4. 生成 JWT token
    access_token = create_access_token(
        data={"id": user_id, "email": data.email, "name": name},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    # 5. 通過身份驗證後, 將生成的 JWT token 回傳給前端, 讓前端使用者登入後帶著這個 token 在身上 (存在 local storage), 之後若要請求需要身份驗證的API, 就用這個 token 來驗證
    return {"access_token": access_token}
# ================================================




# ================================================
# 檢查目前使用者的登入狀態 API
# 前端頁面載入時, 驗證使用者登入狀態並取得使用者資料
@router.get("/auth", response_model=Optional[UserProfileOut])
async def check_auth(user: Dict[str, Any] = Depends(get_current_user)):
    # 1. 參數使用 get_current_user 函數依賴注入, 取得目前使用者的資訊 (user_id, name, email) 
    # 2. 根據 user_id 查詢完整使用者的會員資料 
    # 3. 回傳使用者的會員資料或 None
    
    user_id = user["user_id"]    
    try:
        row = get_member_row_by_id(user_id)
        if not row:
            return None
        row["favorite_teams"] = json.loads(row["favorite_teams"]) if row["favorite_teams"] else []
        # 如果資料庫中存的 JSON 字串格式錯誤，會直接拋出 JSONDecodeError, 建議加上錯誤處理 except json.JSONDecodeError: row["favorite_teams"] = []
        return row
    except Exception as e:
        print("檢查登入狀態時錯誤：", e)
        raise HTTPException(status_code=500, detail="伺服器錯誤")



# ================================================
# 每次呼叫 /api/user/auth：FastAPI 會先從 request header 拿 Authorization，執行 get_current_user 檢查 token，若通過，拿到 {"user_id": ..., "name": ..., "email": ...}，再把這個 dict 當成 user 傳進 check_auth 函數。
# 所以 check_auth 函數內可以直接透過 user["user_id"] 知道現在是登入的使用者是哪個會員。
# ================================================



