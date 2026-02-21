"""
s3_utils.py
AWS S3 Upload Utility Module

Functions:
- upload_file_to_s3(file_content, file_name, content_type)   - Upload file to S3 and return CloudFront URL
- get_content_type(extension)                                - Get MIME type from file extension

Architecture:
- Files are uploaded to S3 bucket under 'tickets/' prefix
- CloudFront Distribution is configured to point to the S3 bucket
- Returns CloudFront URL for faster content delivery via CDN

Prerequisites:
- AWS credentials configured (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- S3 bucket created and CloudFront distribution configured
- Environment variables: S3_BUCKET_NAME, CLOUDFRONT_URL
"""


# 在 AWS Console 設定 CloudFront Distribution 指向特定 S3 Bucket, 設定好後: CloudFront 會自動快取並分發 S3 的內容，就可以直接在需要的程式碼中使用 CLOUDFRONT_URL (CLOUDFRONT域名) (eg. 本專案使用 CLOUDFRONT域名 來組裝每個檔案的實際 url)


import boto3     # AWS 官方 Python SDK，用來操作所有 AWS 服務
from botocore.exceptions import ClientError     # 保留供未來更精確的錯誤處理使用
from typing import Optional


# 從 settings 模組讀取操作 S3 的環境變數設定 (AWS IAM 存取金鑰 ID、AWS IAM 秘密存取金鑰、S3 Bucket 所在區域、S3 Bucket名稱、CloudFront 分發網域)
from config.settings import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_REGION,
    S3_BUCKET_NAME,
    CLOUDFRONT_URL,
)


# ================================================
# 初始化 S3 客戶端（Eager Singleton Pattern）

# boto3.client() 只是先在 import s3_utils.py 時就先建立好「客戶端物件」放著等其他程式碼呼叫, 但此時還沒有真正的網路連線
# s3_client.put_object: 使用 S3 客戶端物件呼叫 put_object 方法時, 才會真正建立與 AWS S3 服務的網路連線並發送請求

s3_client = boto3.client(
    "s3",                                       # 指定要操作的 AWS 服務是 S3
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)
# ================================================





# ================================================
# 函數功能: 上傳檔案到 S3 並回傳 CloudFront URL (呼叫此函數時, 才真正建立與 S3 服務的連線)
# 參數: 1.file_content: 上傳檔案的二進位內容 (bytes)  2.file_name: 要儲存在 S3 的檔案名稱（含副檔名） 3.content_type: 檔案的 MIME 類型，告訴瀏覽器這是什麼類型的檔案
# 回傳值: 若函數執行成功: 組裝完成的「檔案真實 url」字串, 若函數執行失敗: 回傳 None

# 呼叫端是: POST /api/sell_tickets
# 在 AWS Console 設定 CloudFront Distribution 指向特定 S3 Bucket, 設定好後: CloudFront 會自動快取並分發 S3 的內容，就可以直接在需要的程式碼中使用 CLOUDFRONT_URL (CLOUDFRONT域名) (eg. 本專案使用 CLOUDFRONT域名 來組裝每個檔案的實際 url)

# 流程: 先上傳到 S3 成功後 (確保S3 Bucket內確實有檔案), 再使用固定的 CLOUDFRONT_URL 組裝網址。
# 「先上傳再組裝」的商業邏輯設計： 確保 URL 指向的檔案確實存在. 如果先組裝再上傳(技術上可行, 因為CLOUDFRONT_URL在設定好指向時就已存在), 除了邏輯順序不合理, 如果 S3 上傳失敗, 結果是「有一個 URL，但指向一個不存在的檔案」, 若 URL 被點擊就會是 404 Not Found

def upload_file_to_s3(
    file_content: bytes,
    file_name: str,
    content_type: str = "image/jpeg"
) -> Optional[str]:

    try:        
        s3_client.put_object(            # put_object() 是 S3 固定的上傳方法
            Bucket=S3_BUCKET_NAME,       # Bucket: 目標的 S3 儲存 Bucket名稱
            Key=f"tickets/{file_name}",  # 檔案在 S3 中的路徑/名稱, 目的: 存放在 tickets 資料夾下，方便管理及識別上傳的檔案
            Body=file_content,           # Body: 檔案內容（bytes）
            ContentType=content_type,    # ContentType: 設定正確的 MIME 類型，讓瀏覽器能正確顯示圖片
        )
        
        # 使用 CLOUDFRONT_URL (CLOUDFRONT域名) 來組裝每個檔案的真實 url (eg.https://cloudfront域名/tickets/檔名.jpg) (檔名都是獨一無二的, 所以每個檔案的 url 也都是獨一無二)
        cloudfront_url = f"{CLOUDFRONT_URL}/tickets/{file_name}"
        
        # 回傳組裝完成的「檔案真實 url」
        return cloudfront_url

    except Exception as e:         
        # 接住所有錯誤 (較保守的寫法)
        # /api/sell_tickets中, 若呼叫此函數得到的回傳值是 None, 就 raise HTTPException(500, f"圖片上傳失敗：{image.filename}")        
        print(f"S3 上傳失敗: {e}")
        return None    # 回傳 None 給呼叫端


# ================================================


    

# ================================================
# 功能: 使用此函數將「一般檔案常見的副檔名 (eg. jpg)」轉換成「瀏覽器認識的 MIME類型 (eg. image/jpeg)」
# 使用時機: 在 POST /api/sell_tickets中呼叫 upload_file_to_s3 函數時, 作為 content_type參數的傳入值 使用

# 參數: 一般副檔名 (eg. jpg)
# 回傳值: MIME類型 (eg. image/jpeg), 根據參數傳入的副檔名, 回傳對照表中對應的 MIME 類型

def get_content_type(extension: str) -> str:    
    # 建立一個對照表: 把副檔名 (eg. jpg) 對應到 MIME 類型 (eg. image/jpeg)
    # sell_tickets API 有限制檔案副檔名只能是 jpg、jpeg、png三種其一
    content_types = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }


    # 語法: 從 content_types這個字典(對照表)中, 使用.get(key名, 預設值)方法查找 key名 來得到正確的 MIME類型. eg. content_types.get("jpg", 預設值) 就會得到 "image/jpeg" ("jpg"這個 key 對應的 value 是 "image/jpeg")並 回傳給呼叫端
    # 如果找不到 key 就回傳預設值 (application/octet-stream)
    return content_types.get(extension.lower(), "application/octet-stream")




    # --------------
    # extension.lower(): 把副檔名轉小寫（確保 "PNG" 和 "png"都能找到在字典中被找到, 因為一般檔案的有效副檔名可能是"PNG" 和 "png"）, eg. "PNG".lower() 會得到 "png", 就能對應到字典中的 "png" 這個 key名


# ================================================



# ------------------------------------------
# s3_utils.py 和 sqs_utils.py 都是 Singleton. (兩者的客戶端物件都可以重複使用，不需要每次上傳都建立新的 S3 客戶端物件 或 SQS 客戶端物件)

# 兩種 Singleton 寫法比較: 
# ----- s3_utils.py 的寫法（ Eager Singleton ）-----
# s3_client = boto3.client("s3", ...)  
# - import s3_utils 時就 「建立好」模組層級變數 (s3_client 客戶端物件), 之後就可以一直用 (整個程式期間只有這一個)
# (Python 不會重複 import 同一模組，所以 s3_client 只會在一開始 import s3_utils.py 時建立一次, 之後整個程式期間就重複使用之前建立好的同一個 S3 客戶端物件)


# ----- sqs_utils.py 的寫法（ Lazy Singleton ）-----
# _sqs_client = None  
# - import sqs_utils 時就「宣告」模組層級變數 (_sqs_client)，但這時先不「建立」模組層級變數」

# def get_sqs_client():
#     global _sqs_client
#     if _sqs_client is None:
#         _sqs_client = boto3.client('sqs', ...)  # 「第一次呼叫時才建立」模組層級變數 _sqs_client 且 同時建立與 SQS 服務的連線
#     return _sqs_client


# 兩者差異: 
# - Eager（s3_utils.py）：import 時就建立.      適合: 幾乎一定會用到的服務 (因為若根本沒用到, 還是在一開始import就會建立, 浪費資源). eg. 核心功能 (頻繁使用上架票券). 優點: 簡單直接   缺點: 若沒用到就會浪費資源
# - Lazy（sqs_utils.py）：第一次呼叫使用時才建立. 適合: 可能不會用到的服務 (因為只有用到時才會第一次呼叫建立, 若根本沒用到就不會浪費資源 ). 適合可能不會用到的服務. eg. SQS 有 fallback 機制, 如果 SQS_EMAIL_QUEUE_URL 沒設定就不會用到. 優點: 延遲初始化、節省資源  缺點: 寫法複雜 (需要函數 + global)

# 兩者相同: 
# 效果都是 Singleton: 模組層級變數在整個程式期間只有一個實例. 模組層級變數天生就是 Singleton
# ------------------------------------------



# ------------------------------------------
# 要使用 get_content_type 函數的原因: upload_file_to_s3 中的 ContentType 參數必須是 MIME 類型 (eg. image/jpeg), 不能是副檔名(eg. jpg), 因為: (1) S3 需要的是 MIME 類型 (2) 瀏覽器只看得懂 MIME 類型來決定該如何處理這個檔案 (eg. image/jpeg 告訴瀏覽器這是 JPEG 圖片，應該顯示它), 瀏覽器看不懂一般的副檔名 (eg. jpg) 
# 完整流程：
# 1. 上傳時設定 ContentType="image/jpeg" -> S3 儲存在 metadata (metadata: 在 Amazon S3 物件儲存中，除了實際檔案內容（Value）之外，一併儲存關於該檔案的描述性資訊 的中繼資料)
# 2. 瀏覽器用GET請求檔案時 -> S3/CloudFront 回傳的 HTTP Response 的 Content-Type: image/jpeg
# 3. 瀏覽器看到 Content-Type -> 知道這是圖片，直接顯示
# 結論:  S3 需要 MIME 類型是為了之後回傳給瀏覽器時能正確設定 Content-Type Header
# ------------------------------------------




# ------------------------------------------
# 設定預設值 "application/octet-stream"：
    
# 1.原因: 防禦性程式設計, 原則: 
# (1)函數的獨立性：get_content_type 是一個獨立的工具函數，這個工具函數不知道誰會呼叫它、傳什麼參數，這個工具函數只負責「接收副檔名然後回傳 MIME 類型」。
# (2)未來擴展：如果未來有其他地方呼叫這個函數，可能沒有做副檔名驗證 (現在是API端有先驗證, 限制傳入的檔案副檔名只能是這三種) 。若傳入字典不存在的副檔名，在.get()使用預設值可以避免程式因 KeyError 而崩潰
# (3)防止意外：萬一副檔名驗證邏輯被修改或繞過，至少不會因 KeyError 而崩潰

# 2.實務影響很小：因為上游 API 已經先驗證過副檔名只能是 jpg/jpeg/png，所以幾乎不會用到預設值。所以「保留預設值 "application/octet-stream"的設定而因此不小心掩蓋錯誤的風險」很低。主要目的是為了避免 KeyError , 所以這個 trade-off 可接受。(若希望更嚴格，可改成若找不到 key 就拋出例外)

# 3.application/octet-stream 是「通用二進位檔案」的 MIME 類型，意思是「我不知道這是什麼類型的檔案」. 瀏覽器收到這個類型時: 瀏覽器不會嘗試顯示而是直接下載. 瀏覽器也不會自動開啟檔案, 而是讓使用者自己決定用什麼程式開啟. 優點: 不會導致程式崩潰（避免 KeyError）、使用者還是能下載檔案. 缺點: 圖片不會直接顯示，而是被下載.

# ------------------------------------------