"""
redis_utils.py
Redis Connection Utility Module

Functions:
- get_redis_client()  - Get Redis client from connection pool

Architecture:
- Uses connection pool to manage Redis connections efficiently
- Connections are automatically returned to pool after use
- Supports concurrent access with configurable max connections
- Production environment uses SSL + AUTH token for AWS ElastiCache
- Development environment connects without SSL/password for local Docker Redis
"""


# 載入 redis-py 套件，用來連線到 AWS Redis 服務
import redis

# 從 settings 模組載入環境變數設定: ENV 變數 (當前環境: development / production) & REDIS 連線設定 
from config.settings import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, ENV



# ============================================
# 第一段：判斷目前是什麼環境
IS_PRODUCTION = (ENV == "production")
# settings.py 已經使用「ENV = os.getenv("ENV", "development")」來判斷當下環境，所以直接從 settings.py import ENV 變數來判斷環境是什麼
# 如果 .env 是 ENV=production, 則 IS_PRODUCTION = True
# 如果沒設定或設為其他值, 則 IS_PRODUCTION = False
# ============================================


# ============================================
# 第二段：建立「基本設定」dict
# 這四個參數在本機和生產環境都需要
pool_config = {
    "host": REDIS_HOST,         # Redis 伺服器位址（IP 或域名）
    "port": REDIS_PORT,         # Redis 伺服器 Port（預設 6379）
    "decode_responses": True,   # 自動將 Redis 預設回應 (bytes) 解碼為 str (優點: 不需要每次都手動 .decode("utf-8")、可直接用 json.loads() 解析)
    "max_connections": 10,      # 連線池最多保持 10 條連線
}


# ============================================




# ============================================
# 第三段：如果是生產環境，「追加」密碼和 SSL 設定 （AWS ElastiCache 需要）
# 寫法: 在 pool_config 這個 dict 裡面「新增」一個 key-value, eg. key 是 "ssl", value 是 True
if IS_PRODUCTION and REDIS_PASSWORD:
    pool_config["password"] = REDIS_PASSWORD  # 設定密碼: AUTH Token (AWS ElastiCache 密碼, 是 AWS ElastiCache 的認證機制 (redis-py會自動帶這個密碼去認證)，防止未授權存取）
    pool_config["ssl"] = True                 # 設定 SSL 開啟: 因為啟用 Encryption in transit, EC2 和 ElastiCache 連線傳輸的資料內容是有加密的（HTTPS/SSL加密）, 所以程式碼連線時 ( EC2連到ElastiCache時 )必須用 SSL, 否則連線會被拒絕
    pool_config["ssl_cert_reqs"] = None       # 設定 SSL「不驗證」憑證: VPC 內網不需驗證憑證
    # 因為 EC2 和 ElastiCache 在同一個 AWS VPC 中，不需擔心有其他惡意攻擊在 EC2 和 ElastiCache 中攔截篡改, 所以不需要「由 EC2 來 驗證 ElastiCache Redis 的身份憑證是否合法」 (而且因為 ElastiCache 的憑證是 AWS 內部發的, docker容器中沒有 AWS 內部的憑證清單, 除非下載 AWS 的憑證檔案放進 Docker, 才能成功驗證 ElastiCache Redis 並連線. 但因為 EC2 和 ElastiCache 就在同一個 AWS VPC 內網中, 所以夠安全, 不需要多此一舉. 所以最後選擇「不進行身份驗證」的方案)



# 執行到這裡，pool_config 會是：
# 本機環境：{"host": ..., "port": ..., "decode_responses": True, "max_connections": 10}
# 生產環境：{"host": ..., "port": ..., "decode_responses": True, "max_connections": 10, "password": ..., "ssl": True, "ssl_cert_reqs": None}
# ============================================




# ============================================
# 第四段：用 **pool_config 展開 dict 作為參數

# 建立連線池物件 (import redis_utils 模組時就建立) (此時還沒建立 Redis 客戶端物件和連線)
# 使用 redis.ConnectionPool() 方法建立連線池物件
REDIS_POOL = redis.ConnectionPool(**pool_config)

# ** 是「展開運算子」，把 dict 變成 「key=value」 參數
# 等同於：
# 本機：redis.ConnectionPool(host=..., port=..., decode_responses=True, max_connections=10)
# 生產：redis.ConnectionPool(host=..., port=..., decode_responses=True, max_connections=10, password=..., ssl=True, ssl_cert_reqs=None)
# ============================================






# ================================================
# 呼叫此函數時, 建立 Redis 客戶端物件 (呼叫端此時可取得 Redis 客戶端物件) (但還沒建立網路連線), 直到呼叫端「使用此物件執行 Redis 操作 (eg. get、set、setex等)」時, 才會建立網路連線 (去連線池拿閒置連線, 或若連線不夠就建立新連線, 上限是「同時有十條連線在池中」)
# 回傳值 : Redis 客戶端物件

# 「建立 Redis 客戶端物件」作法: 
# 使用 redis.Redis() 方法建立 Redis 客戶端物件, 之後可使用此物件「執行 Redis 操作 (eg. get、set、setex等)」
# redis.Redis(connection_pool=REDIS_POOL): 建立 Redis 客戶端物件時就指定使用 REDIS_POOL 連線池來管理連線 (不用每次都建立新連線, 提高效率). 之後使用 Redis 操作 (eg. get、set、setex)時, 就能直接從池中取出已建立的連線來操作 Redis
# 每操作完一次 Redis  (eg. cached_data = redis_client.get(cache_key)這個動作)，就自動將連線歸還到池中, 之後其他請求即可重複使用同一條連線 (原理: redis-py 的連線池會在每次操作完成後，自動把連線放回池中)
def get_redis_client():    
    return redis.Redis(connection_pool=REDIS_POOL)
# ================================================






