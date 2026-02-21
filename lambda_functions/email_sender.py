# email_sender.py
# AWS Lambda Function for Email Sending

# Trigger: AWS SQS (automatically triggered when messages arrive in queue)
# Function: Parse SQS messages and send emails via SMTP

# Deployment:
# - This file runs on AWS Lambda, independent of FastAPI
# - Always edit locally first, then deploy to Lambda Console
# - Do not edit directly in Lambda Console (except emergency fixes)


# ---------------------------

# AWS lambda_handler 函數: 
# 1. 功能: 在背景實際寄送 Email 
# 2. 實際行為: lambda_handler 函數從 SQS Queue 取得任務, 並實際在背景執行「寄信動作」
# 3. 被觸發執行的時機: 當 SQS Queue 有新訊息進來, AWS 就會自動觸發執行 lambda_handler 函數 (Lambda 由 AWS 管理輪詢)
# (1)「自動觸發」設定: 設定 Event Source Mapping, 告訴 AWS「當這個 SQS Queue 有訊息時，觸發這個 Lambda」. 觸發 Lambda 的事件(event)資料就是「Queue裡的訊息」
# (2)「輪詢」設定: 預設 Receive message wait time 0 秒 -> 短輪詢: Lambda 會每間隔 0 秒就問一次 SQS Queue 現在有沒有任務, 即使 Queue 是空的, Lambda會一直問、Queue也會一直立即回應沒有 (長輪詢 eg. 20秒: Lambda問 SQS Queue裡有沒有任務後, 若20秒內有任務進來, Queue 就會立即回應 Lambda, 若20秒內都沒有任務進來, Queue 會在 Lambda 發問後 20 秒才回應 Lambda 說沒有任務)


# ---------------------------

# 本檔案 (email_sender.py)會部署到 AWS Lambda Console, 獨立於 FastAPI 以外運行 (本機版本是供版控備份, 實際是 AWS Lambda Console 版本在運行):
# (1) 提醒: 不要在 Lambda Console 直接改程式碼, 而是「永遠只在本機改完此檔案程式碼並 git commit 後，再複製到 Lambda Console 後點 Deploy」, 在 Lambda Console 測試 (Lambda Console 有內建的測試功能，可以模擬 SQS 事件來測試 Lambda 函數)
# (2) 目的: 確保本機版本隨時與 AWS Lambda Console 上的版本相同
# (3) 例外: 除非是必須在 AWS 上緊急修復，但在 AWS 上修復完就要馬上同步回本機

# ---------------------------

import json
import smtplib    # 引入 smtplib (Python 內建的 SMTP 客戶端), 用來與信件伺服器（eg. Gmail SMTP）連線並送出信件
import os
from email.message import EmailMessage  # 從 email (Python內建的標準函式庫) 的 message模組 引入 EmailMessage類別, 用來建立 Email物件 


# 環境變數設定: 
# 這裡的 SMTP 環境變數是: 在 AWS Lambda Console 上設定 以及 被讀取, 不是「讀取專案資料夾 .env檔裡的 SMTP 環境變數」
SMTP_HOST = os.environ.get('SMTP_HOST')      
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER')      
SMTP_PASS = os.environ.get('SMTP_PASS')      



# ================================================
# 實際寄送 Email 的函數
# 參數: (1) to: 收件人 Email; (2) subject: 信件主旨; (3) body: 信件內容
# 無回傳值: 這個函數只負責「執行寄信動作」，成功就正常結束，失敗就拋出例外讓 lambda_handler 處理。不需要回傳值 
def send_email(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()                          # 建立一個新的 EmailMessage 物件, 代表「一封信」
    msg["From"] = f"Pitch-A-Seat <{SMTP_USER}>"   # 設定信件的「From」欄位
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)                         # 設定信件內容（純文字）, body 是內容 (字串)
    
    # 呼叫 SMTP 伺服器: 建立一個到 SMTP 伺服器的連線，啟用 TLS
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()                       # 對 SMTP 伺服器送出 EHLO 指令
        smtp.starttls()                   # 對伺服器送出 STARTTLS 指令
        smtp.login(SMTP_USER, SMTP_PASS)  # 登入 SMTP 伺服器，取得寄信權限
        smtp.send_message(msg)            # 把前面組好的 EmailMessage 物件送出去, 實際寄出信件給收件人


# ---------------------------    


# 1. 如果上面寄信動作的任何一步失敗，會拋出 smtplib.SMTPException, 由 lambda_handler 函數接住這個錯誤
# 2. 此函數和 email_utils.py 裡的 send_email 函數幾乎一樣 (都是實際執行寄信動作),
# 但此函數是獨立的: 因為此Lambda 函數在 AWS 上執行, 無法 import 專案其他模組（Lambda 環境獨立於 FastAPI），所以必須在此重新實作這個獨立的 send_email 函數
# 3. 兩個函數的錯誤處理策略不同:     
# (1) FastAPI 的 send_email 函數: 1.發生錯誤時只印 log, 不 raise, 不影響主流程 2.是 Fallback 的替代手段, 若這次再寄失敗就印 log 但不 raise   
# (2) Lambda 的 send_email 函數: 
# a. 發生錯誤時: 直接將錯誤拋出，讓外層 lambda_handler 決定要不要重試.
# b. 設計成將錯誤拋出的原因: 不 try-except, 而是直接讓錯誤往上拋, 由 lambda_handler 函數裡的 try-except 接住並決定處理方式 


# --------------------------- 


# ================================================






# ================================================
# Lambda 進入點的關鍵函數 (Lambda 需要知道「要執行哪個函數」，這個函數就叫做「進入點」（Entry Point）或「Handler」。在 Lambda Console 的設定中會指定 email_sender.lambda_handler) 
# 功能: 解析訊息、實際寄送 Email
# 參數: (1) event (SQS 訊息) (2) context (執行環境資訊)
# 回傳值: 執行結果 dict (方便看 log 確認) (如果是由 API 觸發 Lambda, 這個執行結果才會用來判斷是成功或失敗)
# 流程: 當 SQS Queue 有新訊息進來, (1) AWS 就會 自動觸發執行 lambda_handler 函數. (2) lambda_handler 函數會從 SQS Queue 取得任務, (3) 並實際在背景執行任務「寄信動作」(執行 send_email 函數)

def lambda_handler(event, context):
    # 1. 在 lambda 啟動的一開始, 先印出 Lambda 啟動訊息 log, 方便有必要時查流程情形
    print(f"Lambda 啟動，收到 {len(event['Records'])} 筆訊息")
    
    # 2. 在 for loop 開始前宣告這兩個變數並將值預設為 0，之後要用這兩個變數記錄處理結果
    success_count = 0
    fail_count = 0
    
    # 3. 用 for loop 遍歷所有 SQS 訊息 (任務), 原因: SQS 可能一次傳多筆訊息 (任務), 所以用 for loop 分批處理
    # 流程: 
    # (1) 解析 SQS 訊息內容 (當初發送任務進 Queue 時組裝的 message_body 內容)
    # (2) 檢查 SQS 訊息類型是否為 當初發送任務進 Queue 時設定的 type 
    # (3) 取出 Email 的實際資訊 (to: 收件人 email, subject: 信件主旨, body: 信件內容) 
    # (4) 實際進行「寄送 Email」的動作 
    # (5) 印出任務執行成功訊息 log, 並將 success_count 加一
    # (6) Lambda 成功完成任務 : lambda_handler 正常結束 -> SQS 刪除訊息

    for record in event['Records']:
        message_id = record['messageId']
        
        try:
            # Step 1: 解析 SQS 訊息內容 (當初發送任務進 Queue 時組裝的 message_body 內容)           
            raw_body = record['body'] # SQS 只接受字串，所以record['body']是字串，之後用json.loads轉為dict
            print(f"處理訊息 {message_id}: {raw_body[:100]}...")  # 印出 body 內容的 log 確認: 只印 body 內容的前 100 字元
            
            message = json.loads(raw_body) # 因為之後要使用 .get() 取 type 檢查，所以要把原本是字串的raw_body轉成Python dict
            

            # Step 2: 檢查訊息類型
            # 當初在 send_email_to_queue 有設定 type 是 "email" (未來可能有其他類型（如 "sms", "push"）) 
            # 若訊息類型不是 send_email_to_queue 函數設定的 email type, 就直接跳過這圈不執行, 繼續進行下一圈 for loop           
            if message.get('type') != 'email':
                print(f"未知的訊息類型: {message.get('type')}，跳過")  # 印出類型不符被跳過的訊息 log, 作為確認
                continue


            # Step 3: 從 body 的 payload 取出 Email 的實際資訊 (to: 收件人 email, subject: 信件主旨, body: 信件內容) 
            payload = message['payload']
            to = payload['to']
            subject = payload['subject']
            body = payload['body']
            

            print(f"準備發送 Email: to={to}, subject={subject}") # 印出 email收件人 和 信件主旨 log 作為確認


            # Step 4: 呼叫此檔案的send_email函數, 實際進行「寄送 Email」的動作
            send_email(to, subject, body)
            

            # Step 5: 印出任務執行成功訊息 log (包含成功任務訊息的 message_id )作為確認, 並將 success_count 加一, 之後可以看 log 確認執行情形
            print(f"Email 發送成功: {message_id}")
            success_count += 1
            

            # 走到這邊, Lambda 就成功處理完寄信任務了. 
            # 之後, Lambda 與 SQS 的整合機制 會自動做以下處理：
            # (1) lambda_handler 正常結束 (return), 沒有 raise -> 視為 Lambda 成功完成任務 ->「Lambda 與 SQS 的整合機制」自動刪除這筆任務訊息, 不需要人手動刪除 (AWS Lambda Service 通知 SQS 刪除訊息)
            # (2) lambda_handler 拋出例外 (raise) -> 視為 Lambda 任務失敗 -> 「Lambda 與 SQS 的整合機制」讓訊息回到 Queue 重試 (訊息在 visibility timeout 後重新可見，等待重試)
        

        # 若前面 Lambda 函數處理任務流程中的任一步發生錯誤, 就依不同情形進不同的 exception. 
        # 兩種 Exception 情形: 
        # (1) Lambda 函數 只印 log 不 raise: 一樣會 return result, 內含 200 和 fail_account, 視為 Lambda 成功完成任務, AWS Lambda Service 通知 SQS 刪除訊息
        # (2) Lambda 函數 直接 raise: 拋出例外, 視為 Lambda 任務失敗, 訊息回到 Queue 裡重試 

        # 錯誤情境一: SQS 訊息字串 的 JSON 解析失敗（ SQS 訊息格式錯誤）
        # 作法: (1) 印出 JSON 解析失敗 log、失敗的任務 id、實際錯誤訊息. 不 raise 拋出例外 (2) fail_count加一 (可看 log 追蹤失敗情形)
        except json.JSONDecodeError as e:            
            print(f"JSON 解析失敗 {message_id}: {e}")
            fail_count += 1


        # --------------------    
        # 只印 log 不 raise:
        # (1) 效果: 這筆錯誤訊息會被視為「處理成功」而由 AWS Lambda Service 通知 SQS 自動刪除 (必須由開發者從 fail_count 紀錄並看 log 檢查失敗任務)
        # (2) trade-off: 不會因一批任務裡的某一個任務 格式錯誤, 而導致整批執行失敗 (若某一筆有錯就 raise, 會整批任務（這次 Lambda 收到的所有 Records）都會被視為失敗，全部回到 Queue 重試; 若某一筆有錯但不 raise, 只有那筆不會重試（被視為成功刪除），其他正常處理. 也就是: 只會丟掉那一筆格式錯誤的訊息 (因為不 raise 會被視為任務成功), 而且可以看 CloudWatch Logs 有 fail_count 來輔助發現問題 (但就沒有機會當下被修復後重試)

        # 若想讓格式錯誤的訊息重試: 
        # 運作原理：
        # 1. Lambda 拋出例外 -> AWS Lambda Service 不呼叫 SQS 的 DeleteMessage API
        # 2. 訊息維持「處理中」狀態，visibility timeout 到期後重新可見
        # 3. 下一個 Lambda instance 取走訊息，重試處理
        # 4. 超過 maxReceiveCount（3 次）-> 訊息移到 DLQ
        # -------------------- 
        
        

        # 錯誤情境二: SMTP 發送失敗 (eg.網路問題、SMTP認證問題等)
        # 作法: (1) 印出 SMTP 錯誤 log、失敗的任務 id、實際錯誤訊息. 不 raise 拋出例外 (2) fail_count加一 (可看 log 追蹤失敗情形)    
        except smtplib.SMTPException as e:            
            print(f"SMTP 錯誤 {message_id}: {e}")
            fail_count += 1
            # 只印 log，不 raise (避免一直重試寄信到無效的 Email)，因此這筆訊息會被 SQS 視為「處理成功」而刪除。實務上可根據錯誤類型決定要不要加 raise 來拋出例外讓訊息回到 Queue 裡重試
        
        # --------------------    
        # 只印 log 不 raise:
        # (1) 效果: 
        # 這筆錯誤的任務訊息會被視為「任務處理成功」而被SQS刪除 (必須由開發者從 fail_count 紀錄並看 log 檢查失敗任務)
  
        # (2) trade-off: 
        # 不會因一批任務裡的某一個任務 SMTP 錯誤 (eg. 永久性問題: 收件人email無效 這種無論重試幾次都不會修復的狀況), 而導致整批執行失敗 (若某一筆有錯就 raise, 會整批任務（這次 Lambda 收到的所有 Records）都會被視為失敗，全部回到 Queue 重試; 若某一筆有錯但不 raise, 只有那筆不會重試（被視為成功刪除），其他正常處理. 也就是說, 只會丟掉單一有問題的訊息 (eg.收件人email無效), 而且可以看 CloudWatch Logs 有 fail_count 來輔助發現問題 
        # 但如果是暫時性網路問題 (eg. Gmail 伺服器暫時無回應而網路短暫中斷, 可能過一下重試就好了), 就沒有機會當下被修復後重試
        # (3) 改善方式: 
        # 分開不同錯誤類型, 暫時性網路問題使用 raise 拋出例外, 訊息就會回到 Queue 重試, 永久性問題就還是只印 log 不 raise

        # --------------------



        # 其他所有錯誤情境: 其他未預期的錯誤 
        # 作法: 一律 (1) 印 log、失敗的任務 id、實際錯誤訊息 (2) fail_count加一 (可看 log 追蹤失敗情形) (3) raise 拋出例外讓 Queue 重試任務 
        except Exception as e:            
            print(f"未預期錯誤 {message_id}: {e}")
            fail_count += 1
            raise   # raise 拋出例外，讓訊息回到 Queue 去重試這筆訊息任務
            # 不寫 raise e，而是寫 raise，能保留原始 stack trace, 更乾淨、更好追蹤原始錯誤
    


    # 4. lambda 處理任務成功並順利寄出信件後, 組裝 lambda_handler 函數的處理結果, 並將這個結果回傳給 AWS Lambda Service
    # Lambda 與 SQS 整合機制：
    # - 正常結束（return）→ AWS Lambda Service 通知 SQS 刪除訊息
    # - 拋出例外（raise）→ 訊息在 visibility timeout 後重新可見，等待重試
    # 注意：SQS 觸發的 Lambda 是看「有沒有拋出例外」，不是看回傳值的 statusCode


    # 這是 Lambda 的標準回傳格式 (statusCode 200 和 body內容), 回傳處理結果給 AWS Lambda Service 
    # 雖然本例是 SQS 觸發, 所以 SQS 只看有沒有 raise 來判斷任務是否成功, 不看回傳值的 200 和 body (所以 status code 不重要, body內容不是字串也沒關係). 但固定標準格式可以提升一致性(好維護)、可讀性(看log很清楚)、可擴展性 (未來如果要加 API Gateway 觸發 Lambda 就可以直接沿用格式) 
    # 若由 API Gateway 觸發 Lambda, Lambda回傳值會「直接變成 HTTP Response 回給使用者」, 所以必須有 StatusCode（HTTP 需要狀態碼）, body也必須是字串（HTTP body 是字串）
    result = {
        'statusCode': 200,                 
        'body': json.dumps({               
            'message': 'completed',        
            'success': success_count,
            'failed': fail_count,
            'total': len(event['Records'])
        })
    }

    # 5. 印出 lambda_handler 函數執行完畢的 log 資訊 (包含 result 內容) 作為確認
    print(f"Lambda 執行完畢: {result}")
    
    # 6. 實際回傳 lambda_handler 函數的處理結果給 AWS Lambda Service
    return result




# ----------------------------
# 當 SQS Queue 有任務訊息時, AWS 會觸發 Lambda, 執行 lambda_handler 函數 (AWS Lambda Service 自動呼叫 lambda_handler 函數)。AWS 會: 
# (1) 啟動這個 Lambda (2) 把訊息包在 event 參數裡傳進 lambda_handler 函數 (3) 執行這個 lambda_handler 函數
# ----------------------------


# ----------------------------
# Exception 分不同種類的設計原則：已知的永久性問題不重試，未知問題預設重試（保守策略）. eg.
# 1. JSONDecodeError: 不 raise. 原因: 格式錯誤是永久性問題，重試也沒用
# 2. SMTPException:   不 raise. 原因: 可能是收件人無效，重試也沒用
# 3. 未預期錯誤:        raise.   原因: 可能是暫時性問題（如記憶體不足），重試可能成功
# ----------------------------




# ----------------------------
# lambda_handler 函數

# event 參數 (dict): 
# SQS 傳來的事件，格式如下：
#     {
#         "Records": [
#             {"messageId": "abc", "body": "{\ "type\ ":\ "email\ ",...}"},
#             {"messageId": "def", "body": "{\ "type\ ":\ "email\ ",...}"}
#         ]
#     }


# 當初 send_email_to_queue函數送進 SQS Queue 的任務訊息內容 (Email資訊), 就是組裝成:
    # message_body = {
    #     "type": "email",
    #     "payload": {
    #         "to": to,
    #         "subject": subject,
    #         "body": body
    #     }
    # }
# 就是 events 參數的 Records 中的 body 內容
# messageId 是 AWS 自動給每一個 SQS Queue 中的新任務的編號. 但如果同一任務處理失敗, 在三次以內重新進到 Queue 裡重試, 該任務會沿用原本的編號, 因為: messageId 在訊息進入 Queue 時就分配了，重試時不會改變。這樣方便追蹤同一筆訊息的處理歷程


# ----------------------------



# ----------------------------
# json.loads 將 raw_body 字串轉成 dict:
# 因為之後要使用 .get()，所以要用 json.loads() 把原本是字串的 raw_body 轉成Python dict。否則會 AttributeError: 'str' object has no attribute 'get'。
# 若想使用 raw_body['type'] 也必須先用 json.loads() 把原本是字串的 raw_body 轉成 Python dict, 這樣 dict 就可以用字串當 key (這是更安全的寫法, 因為key 不存在時會回傳 None). 否則也會 TypeError: string indices must be integers (原因: 若沒轉成 dict 而用原本的字串來取, 會因為字串的 key 必須是整數、不能是字串 而報錯).  


# ----------------------------
# 用 json.dumps 把 result 的 body 從 dict 轉為字串:
# 如果 Lambda 是被 API Gateway 觸發 (本專案是由 SQS 觸發), 就必須將回傳值的 "body" 轉成字串，不能是 dict. 因為 API Gateway 需要把 body 直接回傳給用戶端，而HTTP Response Body 必須是字串

# ================================================