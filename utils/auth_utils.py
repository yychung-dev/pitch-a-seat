"""
auth_utils.py
Authentication Utilities: JWT & Password Handling

Functions:
- hash_password(password)                   - Hash password using bcrypt
- verify_password(password, hashed)         - Verify password against hash
- create_access_token(data, expires_delta)  - Generate JWT token
- verify_token(token)                       - Decode and validate JWT token
- get_current_user(authorization)           - Extract user info from Authorization header
"""


import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import HTTPException, Header
from config.settings import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES




# ================================================

# 函數功能: 密碼加密：將「使用者註冊的明碼密碼」雜湊後得出「亂碼密碼」
# 參數: 明碼密碼
# 回傳值: 雜湊後的亂碼密碼 (str)

def hash_password(password: str) -> str:
    #將「使用者註冊的明碼密碼」經salt雜湊後得出亂碼(bytes)，再用.decode("utf-8")轉回字串回傳，方便以字串形式將雜湊後的密碼亂碼存入資料庫
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

# ================================================






# ================================================
# 函數功能: 驗證密碼: 比對「會員登入時輸入的密碼」與「該會員註冊時存入資料庫的密碼」是否相同
# 參數一: 「會員登入時在前端輸入的密碼 (明碼字串)」, 參數二:「會員註冊時存入資料庫的密碼(雜湊得出的亂碼字串)」
# 回傳值: True 或 False ( 相同或不相同 )
def verify_password(password: str, hashed: str) -> bool:    
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

    # ---------------- 
    # 先使用 encode("utf-8") 將 參數一 和 參數二 都轉成 bytes 後, 再用 bcrypt.checkpw 方法比對    
    # bcrypt.checkpw 的比對方式: 從「資料庫裡的雜湊密碼」取出「當初雜湊時使用的salt值」, 再用這同一個salt值將「前端輸入的明碼密碼」重新雜湊得出亂碼. 接著比對「資料庫裡的雜湊密碼」與「用同樣salt值新算出的雜湊密碼」, 兩者應該相同 (bytes).
    # 若兩者相同, bcrypt.checkpw 會 return True, 反之則 return False.
    
    # data.password (傳入的參數一)：會員在前端輸入的密碼, stored_hash (傳入的參數二)：資料庫儲存的 bcrypt 雜湊密碼.
    
# ================================================






# ================================================
# 函數功能: 生成一個 JWT Token (str)
# 參數: 1. 會員資料 (id, email, name)  2. Token 有效時間 
# 回傳值: JWT Token 字串 (沒有 Bearer 前綴. Bearer 前綴是之後要驗證 Token 時, 由前端手動加上後放在 Authorization header 裡, 再傳到後端進行驗證)
# 流程: 1. 複製一份會員 data  2. 加上「Token 有效時間 」的資訊  3. 使用 JWT 簽名生成 JWT Token (字串) (字串的組成方式: payload (主要是: data & expire) + SECRET_KEY + 加密演算法)  4. 回傳生成的 JWT Token 字串

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:    
    # 1. 把 data 複製一份（ 避免直接改到原本的 data: 因為 payload 之後會增加 exp 欄位, 所以把 data copy 出來一份再做修改較安全）
    to_encode = data.copy() # 此時的 to_encode: {'id': 123, 'email': 'test@example.com', 'name': 'Anna'}, 是一個 dictionary
    
    # 2.1 算出 expire: 現在時間 + Token 有效時間, 得出 Token 的特定過期時間
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # 2.2 在 payload 裡加上 exp 欄位 (原因: Token 解碼時, JWT library 會自動檢查 exp 是否已經過期)
    # 此時的 to_encode: {'id': 123,'email': 'test@example.com','name': 'Tom', 'exp': datetime.datetime(2026, 2, 1, 10, 45, 30, 123456)}, 是一個 dictionary
    to_encode.update({"exp": expire})  

    # 3. 用 PyJWT 的 jwt.encode 把 to_encode 這個 payload 簽名後變成 JWT 字串 
    # 搭配 key 和演算法來簽名，產生一個 JWT 字串 (三段: header、payload、signature 以兩個句點分隔
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM) 

    # 4. 回傳生成好的 JWT Token 字串給前端, 前端之後會手動加上 Bearer 後, 放在 Authorization header 裡送到後端 (要驗證身份時會將 JWT Token 傳到後端進行驗證)
    return encoded_jwt 

# --------------
# 不建議在 payload 裡放: 密碼（即使 hash 過也不建議）、大型資料（JWT 每次 request 都會帶）、會頻繁變動的資料（權限要常改）

# data 參數 : {"id": user_id, "email": data.email, "name": name}

# jwt.encode(payload=...) 的 payload 一定要是 dictionary. 因為: 在 PyJWT裡, jwt.encode(payload, key, algorithm) 對 payload 的資料型態要求必須是 dict，不能是 list / str / int / tuple / 其他自訂物件, 否則會是 TypeError: Expecting a dict payload, got <class 'str'>
# ================================================





# ================================================
# 函數功能: 將 JWT Token 字串解析出簽名前的 原始 payload 內容 
# 參數: 去除 Bearer 前綴的 JWT Token 字串 (get_current_user 函數呼叫 verify_token 函數時傳入的參數)
# 回傳值: 會員資訊 dict (id, email, name)
def verify_token(token: str) -> Dict[str, Any]:
    try:
        # 1. 解析 JWT Token 得出簽名前的原始 payload 內容
        # 正確解碼後，payload 會是: {'id': 123,'email': 'test@example.com','name': 'Tom', 'exp': 1769913930}, 是一個 dictionary
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # 2. 從 payload 取出會員的 id
        user_id: int = payload.get("id")

        # 3. 檢查取出的 payload 中是否確實有會員的 id (會員的 id 是最重要的身份驗證依據, 所以取 id 來檢查)
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token payload invalid")

        # 4. 透過取出的 payload 內容, 組出會員資訊 dict
        return {"user_id": user_id, "name": payload.get("name"), "email": payload.get("email")}
    except jwt.ExpiredSignatureError:
        # 若 payload 中的 exp 時間已過期, jwt.decode 這個 PyJWT 內建函數會檢查到並拋出 ExpiredSignatureError (PyJWT套件內建功能)
        raise HTTPException(status_code=401, detail="Token 已過期，請重新登入")
    except jwt.PyJWTError:
        # 若有 token格式錯誤、簽名錯誤等錯誤, jwt.decode 這個 PyJWT 內建函數會檢查到並拋出 PyJWTError (PyJWT套件內建功能)
        # jwt.decode 這個 PyJWT 內建函數內部會做很多檢查
        raise HTTPException(status_code=401, detail="無效的 token")
# ================================================




# ================================================
# 函數功能: 從呼叫此函數的 HTTP 請求的 Header 中取出 JWT Token 字串 (去除 Bearer), 再將此 Token 字串傳入 verify_token函數來比對「此登入的使用者身份是否合法」

# FastAPI 的 依賴注入（Dependency Injection）語法
# 參數: 
# (1)authorization: 參數名稱, FastAPI 依賴注入，自動從 HTTP Request Header 的 "Authorization" 欄位取值 (JWT Token, 包含前端呼叫時手動加上的 Bearer 前綴)
# (2)Header(None): 若 Header 中沒有此欄位，回傳 None（而不是報錯）
# (3)FastAPI 會根據參數名稱自動對應到同名的 Header（不區分大小寫）

# 回傳值: 會員資訊 dict (verify_token的回傳值), 呼叫此函數的 API 會把這些會員資訊拿來進一步使用 (eg. 用會員 id 去資料庫取得會員各種資料, 如: 訂單資料、預約資料)

# 流程: 1. 從 Header 拿 Token  2.檢查 Bearer 格式是否正確  3.把「去除 Bearer前綴後的 Token 」作為參數呼叫 verify_token函數進行驗證

def get_current_user(authorization: str = Header(None)) -> Dict[str, Any]:
    
    # 1.檢查 「Header 中是否確實有 Bearer Token」、檢查 「Header 中的 Bearer Token 是否確實以Bearer作為前綴」(避免有人惡意使用篡改後的 JWT Token 進行驗證)
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    # 2.把 Token 去除 Bearer 前綴
    # (1)authorization.replace("Bearer ", "") -> 將 「Token 字串中的 "Bearer "」替換成一個「""(空字串)」, 所以"Bearer XXXXXX" 會變成"XXXXXX" (替換後的 Token 就沒有空格了, 因為空字串「沒有空格」)
    # (2).strip() -> 防禦性設計: 移除字串首尾的所有空格或換行符, 避免「因多打空格而導致後續 Token 解析失敗」
    token = authorization.replace("Bearer ", "").strip()

    # 3.把「去除 Bearer前綴後的 Token 」作為參數呼叫 verify_token函數進行驗證
    return verify_token(token)


# --------------
# 所有需要身份驗證的 API 都會呼叫 get_current_user 函數來驗證身份.
# 把 verify_token 函數單獨抽出來, 優點: 若有其他不是放在 Header 裡的 token 要驗證 (eg. WebSocket query string), 就可以直接呼叫 verify_token 函數來驗證就好.

# ================================================

