"""
email_utils.py
Email Utility Module

Functions:
- send_email_async(to, subject, body)  - Send email asynchronously via SQS (with sync fallback)
- send_email(to, subject, body)        - Send email synchronously via SMTP (used as fallback)
"""



import smtplib # 引入 smtplib (Python 內建的 SMTP 客戶端), 用來與信件伺服器（eg. Gmail SMTP）連線並送出信件
from email.message import EmailMessage # 從 email (Python內建的標準函式庫) 的 message 模組 引入 EmailMessage類別, 用來建立 Email物件 
from config.settings import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SQS_EMAIL_QUEUE_URL  # 從 settings 模組讀取寄信用的環境變數設定: SMTP 伺服器位址、SMTP 連線 PORT、登入 SMTP 的帳號、登入 SMTP 的應用程式密碼(應用程式密碼 App Password, 非一般登入密碼為第三方應用程式產生的密碼) 

from utils.sqs_utils import send_email_to_queue


# 取得此模組專屬的 logger（繼承 app.py 中 basicConfig 設定的 root logger）
import logging
logger = logging.getLogger(__name__)






# ================================================
# 非同步寄信函數 (發送任務進 SQS Queue)
# 對外的統一介面:「業務邏輯函數或 API」呼叫此函數, 此函數進行「SQS發送任務」動作:
# 1. SQS 發送任務成功 (if success): 「寄信任務」順利進入 SQS queue, 後續由 Lambda function 被觸發後於背景執行「非同步寄信動作」
# 2. SQS 發送任務失敗 (if not success): 「寄信任務」無法進入 SQS queue, 直接呼叫send_email函數, 執行「同步寄信動作」

# 參數: (1) to: 收件人 Email; (2) subject: 信件主旨; (3) body: 信件內容 
# 無回傳值: 若執行成功, 就結束函數後返回呼叫端, 最後返回到 API 層 ; 若執行失敗, 就記 warning log後, Fallback 到 send_email同步寄信函數

def send_email_async(to: str, subject: str, body: str) -> None:
    # 呼叫 send_email_to_queue 函數, 將寄信任務發送到 SQS Queue 裡 
    # 「發送到 SQS」是同步操作，「Lambda 實際寄信」才是非同步（背景執行）
    success = send_email_to_queue(to, subject, body)
    
    if not success:
        # send_email_to_queue 回傳 False 的情況：
        # 1. SQS_EMAIL_QUEUE_URL 沒設定 或 設成空字串
        # 2. SQS client 建立失敗
        # 3. sqs.send_message() 執行失敗

        # 這時候 fallback 到同步發送: 如果發送任務到 SQS 的動作失敗，就改用原本的同步寄信函數send_email執行同步寄信動作
        logger.warning(f"SQS 發送失敗，fallback 到同步發送: {to}")
        send_email(to, subject, body)

# 設計原則: 1. SQS 正常時: 快速執行任務後, API 可更快回應, 實際寄信動作由背景處理  2. SQS 異常時: 直接降級成同步寄信, 功能不中斷
# ================================================









# ================================================
# 同步寄信函數
# 參數: (1) to: 收件人 Email; (2) subject: 信件主旨; (3) body: 信件內容 
# 無回傳值: 若成功, 就記info log後返回呼叫端, 最後返回到 API 層 ; 若失敗, 就記 exception log (不raise), 記完log就返回呼叫端, 最後返回到 API 層 
def send_email(to: str, subject: str, body: str) -> None:
    # 若 send_email_async 執行失敗, 就 Fallback 到這個同步寄信函數 (best-effort 原則): 
    # (1)寄信成功：記一筆 info log 
    # (2)寄信失敗：記一筆 exception log, 但不 raise 例外, 讓交易流程照常進行 (不被寄信這個輔助功能影響核心交易流程)
    try:
        msg = EmailMessage()                        # 建立一個新的 EmailMessage 物件, 代表「一封信」
        msg["From"] = f"Pitch-A-Seat <{SMTP_USER}>" # 設定信件的「From」欄位
        msg["To"] = to                              # 設定收件人欄位為傳進來的 to
        msg["Subject"] = subject                    # 設定信件主旨                        
        msg.set_content(body)                       # 設定信件內容（純文字）, body 是內容 (字串)
        
        # 呼叫 SMTP 伺服器: 建立一個到 SMTP 伺服器的連線，啟用 TLS
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            # 對 SMTP 伺服器送出 EHLO 指令，告訴對方「我這邊是哪台客戶端」，並取得伺服器支援的擴充功能.通常是啟用 TLS 前的標準動作
            smtp.ehlo()
            # 對伺服器送出 STARTTLS 指令，把連線升級為加密的 TLS 連線（避免敏感資訊與信件內容以明文傳輸）
            smtp.starttls()
            # 使用 SMTP_USER / SMTP_PASS 登入 SMTP 伺服器，取得寄信權限
            smtp.login(SMTP_USER, SMTP_PASS)
            # 把前面組好的 EmailMessage 物件送出去, 實際寄出信件給收件人
            smtp.send_message(msg)
        
        logger.info(f"Email 已成功寄送至 {to}，subject={subject!r}")  # 若前面寄信動作都成功, 記一筆 info log

    except Exception as e:      
        # 若前面寄信動作任一步出錯 (eg. 連線失敗、登入失敗、寄信失敗), 就用 exception log 記錄錯誤 + stack trace. 但不 raise, 呼叫端(商業邏輯) 能繼續執行, 不讓寄信功能錯誤而影響網站核心功能
        # 設計原則：寄信是輔助功能，不應影響核心交易流程
        
        # 為何不 raise：
        # - model 層設計成 commit 後才寄信，確保核心功能已完成
        # - 若這裡 raise，例外會回拋到 router 層，導致 API 回 500
        # - 後果：資料庫成功寫入，但前端收到 500，與真實情況不符
        # - 所以寄信函數也要設計成不 raise，貫徹「不影響核心流程」原則

        logger.exception(
            "寄送 Email 失敗",
            extra={
                "email_to": to,
                "email_subject": subject,
            },
        )


# logger.exception 會自動帶上 stack trace, 方便看錯誤流程
# extra 是 logging API 提供的一個參數, 可以附加自訂欄位. 本例: log 會印出收件者和信件主旨, 方便查錯
# ================================================


# --------------------
# 為何不 raise：
# - model 層設計成 commit 後才寄信，確保核心功能已完成
# - 若這裡 raise，例外會回拋到 router 層，導致 API 回 500
# - 後果：資料庫成功寫入，但前端收到 500，與真實情況不符
# - 所以寄信函數也要設計成不 raise，貫徹「不影響核心流程」原則
# (若設計有 raise, 這個函數會拋錯(拋例外), 一路回拋到呼叫端 API, 可能會導致 API 失敗. eg. model層某函數最後一步是寄信動作, 但這裡寄信失敗後先把例外回拋給 model層函數, model層函數再把錯誤回拋給 router層, 被router層接住包成 500. 後果是: model層是資料庫commit完才寄信(不讓寄信失敗影響核心commit), 但若這裡拋錯導致 API 回 500, 狀況就變成: 資料庫成功寫入, 但卻因為寄信失敗導致前端收到代表 API 失敗 的 500 回應, 與真實情形不符、誤導前端. 所以, 為了貫徹「寄信是輔助功能，不應影響核心交易流程」原則, 除了 model層設計成commit後才寄信, 寄信函式也要設計成不 raise) 
# --------------------

