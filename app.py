"""
Pitch-A-Seat 應用程式主入口

1. 建立 FastAPI 應用程式實例
2. 設定中介層 (CORS、Logging)
3. 掛載所有路由模組
4. 掛載靜態資源服務
"""

# =======================================
# 第一區塊：Import（載入工具）
import logging                                      
from fastapi import FastAPI                         # 載入 FastAPI 這個「類別」，用來建立應用程式
from fastapi.middleware.cors import CORSMiddleware  # 載入 CORS 中介層工具
from fastapi.staticfiles import StaticFiles         # 載入靜態檔案服務工具

from config.settings import CORS_ORIGINS            # 從設定檔 (config/settings.py) 載入允許的網域清單
from config.settings import DEBUG, LOG_LEVEL

from routes import (pages, auth, users, games, tickets, orders, reviews, reservations, notifications)  # 載入各個路由模組
# =======================================



# =======================================
# 第二區塊：Logging 設定 (全域的 root logger) 
# 先設定好日誌格式 (設定好環境), 再做 FastAPI 初始化

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
# 程式執行時會輸出像這樣的日誌：
# 2025-02-06 14:30:05 [ERROR] routes.orders - 賣家出貨發生錯誤：「實際錯誤訊息」


# -----------------------
# getattr(logging, log_level)的作用: 把"INFO"或"WARNING"字串轉成對應的數字。因為 logging 的 level 只認數字，不認字串。
# logging 模組內部不同定義對應的數字如下： 
# getattr(logging, "INFO")     # 等同於 logging.INFO，回傳 20
# getattr(logging, "DEBUG")    # 等同於 logging.DEBUG，回傳 10
# getattr(logging, "WARNING")  # 等同於 logging.WARNING，回傳 30

# 所以:
# eg. getattr(logging, "DEBUG") -> 回傳 logging.DEBUG = 10 -> logging.basicConfig(level=10) -> 所有 DEBUG 以上的訊息都會顯示
# =======================================



# =======================================
# 第三區塊：建立應用程式實例 (建立 FastAPI 應用程式)
app = FastAPI(
    title="中華職棒二手票交易平台 API",
    description="Pitch-A-Seat",
    version="1.0.0",
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None,
)
# 前三個初始化參數, 會顯示在 /docs（Swagger UI）頁面上
# =======================================



# =======================================
# 第四區塊：CORS 中介層
# 把 CORS 規則「掛上主 application instance」
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,  # 哪些網域可以來存取 API
    allow_credentials=True,      # 允許請求帶 Cookie
    allow_methods=["*"],         # 允許所有 HTTP 方法（GET/POST/PUT/DELETE...）
    allow_headers=["*"],         # 允許所有請求 Header
)
# CORS : 
# 當前端 JavaScript 發送跨域請求時，瀏覽器會檢查目標伺服器是否允許該來源。這個設定告訴瀏覽器：「CORS_ORIGINS 清單中的網域可以存取我的 API」
# 註：專案目前是同源（前後端都在 pitchaseat.com），CORS 問題較少，但本機開發時 localhost 不同 port 算跨域，所以還是需要設定
# =======================================



# =======================================
# 第五區塊：註冊路由
# 把 主 app 這個 application instance 加入「路由」

# 1.頁面路由（ HTML 頁面 ）
app.include_router(pages.router)
# 2.API 路由
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(games.router)
app.include_router(tickets.router)
app.include_router(orders.router)
app.include_router(reviews.router)
app.include_router(reservations.router)
app.include_router(notifications.router)

# 以 app.include_router(auth.router) 為例, 就是「把 auth.py 裡 router 收集的所有路由，全部註冊到 app 上，讓 app 知道這些 API 端點存在」
# =======================================



# =======================================
# 第六區塊：掛載靜態資源 (靜態檔案)
# 把 主 app 這個 application instance 加入「 靜態資源 」
app.mount("/static", StaticFiles(directory="static"), name="static")

# 當有人請求 /static/xxx 時，去 static 資料夾找 xxx 這個檔案，找到就回傳，找不到就 404
# (1)參數一: "/static": URL 路徑前綴，以這個開頭的請求才會被處理
# (2)參數二: StaticFiles(directory="static")（處理請求的應用程式）. directory="static": 去專案資料夾裡的 static 資料夾找檔案. StaticFiles 是 FastAPI 內建的「靜態檔案服務應用程式」
# (3)參數三: name="static" (這個 mount 的名字): 這個名字主要用於反向生成 URL（進階功能）)
# =======================================
