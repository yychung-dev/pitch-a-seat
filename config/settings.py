# 所有「環境變數」與「常數」的 讀取 與 驗證 


# JWT、DataBase、TAPPAY、Redis、S3、SQS、SMTP 等設定 
# 其他檔案只需 from config.settings import XX 就能使用


import os                       # 載入 Python 內建模組 os : 用來讀取環境變數
import sys

from dotenv import load_dotenv  # 載入第三方套件 load_dotenv : 用來讀取 .env 檔案
load_dotenv()                   # 套件功能 : 把.env 檔案內容「載入到環境變數」. 例如: 載入後, os.getenv("ENV") 就能讀到 "development"



# =======================================
# 環境判斷
ENV = os.getenv("ENV", "development")
DEBUG = ENV == "development"
# =======================================


# =======================================
# Log 設定
# 開發環境預設 DEBUG，正式環境預設 WARNING
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "WARNING")
# =======================================


# =======================================
# 開發環境和生產環境分別用不同的 CORS 設定

# 開發環境：允許本機各種 port 的跨域請求
if DEBUG:
    CORS_ORIGINS = [               # 開發環境開放這些網域可以向後端 API 發出請求並得到回應 (可能用不同方式開啟前端) (localhost 和 127.0.0.1 技術上是同一個地方, 但瀏覽器會把它們當成「不同網域」, 所以都列出來)
        "http://localhost:3000",   # React 開發伺服器（ npm run dev ）, 預設為 3000
        "http://localhost:8000",   # 直接打開 FastAPI
        "http://127.0.0.1:3000",   # 有些工具用 IP 而不是 localhost
        "http://127.0.0.1:8000",     
    ]
# 生產環境：只允許正式網域請求
else:
    CORS_ORIGINS = [
        "https://pitchaseat.com",  # 正式生產環境(上線時)改成限定「https://pitchaseat.com」這個網域, 只有這個網域可以向我的後端 API 發出請求並得到回應
    ]
# =======================================



# =======================================
# 環境變數讀取

# ===== JWT 設定 =====
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7    # 7 天


# ===== 資料庫設定 =====
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_PORT = int(os.getenv("DB_PORT", 3306))


# ===== SMTP 設定 =====
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587)) # 加上預設值, 避免 None 轉 int 報錯
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")


# ===== TapPay 設定 =====
TAPPAY_PARTNER_KEY = os.getenv("TAPPAY_PARTNER_KEY")
TAPPAY_MERCHANT_ID = os.getenv("TAPPAY_MERCHANT_ID")
TAPPAY_ENV = os.getenv("TAPPAY_ENV", "sandbox")


# ===== Redis 連線設定 =====
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None  # 若沒在 Redis 伺服器設定密碼，可設為 None (加上 or None 是防禦性程式設計: 可以把空字串統一轉成 None。確保無論 .env 的 REDIS_PASSWORD 怎麼寫，程式都能正確處理)


# ===== AWS S3 設定 =====
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")  
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
CLOUDFRONT_URL = os.getenv("CLOUDFRONT_URL", "").rstrip("/")  # 移除尾部斜線: 防禦性程式設計, 避免當使用「f"{CLOUDFRONT_URL}/tickets/{file_name}」組合 URL 時出現雙斜線


# 從環境變數讀取 AWS 設定
# os.getenv() 會讀取 .env 或系統環境變數的值


# ===== AWS SQS 設定 =====
SQS_EMAIL_QUEUE_URL = os.getenv("SQS_EMAIL_QUEUE_URL")

# =======================================




# =======================================
# 環境變數驗證
def validate_all_settings():    
    # ----- 必要的環境變數 (若有缺少, sys.exit(1) 直接強制終止程式) -----
    # 沒有這些，網站的基本核心功能完全無法運作
    required_vars = {
        "JWT": [                                     # 若沒設定 JWT secret key, 無法登入、驗證身份, 會員系統癱瘓
            ("JWT_SECRET_KEY", SECRET_KEY),
        ],
        "資料庫": [                                   # 若沒設定 資料庫資訊, 無法讀寫任何資料, 網站完全無法運作
            ("DB_USER", DB_USER),
            ("DB_PASSWORD", DB_PASSWORD),
            ("DB_HOST", DB_HOST),
            ("DB_NAME", DB_NAME),
        ],
        "SMTP (寄信)": [                              # 若沒設定 SMTP, 無法執行所有寄信通知, 使用者收不到重要通知
            ("SMTP_HOST", SMTP_HOST),
            ("SMTP_USER", SMTP_USER),
            ("SMTP_PASS", SMTP_PASS),
        ],
        "AWS S3": [                                  # 若沒設定 AWS S3/CloudFront, 無法上傳/顯示票券圖片, 無法上架票券
            ("AWS_ACCESS_KEY_ID", AWS_ACCESS_KEY_ID),
            ("AWS_SECRET_ACCESS_KEY", AWS_SECRET_ACCESS_KEY),
            ("S3_BUCKET_NAME", S3_BUCKET_NAME),
            ("CLOUDFRONT_URL", CLOUDFRONT_URL),
        ],
    }
    
    # ----- 非必要的環境變數（若有缺少, 只會印出警告, 不會停止執行程式）-----
    # 沒有這些，網站還能運作，只是部分功能受限或影響效能
    optional_vars = {
        "TapPay (金流)": [                # 若沒設定 TapPay 環境變數, 就無法使用付款功能, 但還能使用上架票券、瀏覽票券、媒合請求等功能. 適合在「尚未開通金流付款」開發階段時這樣設置. 但 TapPay 在生產環境是必要的，部署時務必設定這兩個 TapPay 環境變數
            ("TAPPAY_PARTNER_KEY", TAPPAY_PARTNER_KEY),
            ("TAPPAY_MERCHANT_ID", TAPPAY_MERCHANT_ID),
        ],
        "Redis": [
            ("REDIS_HOST", REDIS_HOST),  # 若沒設定 REDIS_HOST, 還能降級查資料庫, 只是效能較差
        ],
        "SQS (非同步通知)": [              # 若沒設定 SQS_EMAIL_QUEUE_URL, 還能降級用同步方式寄 EMAIL, 只是效能較差
            ("SQS_EMAIL_QUEUE_URL", SQS_EMAIL_QUEUE_URL),   # 因為寄信程式碼有 fallback 機制，即使沒設定SQS，還是可以降級改用同步方式(最原始的方式)寄email
        ]
    }
    
    # ----- 檢查必要變數 -----
    missing_required = []
    for category, vars_list in required_vars.items():
        for var_name, var_value in vars_list:
            if not var_value:
                missing_required.append(f"  [{category}] {var_name}")
    
    if missing_required:
        print("\n" + "=" * 50)
        print("缺少以下必要的環境變數，程式無法啟動：")
        print("=" * 50)
        for var in missing_required:
            print(var)
        print("\n請在 .env 檔案中設定這些變數。")
        print("=" * 50 + "\n")
        sys.exit(1)
    
    # ----- 檢查非必要變數 -----
    missing_optional = []
    for category, vars_list in optional_vars.items():
        for var_name, var_value in vars_list:
            if not var_value:
                missing_optional.append(f"  [{category}] {var_name}")
    
    if missing_optional:
        print("\n" + "-" * 50)
        print("警告：以下環境變數未設定（相關功能可能無法使用）：")
        print("-" * 50)
        for var in missing_optional:
            print(var)
        print("-" * 50 + "\n")
    
    print("環境變數檢查完成")

# =======================================




# =======================================
# 在 settings.py 模組載入時執行此驗證函數, 進行環境變數驗證
validate_all_settings()

# 當其他檔案 import settings.py 時, Python 會執行整個 settings.py，執行到最後這行時就會呼叫 validate_all_settings() 函數進行環境變數驗證 (驗證所有必要的環境變數: (1) 缺乏「必要變數」: 程式無法啟動, (2)缺乏「非必要變數」: 顯示警告, 程式繼續)

# =======================================
