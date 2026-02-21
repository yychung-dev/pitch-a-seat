# 資料庫連線池初始化設置 


import mysql.connector.pooling        # 匯入 MySQL 官方的連線池模組     
from contextlib import contextmanager # 匯入 contextmanager 裝飾器 (就可以用 yield 語法建立 context manager（可搭配 with 使用的物件）)
from config.settings import DB_USER, DB_PASSWORD, DB_HOST, DB_NAME, DB_PORT    # 從第一層環境設定匯入資料庫設定值


# =======================================
# 資料庫連線池內容配置 (參數配置 ) : database.py 模組載入時執行一次
# 此時不會建立任何連線
db_config = {
    "user": DB_USER,
    "password": DB_PASSWORD,
    "host": DB_HOST,
    "database": DB_NAME,
    "port": DB_PORT,
    "connection_timeout": 10,  # 合理的超時時間: 若某次對資料庫的請求等超過 10 秒都無法連上資料庫, 就放棄並報錯. 如果某次請求等了超過 10 秒都無法連上資料庫 ( connection_timeout 只是控制「某次對資料庫的請求要等多久才放棄」，不會影響後續連線 )
}
# =======================================



# =======================================
# 建立資料庫連線池物件 : database.py 模組載入時執行一次
# 根據 db_config 的參數，預先建立 20 條資料庫連線, 這 20 條連線存在連線池裡，等待被借用
# database.py 模組載入時執行一次，之後 cnxpool 這個物件就一直存在
cnxpool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="mypool",      # 連線池的識別名稱
    pool_size=20,            # 池中預先建立 20 條連線
    autocommit=False,        # 預設不自動提交 SQL
    pool_reset_session=True, # 連線歸還池中時, 自動執行清除該連線的所有舊狀態
    **db_config              # 將原本裝成字典的 db_config 展開成關鍵字參數
)    
# =======================================





# =======================================
# 呼叫這個「從連線池取得健康連線的輔助函數」的函數: 從「已存在的連線池」借出連線 

# 使用裝飾器 @contextmanager ，把 get_connection 函數變成可以用 with 的形式 (@contextmanager 這個裝飾器物件可以搭配 with 使用)
# 在商業邏輯函數中要操作資料庫時，會先寫 「with get_connection() as conn:」 來取得連線 

# 「with get_connection() as conn:」觸發步驟 1, 2, 3
@contextmanager
def get_connection():                           # 角色: 從「已存在的連線池」借出連線: 每次有商業邏輯程式碼呼叫 with get_connection() as conn: 時, 就執行  get_connection 函數
    conn = cnxpool.get_connection()             # 步驟 1：從連線池借出一條連線
    try:
        conn.ping(reconnect=True)               # 步驟 2：檢查這條連線是否健康: 用 ping()送一個小封包給 MySQL, 檢查確認連線還活著，如果 ping 失敗（連線斷了）就自動重新建立連線 
        yield conn                              # 步驟 3：將連線交給呼叫者使用: 暫停這個 get_connection 函數，把 conn 連線交出去給呼叫者使用: (1)暫停這個函數，等呼叫者的 with 區塊執行完再繼續 (2) 把 conn 交給呼叫者的 with 區塊使用

        # =========== 暫停在這裡 =============
        # 等呼叫者的 with 區塊執行完才會繼續往下, with 區塊是指例如: 
        # with conn.cursor() as cursor:         # 步驟 4：呼叫者的資料庫操作邏輯程式碼
        #     cursor.execute("SELECT ...")
        #     result = cursor.fetchone()
        # ==================================
                                                # 步驟 5：
                                                # 離開內層 with 區塊 -> cursor 關閉
                                                # 離開外層 with -> 控制權回到 get_connection -> 觸發步驟 6
        
    finally:
        conn.close()                            # 步驟 6： 歸還連線到池中, 不是真的關閉連線 (無論呼叫者的 with 區塊是正常結束還是出錯，都會執行這個歸還動作)


# finally 確保連線一定會被歸還，無論呼叫者的 with 區塊有沒有出錯。
# 有 finally 的情況: 不管呼叫者的 with 區塊有沒有出錯, 一定會執行conn.close()這行。就算呼叫者的 with 區塊出錯, finally 區塊的 conn.close() 還是會執行, 正常歸還連線
# 沒有 finally 的情況: 如果呼叫者的 with 區塊出錯, conn.close()這行不會執行，這樣連線永遠不會歸還 -> 連線池慢慢耗盡


# 「關掉 cursor 之後，執行完 finally 才真的歸還連線」。

# @contextmanager def get_connection() 做的事: 取得健康的資料庫連線: 會 - 自動檢查連線是否存活 - 自動歸還連線 - 不自動 commit 資料庫指令, 而是讓呼叫者 (商業邏輯程式碼) 決定 commit 的時機


# =======================================



# =======================================
# 筆記:
# ---------------------------
# db_config 把多個資料庫設定值整理成字典, 方便傳入各種地方作為參數或進行其他操作 : 因為參數很多，所以集中設定較好重複使用, 例如: db_config 可以用在連線池,也可以用在單獨連線, 也可以印出來 debug (例: print(db_config))

# 合理的超時時間: 如果某次請求等了超過 10 秒都無法連上資料庫，就放棄並報錯。connection_timeout 只是控制「某次對資料庫的請求要等多久才放棄」，不會影響後續連線。
# connection_timeout 報錯後, 這個錯誤會往上拋被 router 層捕捉並回傳500給前端
# 接下來如何繼續使用資料庫: 下一個請求會重新嘗試連線資料庫, 讓請求自己嘗試重連資料庫, 開發者不需要做其他事. 例如:
# 請求 1 -> 連線失敗（資料庫暫時掛了）-> 回傳 500 錯誤
# 請求 2 -> 連線失敗 -> 回傳 500 錯誤
# 請求 3 -> 資料庫恢復了 -> 連線成功 -> 正常運作
# ---------------------------


# --------------------------    
# 「autocommit=False」:
# 預設不自動提交 SQL, 若要寫入資料庫(insert, update, delete) 都要記得手動 commit. 目的: 適合需要 Transaction 的場景: 可以執行多條 SQL 後一起 commit 或 rollback. 
    
# 注意: 若要寫入資料庫(insert, update, delete) , 執行完 SQL 指令後要手動 commit, 如果沒 commit 就斷開資料庫連線，(1)所有變更都會被 rollback (因為連線斷開前沒確認提交的變更會被撤銷) (目前沒有防禦做法，所以呼叫連線池物件的商業邏輯函數一定要記得commit, 否則會「資料明明沒更新, 但開發者以為有更新」). (2)連線會被佔用 (但有 helper 函數 (@contextmanager def get_connection(), 無論商業邏輯程式碼是否出錯，都會自動歸還連線)
# --------------------------


# --------------------------
# 「pool_reset_session=True」:
# 連線歸還池中時, 自動執行清除該連線的所有舊狀態, 否則下一位借到這條連線的呼叫者會繼承前一位使用連線者留下的垃圾. 垃圾例如: 
# 未完成的交易(忘記commit或rollback),透過這行可以自動把已歸還連線中未完成的交易直接rollback清掉，避免污染下一個借用連線的呼叫者; 
# 也能自動清除該連線上一位呼叫者的「查詢快取」、「session變數」;
# 也能自動釋放「所有鎖」(避免下一位呼叫者被前一位呼叫者的鎖卡住無法動彈)
# --------------------------


# --------------------------   
# 「**」 做的事: 把字典的 key 變成參數名稱，value 變成參數值，然後一個一個「攤開」傳進去. 所以「**db_config」就是「將原本裝成字典的db_config展開成關鍵字參數，展開成類似這樣: MySQLConnectionPool(user="abc", password="def", host="localhost")」
# --------------------------    


# --------------------------  
# 程式執行順序
# 【程式啟動時】（只執行一次）
# 程式啟動 -> 載入 app.py -> 執行 from routes import games 來載入 games.py -> games.py中的「from config.database import」載入database.py, 這時候就建立連線池了                       
# 1. from config.settings import ...    ← 載入設定                   
# 2. db_config = {...}                  ← 建立參數字典                
# 3. cnxpool = MySQLConnectionPool(...) ← 建立連線池，預建 20 條連線  
# 4. def get_connection(): ...          ← 定義好 get_connection 函數（但還沒執行 get_connection 函數內容）  


# 【每次 API 請求時】（每次請求都執行)
# 5. with get_connection() as conn:     ← 從連線池借出一條連線 (這時候才由商業邏輯程式碼呼叫並執行 get_connection 函數內容)          
# 6.     cursor.execute(...)            ← 執行 SQL                   
# 7.     conn.commit()                  ← 提交變更                   
# 8. # 離開 with 區塊                    ← 歸還連線到池中              
# --------------------------  

