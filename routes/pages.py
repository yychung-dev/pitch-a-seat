"""
pages.py
Static Page Routes

Serves HTML pages for browser rendering.
All routes return HTML files, not JSON.

Routes:
- GET /                    - Home page (index.html)
- GET /buy                 - Buy ticket page
- GET /sell                - Sell ticket page
- GET /payment             - Payment page
- GET /register            - Registration page
- GET /reservation         - Reservation page
- GET /member_profile      - Member profile page
- GET /member_sell         - Member's selling orders page
- GET /member_buy          - Member's buying orders page
- GET /member_reservation  - Member's reservations page
- GET /member_launch       - Member's ticket listing history page

Note: Authentication is handled by frontend JavaScript checking JWT token.
      Backend only serves HTML files.
"""


# 靜態頁面路由（ GET /、/buy、/sell... 共 11 個 ）
# 這個檔案定義所有「回傳 HTML 頁面」的路由。(pages.py 是「靜態頁面的路由定義檔」)
# 當使用者在網址列輸入 URL 時，回傳對應的 HTML 檔案。例如：使用者訪問 /buy -> 回傳 buy.html .使用者訪問 /sell → 回傳 sell.html


# 與 API 路由的差別：
# 頁面路由（如 /buy）：回傳 HTML 檔案，給瀏覽器渲染成網頁
# API 路由（如 /api/games）：回傳 JSON，給 JavaScript 用 



# =======================================
# 第一區：Import
from fastapi import APIRouter                    # 載入「路由收集器」工具，用來定義這個檔案的路由
from fastapi.responses import FileResponse       # 載入「檔案回應」工具，用來回傳檔案給瀏覽器
# =======================================



# =======================================
# 第二區: 建立路由收集器
router = APIRouter(include_in_schema=False)

# include_in_schema=False 的意思: 不在 /docs API 文件中顯示這些路由.
# 不要把這個 router 的路由顯示在 /docs API 文件中。其他 router (例如 orders.py)寫 router = APIRouter(prefix="/api", tags=["orders"]), 這種才需要顯示在 /docs，因為前端會用 fetch() 呼叫
# =======================================



# =======================================
# 第三區：路由定義

# 公開頁面（首頁）
# 意思：當收到 GET / 請求時，執行下面的函數
@router.get("/")         
async def index():       
    return FileResponse("./static/index.html", media_type="text/html")


# 以下頁面需要登入（由前端 JavaScript 檢查 JWT token）
# 後端只負責回傳 HTML，實際的登入驗證在 API 層處理
@router.get("/sell")
async def sell():
    return FileResponse("./static/sell.html", media_type="text/html")

@router.get("/buy")
async def buy_page():
    return FileResponse("./static/buy.html", media_type="text/html")

@router.get("/payment")
async def payment_page():
    return FileResponse("./static/payment.html", media_type="text/html")

@router.get("/register")
async def register_page():
    return FileResponse("./static/register.html", media_type="text/html")

@router.get("/reservation")
async def reservation_page():
    return FileResponse("./static/reservation.html", media_type="text/html")

@router.get("/member_profile")
async def member_profile():
    return FileResponse("./static/member_profile.html", media_type="text/html")

@router.get("/member_sell")
async def member_sell():
    return FileResponse("./static/member_sell.html", media_type="text/html")

@router.get("/member_buy")
async def member_buy():
    return FileResponse("./static/member_buy.html", media_type="text/html")

@router.get("/member_reservation")
async def member_reservation():
    return FileResponse("./static/member_reservation.html", media_type="text/html")

@router.get("/member_launch")
async def member_launch():
    return FileResponse("./static/member_launch.html", media_type="text/html")



# @: 裝飾器符號，把下面的函數「掛」到路由上, router: 用APIRouter()建立的路由收集器, .get: HTTP GET 方法, "/": URL 路徑（網站根目錄）
# async: 非同步函數（FastAPI 建議用法，可提升效能）, def: 定義函數, index: 函數名稱（可以取任何名字，只是方便辨識）
# return: 回傳結果給瀏覽器, FileResponse: 「讀取檔案並回傳」的回應類別 , 
# "./static/index.html": 檔案路徑. (.  = 專案根目錄（app.py 所在的位置）, /static = static 資料夾, /index.html = 目標檔案 )  
# media_type="text/html": 媒體類型（MIME type）. 告訴瀏覽器「我回傳給你的是 HTML 檔案，請用網頁方式顯示」. 如果不寫 media_type，FastAPI 會根據副檔名自動判斷, 但明確寫出來是好習慣 
# ================================================





# ================================================


# ---------------------
# 1.router = APIRouter(include_in_schema=False): 建立一個「路由收集器」。它本身不是一個完整的應用程式，只是用來「暫時存放路由定義」的容器。每個router檔案都會建立一次，之後app.py會使用app.include_router()來併入app主程式。例如：reservations.py裡有 router = APIRouter(prefix="/api", tags=["reservations"])，因此 reservations.py裡的 API 都是用 @router.get 或其他方法來製作，而這個用APIRouter()創建的router也會在app.py裡用app.include_router(reservations.router)來把它併入app主程式，目的是：讓這些拆分各處的router能被app知道這些所有路由的存在。
# 必須併入主程式、必須被 app 知道這些路由的存在的核心原因：只有 app 會被伺服器執行。uvicorn app:app 指令的意思是：「去 app.py 檔案，找到 app 這個變數，把它當作應用程式執行」。伺服器只認識 app，不認識 router。uvicorn 只會去「餐廳」（app）裡面找有什麼服務。你的 router 如果沒放進去，就像菜單不存在一樣。


# 2.路由用 @ 這個裝飾器的目的: 把下面的函數「掛」到路由上, 告訴 FastAPI「某函式處理這個裝飾器寫的 get 請求」, 例如：@router.post("/api/users") 就是：當收到 POST /api/users這個請求時，就執行這個裝飾器下面的這個函式。



# 3.路由是「 URL 路徑 + HTTP 方法 + 處理函式」的對應關係: 
# 例如：「@router.get("/") async def index(): return FileResponse("./static/index.html", media_type="text/html") 」就是一個路由，這個路由內的彼此對應關係是「 GET / 對應 index()」, 個別角色就是: 「 GET」就是 HTTP 方法、「/」就是URL路徑、「index()」就是處理函式。



# 4.FileResponse 是一個「回應類別 (Response Class)」。
# FileResponse 的功能：讀取伺服器上的檔案，然後把檔案內容回傳給瀏覽器。更完整地說: 
# (1) 讀取指定路徑的檔案
# (2) 設定適當的 HTTP headers（包括 Content-Type）
# (3) 把檔案內容作為 HTTP 回應的 body 回傳



# 5.media_type有很多種, 例如也有text/plalin, 回傳的可能是純文字（瀏覽器顯示原始文字）(原始碼). 或 application/json, 回傳 JSON 資料. 或image/png, 回傳 PNG 圖片.


# 6.「./static/index.html」是檔案路徑 (相對路徑: 相對於專案根目錄)
# . 代表「執行指令時的工作目錄（Current Working Directory）」, 當在專案根目錄執行 uvicorn app:app 時，. 就是專案根目錄, 所以 ./static/index.html 會對應到 pitchaseat/static/index.html
# static 代表「static 資料夾」，index.html 代表「目標檔案」。/ 是資料夾分隔符號。
# 如果從其他目錄執行（如 cd routes && uvicorn app:app），路徑會出錯, 實務上建議始終從專案根目錄執行 uvicorn



# ================================================