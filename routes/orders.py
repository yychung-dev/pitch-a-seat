"""
orders.py
Orders Management APIs 
- POST /api/match_request     - Create a match request and initialize a new order
- GET  /api/buyerOrders       - Get all orders for the logged-in user (as buyer)
- GET  /api/sellerOrders      - Get all orders for the logged-in user (as seller)
- POST /api/order_status      - Update order status (seller accepts/rejects match) and ticket status
- POST /api/tappay_pay        - Process payment via TapPay 
- POST /api/mark_shipped      - Mark order as shipped (seller only)
"""


from fastapi import APIRouter, HTTPException, Depends, Form, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional
import httpx
import json
from datetime import date, datetime, timezone

from config.settings import TAPPAY_PARTNER_KEY, TAPPAY_MERCHANT_ID, TAPPAY_ENV
from config.database import get_connection

from utils.time_utils import utc_now 
from utils.redis_utils import get_redis_client
from utils.auth_utils import get_current_user
from utils.email_utils import send_email_async

from redis.exceptions import ConnectionError, RedisError

from models.user_model import get_member_email


from models.order_model import (
    create_order, get_buyer_orders, get_seller_orders,update_order_and_ticket_status, get_payable_orders, create_payment_unpaid, mark_payment_failed, mark_payment_failed_due_to_api_error, mark_payment_failed_due_to_decline, commit_payment_success_tx, 
    update_order_shipped_atom, get_order_by_id, notify_shipped
)


# 取得此模組專屬的 logger（繼承 app.py 中 basicConfig 設定的 root logger）
import logging
logger = logging.getLogger(__name__)




# ================================================
# API 路徑前綴統一為 /api
router = APIRouter(prefix="/api", tags=["orders"])
# ================================================





# API Routes 
# ================================================

# 送出票券媒合請求的同時成立一筆新訂單 API
# 提出媒合請求同時就在orders資料表中成立一筆新訂單, 訂單狀態設為「媒合中」(等待賣家接受或拒絕 )
# 回傳值: API 執行狀態為 success, message為「媒合請求已送出」
@router.post("/match_request")
async def request_match_api(
    ticket_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):     
    try:
        buyer_id = current_user["user_id"]
        create_order(ticket_id, buyer_id)
        return {"status": "success", "message": "媒合請求已送出"}
    except HTTPException:
        # 對於 404 / 400 等 HTTPException，保持原樣丟出
        raise       
    except Exception as e:
        # 其餘錯誤 (eg.資料庫錯誤 (DB連線錯誤、SQL指令拼字錯誤))從 model 層原樣拋回 router層, 統一在這裡印 log 回 500
        logger.error(f"媒合請求錯誤: {e}")
        raise HTTPException(status_code=500, detail="媒合請求失敗")

# ================================================




# ================================================
# 取得當下登入會員的所有訂單 API（該會員作為買家的所有訂單）
# 回傳值: List (內含每一筆訂單的 dict), 依訂單成立日期由新至舊排序
@router.get("/buyerOrders")
async def get_buyer_orders_api(user: Dict[str, Any] = Depends(get_current_user)):
    try:
        buyer_id = user["user_id"]
        rows = get_buyer_orders(buyer_id)
        for row in rows:
            row["start_time"] = str(row["start_time"])[:5]
            
            # 必須先計算 weekday()，再執行 strftime() 來格式化 game_date. 因為 strftime() 會把 date 物件變成字串，字串沒有 .weekday() 方法。
            if isinstance(row["game_date"], date):
                row["weekday"] = ["一", "二", "三", "四", "五", "六", "日"][row["game_date"].weekday()]
                row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
            else:
                row["weekday"] = "--"  # 若 game_date 不是 date 物件，給予預設值
            
            row["stadium_url"] = {
                "大巨蛋": "https://maps.app.goo.gl/m53dt8TAUQkWXBvD9",
                "樂天桃園": "https://maps.app.goo.gl/otKHfBHksTKJk8uV8",
                "台南": "https://maps.app.goo.gl/Y4SgmRbEBCehqaH89",
                "天母": "https://maps.app.goo.gl/WGsmw7y38Apdkcsm7",
                "新莊": "https://maps.app.goo.gl/evnUECyJsLx3rkaE8",
                "澄清湖": "https://maps.app.goo.gl/T4wG6E4ED5jKnxaz6",
                "洲際": "https://maps.app.goo.gl/U6ZfbxwGp1t9APvN7",
                "嘉義市": "https://maps.app.goo.gl/rv8mNF2bnW5xuFcZ8",                
                "花蓮": "https://maps.app.goo.gl/UCvKfG29V7uEUc4G6",                                          
                "斗六": "https://maps.app.goo.gl/VmwmTQKSVQ5SBPVFA",
                "台東": "https://maps.app.goo.gl/9yAJEH2JvA5utWfx5",
            }.get(row["stadium"], "#")

            # 將 Decimal 轉成 float（ 因為 Decimal 無法 JSON 序列化 ）
            # 雖然 FastAPI 內部會使用jsonable_encoder自動把 Decimal 轉成 float, 但這樣寫可以讓程式碼意圖更明確、不依賴 FastAPI隱性行為, 將來若換框架或直接用json.dumps()，就不會出錯
            row["seller_rating"] = float(row["seller_rating"]) if row["seller_rating"] is not None else None
            
            # 將 JSON 字串轉成 list（資料庫存的是 JSON 字串）( 讓前端不用額外用JSON.parse()處理 JSON字串 )
            row["image_urls"] = json.loads(row["image_urls"]) if row["image_urls"] else []

            # 將 None 轉成空字串（ 讓前端不用額外處理 null ）
            row["note"] = row["note"] if row["note"] else ""

        return rows
    except Exception as e:
        logger.error(f"查詢買家訂單失敗：{e}")
        raise HTTPException(status_code=500, detail="查詢買家訂單失敗")

# ================================================





# ================================================
# 取得當下登入會員的所有訂單 API（該會員作為賣家的所有訂單）
# 回傳值: List (內含每一筆訂單的 dict), 依訂單成立日期由新至舊排序
@router.get("/sellerOrders")
async def get_seller_orders_api(user: Dict[str, Any] = Depends(get_current_user)):    
    try:
        seller_id = user["user_id"]
        rows = get_seller_orders(seller_id)
        for row in rows:
            # 將row["start_time"]這個資料庫回傳的 timedelta 物件(eg.timedelta(seconds=66600))轉成字串(eg."18:30:00"), 再取前 5 個字元 (eg."18:30")
            row["start_time"] = str(row["start_time"])[:5] 
            # 先計算 weekday，然後再格式化 game_date: 必須先計算 weekday()，再執行 strftime()。因為 strftime() 會把 date 物件變成字串，字串沒有 .weekday() 方法。
            # 檢查 game_date 是否為 Python 的 date 物件。正常情況下資料庫回傳的一定是 date 物件，但加上檢查是防禦性程式設計。
            if isinstance(row["game_date"], date):
                # 先計算星期幾: eg. row["weekday"] = "二"
                # 將row["game_date"]這個 date 物件 (eg. date(2026, 2, 12)) 用.weekday()回傳 0-6 的數字(週一=0，週日=6)
                # 用前面 0-6 的數字當索引值, 對應取得["一", "二", "三", "四", "五", "六", "日"]
                row["weekday"] = ["一", "二", "三", "四", "五", "六", "日"][row["game_date"].weekday()]
                # 然後格式化 game_date
                # row["game_date"]這個 date 物件 (eg.date(2026, 2, 12)), 用.strftime("%Y-%m-%d") 格式化成字串 (eg."2026-02-12")
                row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
            else:
                # 若 game_date 不是 date 物件（異常情況），給一個預設值 "--"，避免前端顯示錯誤。
                row["weekday"] = "--"  
            
            # 建立一個球場名稱對應 URL 的字典, 然後用 .get(row["stadium"], "#")來用球場名稱查詢 URL，找不到就回傳 "#"
            # eg. .get("大巨蛋", "#") → 回傳 "https://maps.app.goo.gl/m53dt8TAUQkWXBvD9"
            # eg. .get("木柵", "#") → 字典裡沒有 "木柵"，回傳 "#"
            row["stadium_url"] = {
                "大巨蛋": "https://maps.app.goo.gl/m53dt8TAUQkWXBvD9",
                "樂天桃園": "https://maps.app.goo.gl/otKHfBHksTKJk8uV8",
                "台南": "https://maps.app.goo.gl/Y4SgmRbEBCehqaH89",
                "天母": "https://maps.app.goo.gl/WGsmw7y38Apdkcsm7",
                "新莊": "https://maps.app.goo.gl/evnUECyJsLx3rkaE8",
                "澄清湖": "https://maps.app.goo.gl/T4wG6E4ED5jKnxaz6",
                "洲際": "https://maps.app.goo.gl/U6ZfbxwGp1t9APvN7",
                "嘉義市": "https://maps.app.goo.gl/rv8mNF2bnW5xuFcZ8",                
                "花蓮": "https://maps.app.goo.gl/UCvKfG29V7uEUc4G6",                                          
                "斗六": "https://maps.app.goo.gl/VmwmTQKSVQ5SBPVFA",
                "台東": "https://maps.app.goo.gl/9yAJEH2JvA5utWfx5",      
            }.get(row["stadium"], "#")
            
            # 將 Decimal 轉成 float（ 因為 Decimal 無法 JSON 序列化 ）
            # 雖然 FastAPI 內部會使用jsonable_encoder自動把 Decimal 轉成 float, 但這樣寫可以讓程式碼意圖更明確、不依賴 FastAPI隱性行為, 將來若換框架或直接用json.dumps()，就不會出錯 
            row["rating"] = float(row["rating"]) if row["rating"] is not None else None

            # 將 JSON 字串轉成 list（資料庫存的是 JSON 字串）( 讓前端不用額外用JSON.parse()處理 JSON字串 )
            row["image_urls"] = json.loads(row["image_urls"]) if row["image_urls"] else []

            # 將 None 轉成空字串（ 讓前端不用額外處理 null ）
            row["note"] = row["note"] if row["note"] else ""
        return rows

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查詢賣家訂單失敗：{e}")
        raise HTTPException(status_code=500, detail="查詢賣家訂單失敗")


# --------------------

# 將「HTTPException」和「Exception」兩種錯誤分段區分，實務上能清楚區分「業務相關錯誤(HTTPException)」與「系統錯誤(Exception)」. API 業務邏輯錯誤 ≠ 系統錯誤, 不把兩者混在一起. 若把所有錯誤不分類地全部包成 500，前端和後端維護者會被誤導.
# 業務邏輯問題: 要回 401/404/400, 要明確告訴前端, 前端可依此製作不同提示訊息
# 系統問題（資料庫發生錯誤、伺服器發生錯誤、API 發生錯誤）: 要回 500
# 區分兩類錯誤的優點:  1.錯誤語意清楚 2.後端維護更容易 3.程式可擴充性好: 若未來想新增更多種類的 HTTPException, 都能被原樣保留, 而不會沒分類地全被包成 500

# ================================================





# ================================================
# 更新訂單狀態(賣家接受或拒絕媒合)、更新票券狀態(若賣家接受就將票券標為已售)、通知買家媒合成功或媒合失敗 API
# 回傳值: API 執行狀態為 success
@router.post("/order_status")
async def update_order_and_ticket_status_api(
    order_id: int = Body(...),
    action:   str = Body(...),
    current_user: Dict[str,Any] = Depends(get_current_user)
):
    try:
        seller_id = current_user["user_id"]
        update_order_and_ticket_status(order_id, seller_id, action)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新訂單及票券狀態失敗: {e}")
        raise HTTPException(500, "更新訂單及票券狀態失敗")

    
# 只有賣家可以更新訂單狀態, 否則回 403 錯誤

# ================================================





# ================================================
# TapPay 付款 API 
# 呼叫 TapPay API, 根據不同結果 更新付款資料表 及 新增通知
@router.post("/tappay_pay")
async def tappay_pay_api(
    prime: str = Body(...),
    order_id: int = Body(...),
    user: Dict[str, Any] = Depends(get_current_user)
):
    # 1. 付款前, 先檢查:「訂單是否存在、有操作訂單權限(只有買家有權限付款)、訂單狀態現為「媒合成功」、付款狀態現為「未付款」」. 
    # 符合前述情況, 才能開始進行付款流程
    try:
        buyer_id = user["user_id"]
        amount, order = get_payable_orders(order_id, buyer_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查詢訂單時錯誤: {e}")
        raise HTTPException(status_code=500, detail="伺服器內部錯誤")  

    # 第一步確認後, 開始進行付款流程:
    
    # 2. 首先: 在 payments 資料表新增一筆付款紀錄
    # 作法: (1) 將 付款資料 的 tappay_status 欄位設為 UNPAID (2) 將 付款資料 的 amount 欄位插入 訂單金額
    # 目的: 若之後第三方 TAPPAY API 失敗, payments 表裡就先有一筆「曾經發起過付款的紀錄」，方便查問題 或 做後續處理更新  

    payment_id = None   # 先初始化 payment_id (防禦性設計) 
    
    try:
        payment_id = create_payment_unpaid(order_id, amount)    
    except Exception as e:
        logger.error(f"建立 payments 記錄錯誤: {e}")
        raise HTTPException(status_code=500, detail="伺服器內部錯誤")


    # 3. 呼叫 TapPay Pay By Prime API (打第三方 API) 
    # try:
    # 依據 TapPay 規則, 準備 url、headers、body 等資料, 然後利用這些資料 fetch TapPay API 進行付款 (寫法: await client.post())
    
    # except: 
    # 若 try 呼叫第三方 API 失敗 (eg. DNS問題、網路中斷、TapPay本身掛掉), (1) 將 付款資料 的 tappay_status 欄位設為 設為 FAILED (2) 將 付款資料 的 tappay_status_message 欄位更新為「"TapPay API 呼叫失敗"」(自定義的錯誤訊息) (3) 後端紀錄錯誤訊息(供排查) (4) 回給前端 500 及 detail:「呼叫 TapPay 金流失敗」
    # 目的: 看 log 就知道是第三方 API 掛掉造成的問題
    tappay_api_url = (
        "https://sandbox.tappaysdk.com/tpc/payment/pay-by-prime"
        if TAPPAY_ENV == "sandbox"
        else "https://prod.tappaysdk.com/tpc/payment/pay-by-prime"
    )

    headers = {
        "Content-Type": "application/json",
        "x-api-key": TAPPAY_PARTNER_KEY,
    }

    body = {
        "prime": prime,
        "partner_key": TAPPAY_PARTNER_KEY,
        "merchant_id": TAPPAY_MERCHANT_ID,
        "details": f"Order #{order_id} 支付",  # 自定義交易細節
        "amount": amount,
        "currency": "TWD",   
        "order_number": str(order_id),  # TapPay 在回傳物件中附上訂單編號
        # cardholder 資訊（可帶可不帶，但 TapPay 建議帶上, 可用於風險控管、對帳）
        "cardholder": {
            "phone_number": "",      # 若前端有帶 cardholder 資訊，可補上
            "name": "",
            "email": "",
            "zip_code": "",
            "address": "",
            "national_id": "",
        },
        "remember": False  # 是否要記錄付款卡片資訊，若不需要就設成 False
    }

    try:
        # 1.對 TapPAY API 發送 HTTP 請求 (非同步) (可同時處理多個請求, 提升併發處理能力)
        # 2.設定 timeout 10 秒 (避免無意義地消耗資源): 目的: 若每個請求都卡在外部 API 很久, 會佔掉連線和資源, 甚至拖垮 EC2 Server (雖然有async能避免整個卡住, 但依然會消耗資源並拖垮 Server)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(tappay_api_url, headers=headers, json=body) 
            # client.post(): 送出 HTTP POST 請求
            # json=body: httpx 自動把 body（Python dict）轉成 JSON 字串, 並設定正確的 request body 及 Content-Type            
            tappay_result = resp.json()
            # resp 是 httpx.Response 物件，包含 status_code、text、headers、content 等屬性 (如何取得屬性內容: resp.status_code、resp.text、resp.headers、resp.content)
            # resp.json(): 把 resp 這個 Response物件中的 response body（JSON字串） 解析成 Python dict , 方便讀取
            # tappay_result 是 dict
    except Exception as e:
        # 外層 except: 若 TapPay API 呼叫失敗，要 (1) 將 付款資料 的 tappay_status 欄位設為 設為 FAILED (2) 將 付款資料 的 tappay_status_message 欄位更新為「"TapPay API 呼叫失敗"」(自定義的錯誤訊息)
        logger.error(f"呼叫 TapPay API 失敗: {e}")
        try:
            mark_payment_failed_due_to_api_error(payment_id, "TapPay API 呼叫失敗")            
        except Exception as ex:
            # 內層 except: 連「更新付款資料的 tappay_stauts 為 FAILED」 和「更新tappay_status_message 欄位」的動作都失敗, 就印 log 在後端記錄錯誤訊息
            logger.error(f"更新 payments 失敗: TapPay API 呼叫失敗後，更新 payments 的 tappay_status 為 FAILED 的動作失敗: {ex}")
        
        # 無論「更新付款資料的 tappay_stauts 為 FAILED」 和「更新tappay_status_message 欄位」的動作成功或失敗, 都一定會 raise 500 和detail 給前端
        raise HTTPException(status_code=500, detail="呼叫 TapPay 金流失敗")

    
    # 4. 呼叫 TapPay API 成功後, 根據 TapPay 的回傳結果 (tappay_result), 進行 付款資料 (payments table)的後續 UPDATE 內容


    # TapPay 回傳 resp (response物件), 我們在前一步驟用 .json 「將 response body (JSON 字串) 轉換成 Python dict, 存入 tappay_result 這個變數」
    # 所以, 後續要讀取 TapPay 回傳結果, 就是透過讀取 tappay_result 這個 dict 來取得 (讀取結果都是 tappay 官方的回傳內容, 非我們自定義的內容)

    # TapPay 回傳的官方付款結果碼 (0: 付款成功; 非 0: 付款失敗 (不同號碼代表不同失敗原因) )
    tappay_status_code = tappay_result.get("status")
    # TapPay 回傳的官方訊息 (不是我自己定義的tappay_status_message)
    tappay_official_msg = tappay_result.get("msg", "")    
    # 交易識別碼 (TapPay官方提供), 能定位交易 (可用來對帳、查客服、追查交易)        
    tappay_rec_trade_id = tappay_result.get("rec_trade_id", "")       
    # 交易識別碼 (TapPay官方提供), 能定位交易 (可用來對帳、查客服、追查交易)
    tappay_bank_txn_id = tappay_result.get("bank_transaction_id", "") 

    if tappay_status_code == 0:
        # TapPay 授權付款成功：
        try:
            # (1)更新 付款資料 各個欄位 (UPDATE payments) (2) 通知賣家 (3) 回傳「API執行狀態為 success & 訂單編號」給前端 (前端可以使用「訂單編號」製作「付款成功後的提示訊息」)
            commit_payment_success_tx(
                payment_id, order_id, order, amount, tappay_rec_trade_id, tappay_bank_txn_id, tappay_status_code, tappay_official_msg)
            return {"status": "success", "order_id": order_id}
        except Exception as e:
            # 如果 try 的相關資料庫動作(更新付款資料&新增通知)失敗 (不包含寄信失敗的情形), 印 log 記錄, 回 500 及 detail 給前端 (detail 必須讓前端使用者知道是「付款動作有成功, 但資料庫動作失敗. 而非付款動作失敗. 避免誤導使用者對付款狀態的認知」)
            logger.error(f"更新付款結果到資料庫失敗: {e}")
            raise HTTPException(status_code=500, detail="付款結果已送出，系統暫時無法更新訂單狀態。若已扣款請聯繫客服並提供訂單編號。")
    else:
        # TapPay 授權付款失敗 (呼叫 TapPay API 成功, 但後續付款失敗)：
        # 外層 else: 若 TapPay 授權付款失敗，要 (1) 將 付款資料 的 tappay_status 欄位更新為 FAILED (2) 將 付款資料 的 tappay_status_code 欄位更新為「TapPay 回傳的官方付款結果碼」(3)將 付款資料 的 tappay_status_message 欄位更新為「TapPay 回傳的官方訊息 (非自定義的錯誤訊息)」
        try:
            mark_payment_failed_due_to_decline(payment_id, tappay_official_msg, tappay_status_code)
        except Exception as e:
            # 內層 except: 連「更新付款資料的 tappay_stauts 為 FAILED」、「更新tappay_status_code 欄位」、「更新tappay_status_message 欄位」的動作都失敗, 就印 log 在後端記錄錯誤訊息
            logger.error(f"TapPay 回傳失敗(status={tappay_status_code}, msg={tappay_official_msg})；更新 payments 的 tappay_status 為 FAILED 的動作失敗：{e})")
        
        # 無論更新付款資料的 tappay_stauts 為 FAILED」、「更新tappay_status_code 欄位」、「更新tappay_status_message 欄位」的動作成功或失敗, 都一定會 return 400 和 detail 給前端 (因為走進 else 就代表 TapPay 付款授權失敗, 使用者沒有成功付款) 
        
        # 這裡回 400 是因為「比較可能是客戶端的付款授權有問題, eg.信用卡額度不足, 屬於交易失敗(可預期)」, 而非「系統/網路/第三方API 不可用」. 
        # 前面呼叫 TapPay API 失敗回 500, 是因為屬於「系統/網路/第三方API 不可用 (不可預期)」 
        # detail是: 執行 API 進行付款的動作 failed , 回給前端的訊息是「TapPay 金流失敗：TapPay 官方回傳的訊息」(TapPay 官方回傳的訊息通常不會有敏感資訊, 所以可以回給前端和使用者看)    
        return JSONResponse(
            status_code=400,
            content={"status": "failed", "message": f"TapPay 金流失敗：{tappay_official_msg}"},
        )


# -----------
# 「先初始化 payment_id = None」是防禦性設計. 目前程式碼邏輯是「如果第二步失敗而沒在payments資料表拿到payment_id, 就不會走進第三步使用 payment_id 做資料庫操作」,所以不會出問題. 但若將來修改程式碼邏輯後有可能發生「payment_id 沒被成功賦值, 卻又在第三步使用 payment_id 做資料庫操作時, 發生NameError」, 所以還是先初始化 payment_id 作為防禦性寫法)


# ================================================


    

# ================================================
# 賣家出貨 API
# Transaction: 
# 作法: 若要在 Router 層建立一個 Transaction, 並在這個 Transaction內執行多個 Model 層的 DB Query 函數, 就必須:
# 先在 Router 層借用一條資料庫連線、共用同一個 cursor, 然後在 Transaction 內每次呼叫不同的 DB Query 函數時, 把同一個 cursor 作為參數傳入該特定 Query 函數, 這樣就能維持「每個資料庫函數操作時都是用同一條連線」, 這樣才能在同一個 Transaction 內操作不同資料庫函數. 否則, 若在每個不同的 DB Query 函數內各自借用連線, 那每個函數執行時就都是用不同的連線, 這樣就已經離開 Transaction. 可能在不同連線切換之間時, 就發生 race condition (eg. 有其他使用者發起新的 transaction 來操作資料)

# 流程: (1) 原子更新訂單狀態 (防止 race condition) (UPDATE orders) (2) 查詢訂單資料, 用於後續通知 (SELECT orders) (3) 通知買家 (INSERT INTO notifications) 同時查詢並暫存email通知資訊 (4) Commit (5) Commit 後再發送SQS (6) Commit 後再無效化快取

# 流程說明：
# - conn.commit() 執行完畢後，才呼叫 send_email_async
# - send_email_async 是同步函數，執行完畢後才會返回
# - send_email_async 內部設計為「永不 raise」，無論成功或失敗都正常結束
# - send_email_async 返回後，進行無效化快取動作 (不 raise)，最後一定會執行到 return {"status": "success"}，本 API 回傳 success {"status": "success"} 給前端，API 結束
# - 真正的「非同步」是 Lambda 從 SQS 取出任務並寄信，與本 API 無關

@router.post("/mark_shipped")
async def mark_shipped_api(
    order_id: int = Body(..., embed=True),
    user: Dict[str, Any] = Depends(get_current_user)
):    
    try:
        seller_id = user["user_id"]
        
        notification_data = None  # 在 with conn 外面先初始化 notification_data (「先初始化」是防禦性設計)

        with get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:            
                # 1. 原子更新訂單狀態: 只針對「存在的訂單」、「操作出貨者為賣家本人」、「付款狀態為已付款」且「出貨狀態為未出貨」的訂單資料, 進行「出貨狀態的更新」
                now = utc_now()
                rows_effected = update_order_shipped_atom(cursor, now, order_id, seller_id)

                # 原子更新失敗 (未執行更新), 接著查詢原因
                if rows_effected == 0:
                    # 取得這筆訂單資料, 目的: 檢查是訂單的什麼問題導致原子更新失敗 
                    order = get_order_by_id(cursor, order_id)

                    if not order:
                        raise HTTPException(status_code = 400, detail = "訂單不存在")
                    if order["seller_id"] != seller_id:   # 只有賣家可以標記訂單為已出貨
                        raise HTTPException(status_code = 403, detail = "無權操作此訂單") 
                    if order["payment_status"] != "已付款":
                        raise HTTPException(status_code = 400, detail = "訂單尚未付款") 
                    if order["shipment_status"] == "已出貨":
                        raise HTTPException(status_code = 400, detail = "此訂單已出貨")
                    
                    # 防禦性程式設計: 情境是 UPDATE 失敗，但上面四個條件都沒命中. 可能原因: 1. 資料庫狀態在查詢後又被改變（極端 race condition）2. shipment_status 有新的值（例如「處理中」），程式沒考慮到  3. 其他未預期的情況 
                    
                    # 出貨狀態並未更新成「已出貨」, 所以要中斷流程並回 400 提示使用者「訂單有問題」, 以免明明沒更新成「已出貨」, 還繼續後續寄信通知買家已出貨 (造成使用者誤解出貨成功, 但事實上並沒有成功)
                    raise HTTPException (status_code = 400, detail = "無法出貨")
                
                
                # 2. 若第一步的出貨狀態成功更新為「已出貨」，就查詢訂單資料, 目的: 用於後續通知
                order = get_order_by_id(cursor, order_id)


                # 3. 站內通知買家已出貨
                member_id = order["buyer_id"]
                msg = f"訂單 #{order_id} 已出貨，請確認物流"
                url = "/member_buy"

                # 新增一筆通知進資料表 (INSERT INTO notifications)
                notify_shipped(cursor, member_id, msg, url)


                # 4. 查詢買家 Email （在 commit 前查，因為需要 cursor）
                buyer_email = get_member_email(cursor, order["buyer_id"])
                # 暫存通知資料，commit 後再寄信
                notification_data = {
                    "to": buyer_email,
                    "subject": "Pitch-A-Seat 訂單出貨通知",
                    "body": f"訂單 #{order_id} 已出貨，請留意物流資訊\n詳情請至：我的購買頁"
                }
            
            # 5. Transaction Commit: Router 層決定何時 commit: 前述動作都做完，才一起 commit。
            conn.commit()   
        
        # 6. Commit 成功後，才寄信 (發送任務到 SQS Queue 裡) 
        if notification_data:
            send_email_async(
                to=notification_data["to"],
                subject=notification_data["subject"],
                body=notification_data["body"]
            )
        

        # 7. Commit成功後，才無效化快取 (要確保出貨狀態確實已更新為「已出貨」後 (才有清除快取的必要), 再清除快取)
        try:    
            # 無效化 Redis 快取
            # 產生 Redis 鍵名（例如 "top_games:2025-07")
            current_year_month = datetime.now().strftime("%Y-%m")
            cache_key = f"top_games:{current_year_month}"               
                
            # 呼叫 get_redis_client()，取得可以操作 Redis 的客戶端物件
            redis_client = get_redis_client()

            # 刪除原本的快取資料 (出貨後，該訂單變成「已出貨」, 排行榜的統計會改變（多了一筆已完成交易）, 刪除舊快取，讓下次fetch /api/top_games 查詢資料庫後寫入最新資料)
            deleted = redis_client.delete(cache_key)
            
            logger.info(f"已無效化快取: cache INVALIDATE key={cache_key} deleted={deleted}")

        except Exception as e: # 任何錯誤都會進到這裡（包括 Redis 錯誤、NameError、TypeError 等）
            logger.warning(f"無法無效化 Redis 快取: cache INVALIDATE error key={cache_key} err={e}")  # 若只是 Redis 刪除出錯, 不 raise，讓 API 正常回傳成功 (不讓 Redis 這個輔助功能影響 出貨 這個核心功能)


        return {"status":"success"}  # 前述所有出貨動作做完，回傳結果告知前端，「出貨確認」動作已成功完成 (出貨 API 執行狀態為 success) 
        # 只要 Transaction Commit 成功就一定會走到這行 return. 無論寄信和刪除快取是成功或失敗, 都不會 raise, 都會走到這行 return 
        # return {"status":"success"} 這行程式碼位於 try 區塊內，所以只要前面的程式碼沒有 raise exception，就會執行到這行 return 

    except HTTPException:
        # Transaction 中任何因 HTTPException 而 raise 的錯誤, 原樣拋出
        raise
    except Exception as e:
        # # Transaction 中發生的任何其他錯誤, 包成 500 並提示 detail
        logger.error(f"賣家出貨發生錯誤: {e}")
        raise HTTPException(status_code=500, detail="出貨失敗")                                   


# ================================================