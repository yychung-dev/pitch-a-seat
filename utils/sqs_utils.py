"""
sqs_utils.py
AWS SQS Utility Module

Functions:
- get_sqs_client()        - Get SQS client (singleton pattern)
- send_email_to_queue()   - Send email task to SQS Queue
"""



import boto3  # AWS 官方 Python SDK，用來操作所有 AWS 服務
import json   # 用來把 Python dict 轉成 JSON 字串

# 從 settings 模組讀取操作 SQS 的環境變數設定 (SQS_EMAIL_QUEUE_URL: 具體會發到哪個 Queue 的 SQS Queue URL)
from config.settings import (
    AWS_ACCESS_KEY_ID, 
    AWS_SECRET_ACCESS_KEY, 
    AWS_REGION,
    SQS_EMAIL_QUEUE_URL
)



# 取得此模組專屬的 logger（繼承 app.py 中 basicConfig 設定的 root logger）
import logging
logger = logging.getLogger(__name__)




# ================================================
# 模組層級變數：在 import 時初始化為 None，整個程式執行期間都存在
# 
# 為什麼必須寫在函數外面（Singleton Pattern）：
# - 若寫在函數內，每次呼叫都會重設為 None，失去 Singleton 效果
# - 寫在函數外，變數在函數執行完後不會消失
# - 下次呼叫時可檢查是否已建立，避免重複建立連線

# Lazy Singleton (s3_utils 是 Eager Singleton)

_sqs_client = None 
# ================================================





# ================================================
# 商業邏輯 send_email_to_queue 函數呼叫此函數建立 SQS 客戶端: 此時連線到 SQS並取得 SQS 客戶端
def get_sqs_client():
    # 1. 用 global 宣告「要修改的模組層級的變數」
    global _sqs_client
    # 之後要在這個函數內用 boto3.client()方法修改「模組層級的變數 (_sqs_client)」, 所以必須先用 global宣告 (若只是要「使用」而非修改模組層級的變數, 可以不需要 global宣告, 可以直接使用)   
    
    if _sqs_client is None:
        # 先檢查是否有之前已建立過的 SQS 客戶端物件 (Singleton Pattern 原則: 避免每次都重新花時間連線到 AWS 來建立 SQS 客戶端物件)  
        # (1) 若之前尚未建立過 SQS 客戶端物件, 使用 boto3.client() 「第一次建立」 SQS 客戶端 (連線到 AWS 來建立)
        _sqs_client = boto3.client(
            'sqs',                                       # 指定要操作的 AWS 服務是 SQS
            aws_access_key_id=AWS_ACCESS_KEY_ID,      
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,  
            region_name=AWS_REGION  
        )
    
    # (2) 回傳「建立完成的 SQS 客戶端物件」給呼叫者 (send_email_to_queue函數): 可能是這次新建立的物件(有走進 if)，或之前已經建立好的 SQS 客戶端物件
    return _sqs_client  
    
    
    # -------------
    # 1. 使用 Singleton pattern 原則 取得 SQS client: 目的: 確保一個類別 (或物件) 在整個應用程式中只有一個實例。第一次呼叫get_sqs_client函數完並建立SQS客戶端物件後, 之後每次呼叫get_sqs_client函數就能直接回傳之前建立好的SQS客戶端物件。只要建立一次, 之後就能重複使用同一個Client, 不需要每次呼叫都重複建立網路連線 (因為網路連線來建立client物件需要花時間)
    # 2. 原理：每次呼叫 boto3.client() 都會建立新的網路連線. 如果每發一封 Email 都建立新連線，很浪費資源。

    # -------------
    # 1. _sqs_client 是「模組層級」的變數, 因為這個變數不在任何函數中. 模組層級的變數: 1.在檔案被 import 時就會執行並建立 2.整個程式執行期間都存在 3.可以被同一檔案的所有函數存取
    # 2. Python變數作用域原則: 若要在函數內「修改」「模組層級」的變數，就要先在函數內用 global 宣告要修改的那個「模組層級」的變數, 這樣修改到的才是那個「模組層級」的變數。若沒先用 global 宣告, 就會是「在這個函數裡新建立一個新的區域變數」，而不是修改那個「模組層級」的變數
# ================================================






# ================================================
# 呼叫此函數，將 Email 任務發送到 SQS Queue 裡
# 參數: (1) to: 收件人 Email; (2) subject: 信件主旨; (3) body: 信件內容    
# 回傳值: bool (True or False), 表示: 是否成功將「要寄信這個任務」發送到 SQS Queue 裡, 並非表示「Email 是否發送成功」  
def send_email_to_queue(to: str, subject: str, body: str) -> bool:
    
    # 1. 防禦性檢查：若 SQS_EMAIL_QUEUE_URL 未設定或為空，提前回傳 False
    # 先檢查 SQS_EMAIL_QUEUE_URL 這個環境變數是否「未設定」或是「空字串」. 優點: 
    # (1) 立即發現問題, 避免後續呼叫 boto3 時才失敗: 記錄清楚的 warning log (而非「在 sqs.send_message(後續呼叫 boto3 時) 時才失敗」)
    # (2) 錯誤訊息明確：「SQS_EMAIL_QUEUE_URL 未設定」 (而非「錯誤訊息模糊：boto3 的錯誤訊息」)
    # (3) 呼叫端知道是設定問題，可以 fallback (而非「呼叫端不確定是什麼問題」)

    if not SQS_EMAIL_QUEUE_URL:
        logger.warning("SQS_EMAIL_QUEUE_URL 未設定，改用同步發送")
        return False
    
    # 2. 進行「發送任務進 SQS Queue」的動作 (若第一步檢查確定 SQS_EMAIL_QUEUE_URL 這個環境變數有效, 就來進行發送進 Queue 的動作)
    try:
        # (1) 建立 SQS 客戶端物件: 呼叫 get_sqs_client 函數，建立 SQS client
        sqs = get_sqs_client()
        
        # (2) 組裝訊息內容: 要發送到 SQS Queue 裡的任務訊息內容 (Email資訊)
        message_body = {
            "type": "email",
            "payload": {
                "to": to,
                "subject": subject,
                "body": body
            }
        }
        
        # (3) 發送任務進 Queue: 「使用 SQS 客戶端物件」並呼叫「sqs.send_message 方法 (傳入: SQS Queue URL & 訊息內容 )」, 發送任務訊息到 SQS Queue 裡  
        response = sqs.send_message(
            QueueUrl=SQS_EMAIL_QUEUE_URL,                            # SQS Queue 的完整 URL: 要發送到哪個 Queue
            MessageBody=json.dumps(message_body, ensure_ascii=False) # 訊息內容: 將訊息內容轉成字串(SQS只接受字串）, 並讓中文正常顯示，看 CloudWatch Logs 才能看到正常中文，不會變成 \u4e2d\u6587 這種內容
        )
        
        # (4) 取出 MessageId 並印 info log 記錄成功:
        # 從 AWS 回傳的 response 取出 MessageId (追蹤用途): 可串連 FastAPI 和 Lambda 追蹤 log (單一訊息的完整生命週期)，Debug 時能快速定位問題。
        # 表示訊息(任務)已成功進入 SQS Queue
        message_id = response.get('MessageId') 
        logger.info(f"Email 任務已送入 SQS: {message_id}, to={to}")
        
        # (5) 回傳 True 給呼叫端: 回傳 True 給呼叫端 (send_email_async函數), 代表「成功發送任務進到 SQS Queue」 
        return True  

        
    # 若「嘗試發送任務進 SQS Queue 」的過程中有發生任何錯誤 (就不會走到 return True, 會在走到 return True 前就進到 Exception): 記一筆 exception log, 但不 raise 例外, 只是 return False, 讓呼叫端透過 return 值判斷接下來是否要 Fallback 到同步函數

    except Exception as e:
        # 為何用 return False 而不是 raise：
        # - 若 raise：例外會上拋到 send_email_async → API，可能導致 API 回 500
        # - 但此時 model 層的 commit 已完成，核心功能成功，只是寄信失敗
        # - API 回 500 會誤導前端以為整個操作失敗
        # - 用 return False：send_email_async 收到後 fallback 到同步寄信，不影響 API

        # logger.exception() 會自動附上完整 stack trace（包含錯誤訊息），不需要手動加 e 來看錯誤訊息       
        logger.exception(
            "發送到 SQS 失敗",
            extra={
                "email_to": to,
                "email_subject": subject,
            }
        )
        return False  # 「發送任務進到 SQS Queue」失敗, 回傳 False 給呼叫端 (send_email_async函數)
    

# ================================================





# ----------------------------

# 「_sqs_client = None」: 只是宣告變數，沒有連線
# 「第一次呼叫 get_sqs_client()」: 建立連線，建立完馬上被使用
# 「之後呼叫 get_sqs_client()」: 直接回傳已建立的物件，不重新連線
    
# ----------------------------

# 1. send_email_to_queue 函數是「Producer (生產者)」的角色：只負責把「要發 Email」這個任務送進 Queue 裡，但不是負責發送 Email 這個動作本身 (是由 lambda function 被 SQS Queue 裡的任務自動觸發後, 在背景去做「發送 Email 這個動作」)
  
# 2. 設計原則: (1) 「發送任務的動作」失敗不拋出例外 (best-effort), 只 return True 或 False, 由呼叫端的 send_email_async函數將流程導向「Fallback 到同步寄信」 (因為寄信通知是附加功能, 不要因寄信錯誤影響網站主要功能)) (2)記錄 log 供事後追蹤 (成功記info,失敗記exception)  


# ----------------------------

# 1. 防禦性程式設計：先檢查 SQS_Queue_URL, 若沒設定或是空字串 (無法有效找到正確的 Queue), 就直接回傳 False: 讓此函數的呼叫端知道「SQS不可用」，改採Fallback方案「同步寄送信件」
# 2. 把 Email 資訊包成一個 dict (message_body)，然後再用 json.dumps 轉成 JSON 字串
# (1) 原因：SQS 只接受字串
# (2) dict 內容: (a) "type": "email" -> 讓 Lambda 知道這是什麼類型的任務（未來可能有其他類型，如 "sms", "push_notification"）(b) "payload" → 實際的資料 
# (3) QueueUrl 和 MessageBody 是 AWS SDK (boto3) 要求的固定參數名稱 
# (4)ensure_ascii=False 讓訊息內容的中文可以在 CloudWatch Logs 正常顯示: 不會變成 \u4e2d\u6587 這類內容. eg. 有使用, 會輸出：{"type": "email", "payload": {"to": "user@gmail.com", "subject": "訂單通知", "body": "您的訂單 #123 已付款"}}。 
# 優點：可讀性高, Debug方便. 在 CloudWatch Logs 能看到正常中文, 易看懂訊息內容, 資料較小：\uXXXX格式會讓訊息 size 變大

# ----------------------------


# 模組層級變數：在 import 時初始化為 None，整個程式執行期間都存在

# 為什麼必須寫在函數外面（Singleton Pattern）：
# - 若寫在函數內，每次呼叫都會重設為 None，失去 Singleton 效果
# - 寫在函數外，變數在函數執行完後不會消失
# - 下次呼叫時可檢查是否已建立，避免重複建立連線


# ----------------------------


# 1.模組層級的變數：在 import sqs_utils.py (sqs_utils模組載入) 時就初始化為 None，整個程式執行期間都存在 
#   - 之後整個程式執行期間就可以直接用這個變數, eg. 在 get_sqs_client 函數內判斷 if _sqs_client is None: (檢查是否為None) )
# 2.必須寫在函數外面，否則每次呼叫函數都會重設為 None，失去 Singleton 效果: 
#   - 如果把 _sqs_client=None 寫在 get_sqs_client 函數裡面, 就變成: 每次呼叫 get_sqs_client 函數時都把 _sqs_client 設為 None, 那每次用 if 判斷後都要重新建立連線取得 SQS 客戶端, 失去 Singleton 效果

# 如果要在函數內使用_sqs_client這個變數, 就一定要宣告才能使用, 否則會是 NameError. 
# 如果要先宣告, 就一定要在函數外面先宣告, 因為這樣才能「實際發揮 Singleton Pattern 效果」. 
# 為什麼一定要使用_sqs_client這個變數, 而不是在get_sqs_client函數裡直接寫boto3.client來取得客戶端物件, 回傳給當下的呼叫端就好: 是因為我們想先把這次取得的客戶端物件單獨存起來 (而且是在函數外面存成全域變數_sqs_client, 這樣就不會因為上次函數執行完畢, 這個_sqs_client變數就消失, 而是可以讓下次呼叫這個函數時, 用之前存著沒有消失的_sqs_client變數內容來判斷是否為 None), 之後若再次呼叫 get_sqs_client 函數, 就能先檢查這個_sqs_client變數是否已存在且為 None, 若是 None 就要重新建立連線, 若不是 None 就能直接沿用該客戶端物件, 也是為了「實際發揮 Singleton Pattern 效果」.
    
# ----------------------------

# 若「嘗試發送任務進 SQS Queue 」的過程中有發生任何錯誤 (就不會走到 return True, 會在走到 return True 前就進到 Exception): 記一筆 exception log, 但不 raise 例外, 只是 return False, 讓呼叫端透過 return 值判斷接下來是否要 Fallback 到同步函數

# 若使用 raise: 例外會一路上拋到 send_email_async 以及呼叫 send_email_async的呼叫端 API, 若send_email_async和API沒特別處理, 最後變成: API會包成500回給前端 (但其實model層資料庫 commit已完成後才發生寄信錯誤. 導致: 核心功能完成、只是寄信失敗, API 卻回 500 執行失敗的訊息誤導前端)
# 若使用 return False, 不 raise: send_email_async 收到 False 後就知道改用同步寄信處理, 不會拋例外到最上層router層導致 API 500 錯誤 
# ----------------------------