"""
games.py
Game and statistics APIs
- GET /api/events                  - Fetch games with available tickets for a given month
- GET /api/schedule                - Fetch all games for a given month
- GET /api/total_trades            - Get total completed trades count
- GET /api/total_amount            - Get total trading amount
- GET /api/top_games               - Get top 5 best-selling games this month (with Redis cache)
- GET /api/top_games_median_prices - Get median ticket prices for top 5 games
- GET /api/team_trade_rank         - Get trade count ranking by team
- GET /api/recommendations         - Get personalized game recommendations for a member
"""


from fastapi import APIRouter, HTTPException, Depends, Response
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import date, datetime, timedelta
import json
import math

from utils.auth_utils import get_current_user
from utils.redis_utils import get_redis_client

from models.game_model import (
    get_games_by_date_range, get_total_trades, get_total_trading_amount,
    get_top_games, get_top_games_with_median_prices,
    get_team_trade_rank, get_events,
    get_member_favorite_teams, get_trades_in_period, get_reservations_in_period, get_games_in_period, get_hot_games_in_period
)



# 取得此模組專屬的 logger（繼承 app.py 中 basicConfig 設定的 root logger）
import logging
logger = logging.getLogger(__name__)




# ================================================
# API 路徑前綴統一為 /api
router = APIRouter(prefix="/api", tags=["games"])
# ================================================




# Pydantic Model
# ================================================

# Game information model for /api/schedule response: Contains basic game details including date, teams, and venue.
class Game(BaseModel):
    id: int
    game_date: date
    stadium: str
    game_number: str
    team_home: str
    team_away: str
    start_time: str # 格式為 HH:MM，已轉字串



# Recommended game model for /api/recommendations response: Includes game details, recommendation score, and matching info.
class RecommendedGame(BaseModel):
    game_id: int
    game_date: str
    start_time: str
    team_home: str
    team_away: str
    stadium: str
    ticket_count: int
    recommendation_score: float
    trade_count: int
    favorite_team_match: bool

# ================================================




# API routes
# ================================================
# 取得當月所有有販售中票券的比賽資訊、每場比賽販售中的票券數量 API 
# 前端以「fetch(`/api/events?year=${y}&month=${m}`)」, 傳入查詢參數, 並對 /api/events 發出請求
# 公開 API (無需登入會員即可取得此 API)
@router.get("/events")
async def get_events_api(year: int, month: int):    
    try:
        events = get_events(year, month)
        for row in events:
            if isinstance(row["start_time"], timedelta): # 如果: row["start_time"] = timedelta(seconds=66900), row["start_time"] 不是字串，是 timedelta 物件
                total_seconds = int(row["start_time"].total_seconds())  # 把總秒數的 66900 從 timedelta 物件轉成 int
                hours = total_seconds // 3600                   # 取得小時數
                minutes = (total_seconds % 3600) // 60          # 取得分鐘數 (%3600取得餘數的秒數後再//60)
                row["start_time"] = f"{hours:02}:{minutes:02}"  # 將二位數補零 (如果 hours 或 minutes 沒有二位數的話)
        
        return events
    except Exception as e:
        print(f"查詢售票中場次失敗：{e}")
        raise HTTPException(status_code=500, detail="查詢售票中場次失敗")

# ================================================




# ================================================
# 取得當月所有存在的比賽資訊 API
# 前端以「fetch(`/api/schedule?year=${year}&month=${month}`)」, 傳入查詢參數, 並對 /api/schedule 發出請求
# 公開 API (無需登入會員即可取得此 API)
@router.get("/schedule", response_model=List[Game])
async def get_games_by_date(year: int, month: int):
    try:
        results = get_games_by_date_range(year,month)
        # print(results)        
        # 將 start_time（timedelta）轉為 HH:MM 格式字串
        for row in results:
            # print(row["start_time"])
            # print("$$$$$$$$$")
            if isinstance(row["start_time"], timedelta):
                total_seconds = int(row["start_time"].total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                row["start_time"] = f"{hours:02}:{minutes:02}"
                # print(row["start_time"])
                # print("@@@@@@")

        return results

    except Exception as e:
        print("資料庫錯誤:", e)
        raise HTTPException(status_code=500, detail="資料庫錯誤")
    
# ================================================






# ================================================
# 取得本網站累積的全部交易次數 API
@router.get("/total_trades")
async def get_total_trades_api():
    try:
        total_trades = get_total_trades()
        return {"total_trades": total_trades}
    except Exception as e:
        print("查詢交易總次數發生錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢交易總次數失敗")

# ================================================





# ================================================
# 取得本網站累積的全部交易金額 API
# 回傳值: 包裝成 Dict 後回傳給前端 (回傳給前端之前，FastAPI 會將 Dict 自動轉換成 JSON 格式、轉換成一個 JSON object)
@router.get("/total_amount") 
async def get_total_trading_amount_api(): 
    try:
        total_amount = get_total_trading_amount() 
        return {"total_amount": total_amount} 
    except Exception as e:
        print("查詢交易總金額發生錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢交易總金額失敗")

# ================================================




# ================================================
# 取得本月舉辦賽事的熱賣前五名排行榜 API
# 查詢本月舉辦比賽的「最熱賣場次前五名」 (比賽必須是本月舉辦的比賽, 但不限訂單成立日期)
# 回傳值: 
# 若「已付款、已出貨、且於本月舉辦的比賽資料」有五場以上, 回傳「比賽資訊、交易數量(訂單數量), 以 list 裝著前五名的 5 個 dict」; 
# 若「已付款、已出貨、且於本月舉辦的比賽資料」不足五場(eg.2場比賽), 回傳「比賽資訊、交易數量(訂單數量), 以 list 裝著名的 2 個 dict;
# 若「已付款、已出貨、且於本月舉辦的比賽資料」是 0 場, 回傳 [] (空list)

# 前端 fetch /top_games API 後的流程: 
# 1.先嘗試查詢快取 (最快) 2.沒有快取才查資料庫 (較慢) 3.查完資料庫把這次查到的前五名存入快取 (為下次請求這支 API 做準備) 4.回傳查詢的前五名結果
# 效益:(若一天內有 10000次 請求這支 API，第一次請求會去查資料庫並存入快取，後面9999人就直接從快取拿，效能好，降低server負擔)
@router.get("/top_games")
async def get_top_games_api():
    # 產生 Redis 鍵名（例如 "top_games:2025-07")
    current_year_month = datetime.now().strftime("%Y-%m")
    cache_key = f"top_games:{current_year_month}"

    logger.info(f"request start key={cache_key}") # 在 log 能一眼看到「這次請求用哪個 key」

    
    # 1.先查詢 Redis 快取內是否有資料
    try:
        # 呼叫 get_redis_client()，取得可以操作 Redis 的客戶端物件 
        redis_client = get_redis_client()

        logger.info(f"redis GET start key={cache_key}") # 若出問題, 可以區分「卡在 get_redis_client()」還是「卡在 get(cache_key)」

        cached_data = redis_client.get(cache_key) 
        
        if cached_data: # 這行不會拋錯：若沒有這個cache_key，cached_data 是 None, if cached_data 是 False, 會印出不會進 except， 會印出 cache MISS key={cache_key}後走進第二個 try 進行資料庫查詢
            logger.info(f"cache HIT key={cache_key} bytes={len(cached_data)}") # 區分是 hit 或 miss, bytes: 用以快速判斷存的東西是不是空的/太大/異常

            return json.loads(cached_data)   # 回傳 Redis 查詢結果後, 直接結束這支 API 流程, 不會去查資料庫
        
        logger.info(f"cache MISS key={cache_key}")  # 區分是「沒 key (miss)」還是「 Redis 出錯」(如果是「沒key」就會印出 cache MISS 這行 log; 如果是 Redis 出錯, 會進入 except 區塊，印出 Redis 連線錯誤，降級查詢資料庫: redis GET error key={cache_key} err={e}，不會印出 cache MISS)

    except Exception as e:   # 任何錯誤都會進到這裡（包括 Redis 錯誤、NameError、TypeError 等）
        logger.warning(f"Redis 連線錯誤，降級查詢資料庫: redis GET error key={cache_key} err={e}")  
        # Redis 的 except 只 print 不 raise。不因快取(輔助功能)壞了，就影響核心功能，讓使用者看不到排行榜
        # 同一個 API 可能很多 key（不同月份），印 key 才好查

    
    # 2.若無快取或 Redis 錯誤，降級查詢資料庫: 查詢本月舉辦的比賽中，最熱賣的前五名 (不限訂單成立時間)
    try:    # 外層 try：資料庫操作
        logger.info(f"DB query start (no cache)") # 從 log 一眼看出「為什麼走 DB」(因為沒有cache)

        top_games = get_top_games()  # router 層若發生錯誤, 會回拋錯誤並在這裡冒出來, 被 except Exception as e接住, 回 500

        logger.info(f"DB query done rows={len(top_games)}") # 確認回傳筆數符合預期（應為 5 或小於 5）. 避免沒發現 DB 回傳空資料 (因為如果 log 顯示 rows=0, 可以立即發現「這個月沒有任何熱門比賽資料」，而非等到前端顯示空白才發現問題)

        for row in top_games:
            # 格式化 game_date 為 YYYY-MM-DD：資料庫回傳的 game_date 是 Python 的 date 物件, 例如: datetime.date(2025, 7, 20), 必須將 date 物件轉換為字串, 轉換後: "2025-07-20", 前端收到的 JSON 才能正確解析
            if isinstance(row["game_date"], date):
                row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
                
        # 3. 查完資料庫將回傳結果寫入 Redis，並設定 TTL 
        try:    # 內層 try：Redis 操作
            # 呼叫 get_redis_client()，取得可以操作 Redis 的客戶端物件 (再取一次比較保險，因為若第一個 try 在 get_redis_client() 就失敗，那 redis_client 根本不存在。第二個 try 不要去依賴第一個 try 的結果。 get_redis_client() 通常是從連線池取之前已經建立好的連線, 不需花時間重新建立連線, 所以重新get_redis_client()再取一次連線的成本很低)
            redis_client = get_redis_client()

            logger.info(f"redis SETEX start key={cache_key} ttl=86400") # 表示「快取寫入開始」(若發生寫入成功/失敗，能以這行做區分)

            payload = json.dumps(top_games) # top_games 是 Python list，Redis 只能存字串，所以用json.dumps()轉成 JSON 字串, 並存入 payload 這個變數
            redis_client.setex(cache_key, 86400, payload) 
            # (1)把資料存入快取 
            # (2)設定 86400 秒（1 天）後自動刪除: 1 天後自動清除快取後的下次請求會重新查詢資料庫，確保排行榜保持最新狀態

            logger.info(f"redis SETEX ok key={cache_key} bytes={len(payload)}") # 確認「真的有寫入」且資料大小合理


        except Exception as e:  # 任何寫入快取過程(取得連線、轉換JSON字串、寫入快取)中發生的錯誤都會進到這裡（包括 Redis 錯誤、NameError、TypeError 等）    
            logger.warning(f"無法寫入 Redis 快取: redis SETEX error key={cache_key} err={e}")  
            # 不中斷 (不raise)，只 print log 
            # 若有多個 key, 這行能快速定位是哪個 key 出錯

                
        # 4. 回傳資料庫查詢結果
        return top_games     
        # 不管 Redis 寫入快取成功或失敗，都會執行到這裡 (因為 Redis 的所有錯誤都會被內層的 Exception 包住), 確保無論寫入成功或失敗, 都能回傳熱門比賽排行榜, 正常運作這個功能

    except Exception as e:
        logger.error(f"查詢資料庫本月熱門賽事前五名發生錯誤: {e}")
        raise HTTPException(status_code=500, detail="查詢本月熱門賽事排行榜失敗")
    # 只有資料庫查詢錯誤時，才會進到這個外層的 Except. 發生這類錯誤時會中斷 API, 無法回傳排行榜結果, 因為資料庫是「必要條件」, 資料庫錯誤就無法回傳正確排行榜資料

# -------------------------

# 若 get_top_games 函數查出的結果是一場比賽都沒有, 回傳值如何運作：
# 1.沒資料時, cursor.fetchall() 回傳[]（空 list），不是回傳 None。
# 2.for row in [] 的迴圈執行 0 次，直接跳過
# 3.快取存入 "[]" ( Redis 只能存字串 )
# 4.API 回傳值: []（空 list）

# 若有 bug 導致 cursor.fetchall() 回傳 None，for row in Noe 會 TypeError: 'NoneType' object is not iterable。但 cursor.fetchall() 的設計本身不會回傳 None，所以不需擔心這類情況。

# ================================================





# ================================================
# 取得本月熱賣場次前五名的票價中位數 API
# 1.如何篩選前五名比賽: 本月成立的訂單 (不限定於本月舉辦的比賽)、依單場比賽交易數量由多至少排序、取交易數量最多的前五名. 
# 2.例外處理: 交易數量相同的比賽: 依比賽舉辦日期由新到舊排序 (依 game_id排序), eg. 10/18 比賽 (3筆交易) 優先於 10/3 比賽 (3筆交易)
# 3.計算中位數: 計算前五名比賽的訂單金額中位數 
# 回傳值: 本月熱門前五名比賽 List (包含: 熱門前五名比賽的資訊、這五場比賽的訂單金額中位數 )
@router.get("/top_games_median_prices")
async def top_games_with_median_prices_api():
    try:
        games = get_top_games_with_median_prices()
        result = []  # 用新的 list 收集有效資料
        
        for row in games:
            if isinstance(row["game_date"], date):     # row["game_date"] = date(2026, 2, 24) 不是字串，是 date 物件. 
                row["game_date"] = row["game_date"].strftime("%Y-%m-%d") # .strftime("%Y-%m-%d") 把時間格式化成字串. eg.把 date(2025, 1, 23) 格式化成 "2025-01-23"
            if row["median_price"] is None:
                # 防禦性處理：
                # 正常情況下: median_price 不會是 None (不會發生取得某場次資訊, 但該場次沒有訂單而導致中位數計算為 NULL. 因為 SQL 指令中的 top_games 和 median_calc 條件同為「當月的已付款+已出貨訂單」)
                # 異常情況的處理方式: 1.印 log 追蹤問題 2.跳過異常資料、不顯示這場比賽資料, 而非「顯示中位數為 0 的錯誤資料、誤導網站使用者」
                print(f"[Warning] 場次 {row['game_id']} 中位數為 NULL (不應發生，請檢查 SQL 邏輯)，已跳過")
                continue
            
            row["median_price"] = int(row["median_price"])
            result.append(row)  # 只有正常的資料才加入 result
    
        return result  # 回傳過濾後的 result

    except Exception as e:
        print("查詢票價中位數發生錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢票價中位數失敗")    

# --------------------

# median_price 理論上不會是 None（兩個 CTE 條件相同）
# 但使用 LEFT JOIN + NULL 檢查作為防禦性處理: 1.確保錯誤能被發現 2.確保異常時有 log 可追蹤 3.同時使用 continue 跳過異常資料 (不顯示這場異常的比賽資料, 避免「顯示異常資料的中位數為 0 的錯誤資料、誤導網站使用者」)

# --------------------

# 格式化 game_date 為 YYYY-MM-DD：資料庫回傳的 game_date 是 Python 的 date 物件. 例如: datetime.date(2025, 7, 20). 所以必須手動將 date 物件轉換為字串 (date 物件無法直接轉成 JSON（或格式不可控）. 字串可以直接轉成 JSON), 轉換後: "2025-07-20", 前端收到的 JSON 才能正確解析
# JSON 只支援基本型別（字串、數字、布林、null、陣列、物件），不支援 Python 的 date 物件
# ================================================




# ================================================
# 取得各球隊的本月交易熱度 API
@router.get("/team_trade_rank")
async def team_trade_rank_api():
    try:
        teams = get_team_trade_rank()
        return teams
    except Exception as e:
        print("查詢球隊交易熱度發生錯誤:", e)
        raise HTTPException(status_code=500, detail="查詢球隊交易熱度失敗")

# ================================================




# ================================================
# 取得會員的個人化推薦賽事前五名 API
@router.get("/recommendations", response_model=List[RecommendedGame])
async def get_recommendations_api(
    response: Response,
    user: Optional[Dict[str, Any]] = Depends(get_current_user)
):
    try:
        today = datetime.now().date()
        past_90_days = today - timedelta(days=90)
        future_30_days = today + timedelta(days=30)
        future_60_days = today + timedelta(days=60)
        
        # Step 1: 取得會員喜愛球隊
        favorite_teams = []
        if user:
            user_id = user["user_id"]
            favorite_teams = get_member_favorite_teams(user_id)
            
        # 初始化隊伍得分 dictionary (會員喜愛球隊先給 2 分)
        team_scores = {team: 2.0 for team in favorite_teams}

        
        # Step 2: 查詢會員過去 90 天內的全部交易紀錄 (已出貨訂單)
        trades = get_trades_in_period(past_90_days)

        trade_contributions = []
        
        for trade in trades:
            days_diff = (today - trade["created_at"].date()).days  
            weight = 1.2 * math.exp(-0.01 * days_diff) 
            trade_contributions.append(weight) 
            for team in [trade["team_home"], trade["team_away"]]: 
                team_scores[team] = team_scores.get(team, 0) + weight


        # 正規化交易得分
        if trade_contributions:
            mean_trade = sum(trade_contributions) / len(trade_contributions)
            for team in team_scores: 
                if team not in favorite_teams: 
                    team_scores[team] = max(0, team_scores[team] - mean_trade)
                        
        
        
        # Step 3: 查詢會員過去 90 天內的全部預約紀錄 
        reservations = get_reservations_in_period(past_90_days)

        reservation_contributions = []
        for res in reservations:
            days_diff = (today - res["created_at"].date()).days
            weight = 1.0 * math.exp(-0.01 * days_diff)
            reservation_contributions.append(weight)
            for team in [res["team_home"], res["team_away"]]:
                team_scores[team] = team_scores.get(team, 0) + weight


        # 正規化預約得分
        if reservation_contributions:
            mean_res = sum(reservation_contributions) / len(reservation_contributions)
            for team in team_scores:
                if team not in favorite_teams:
                    team_scores[team] = max(0, team_scores[team] - mean_res)    


        # Step 4: 查詢未來 30 天比賽
        games = get_games_in_period(today, future_30_days)
        

        # Step 5: 計算推薦分數
        recommended_games = []
        for game in games:
            score = team_scores.get(game["team_home"], 0) + team_scores.get(game["team_away"], 0)
            # 加權熱門比賽 (目的: 交易量大的比賽，根據交易量把這場比賽的推薦分數多加一點分 )
            score += 0.1 * game["trade_count"]
            favorite_team_match = any(
                team in [game["team_home"], game["team_away"]] for team in favorite_teams
            )
            recommended_games.append({
                "game_id": game["game_id"],
                "game_date": game["game_date"].strftime("%Y-%m-%d"),
                "start_time": str(game["start_time"])[:5],
                "team_home": game["team_home"],
                "team_away": game["team_away"],
                "stadium": game["stadium"],
                "ticket_count": game["ticket_count"],
                "recommendation_score": round(score, 2),
                "trade_count": game["trade_count"],
                "favorite_team_match": favorite_team_match
            })


        # 過濾掉 0 分的個人化推薦比賽
        recommended_games = [g for g in recommended_games if g["recommendation_score"] > 0]
        # 按推薦分數降序排序
        recommended_games.sort(key=lambda x: x["recommendation_score"], reverse=True)
        top_games = recommended_games[:5]



        # Step 6: 冷啟動處理
        if len(top_games) < 5:
            needed = 5 - len(top_games) # 計算需要補幾場才能讓總數有 5 場
            
            # 查詢未來 60 天內有已出貨訂單紀錄的比賽 (依熱門程度由多至少排序, 取 needed+10 筆資料)
            hot_games = get_hot_games_in_period(today, future_60_days, needed + 10)
            # 用 needed+10 先多撈一些比賽，確保過濾掉重複game_id的比賽後, 總數量還足夠 (用 trade_count DESC 由多至少排出熱門順序)

            # 建立目前 top_games 中所有 game_id 的集合（用於快速查詢）
            existing_ids = {g["game_id"] for g in top_games}

            # 針對 hot_games 裡的個別比賽做 2 個檢查，檢查通過就 append 進 top_games
            for game in hot_games:
                # 檢查 1 : 每次進入 loop 的第一步都先檢查：目前是否已經補滿五場 (目的: 先檢查邊界條件，不符合就提前離開)
                if len(top_games) >= 5:
                    break
               
                # 檢查 2 : 檢查這圈 loop 的這場熱門比賽，是否與現存於 top_games 中的比賽 重複 (比對 game_id )
                if game["game_id"] not in existing_ids:
                    favorite_team_match = any(
                        team in [game["team_home"], game["team_away"]] for team in favorite_teams
                    )
                    # append 和 add 是「通過檢查後的動作」，所以必須在 if 裡面。
                    top_games.append({
                        "game_id": game["game_id"],
                        "game_date": game["game_date"].strftime("%Y-%m-%d"),
                        "start_time": str(game["start_time"])[:5],
                        "team_home": game["team_home"],
                        "team_away": game["team_away"],
                        "stadium": game["stadium"],
                        "ticket_count": game["ticket_count"],
                        "recommendation_score": 0.0,  # 冷啟動分數設為 0
                        "trade_count": game["trade_count"],
                        "favorite_team_match": favorite_team_match
                    })
                    
                    # 做完這圈 loop 比賽的 append 後，將這場比賽的 game_id 存進 existing_ids 中，目標: 更新 existing_ids 這個集合，避免後續重複 append (理論上，hot_games 中不會有重複的比賽，但避免意外，所以做這個設計)
                    existing_ids.add(game["game_id"])


        # step 7 : 冷啟動做完後，最後一次檢查排行榜是否有 5 場比賽。若仍不足 5 場，在前端 Response Header 做訊息提示、在後端印 log 提醒開發者
        if len(top_games) < 5:
            print(f"推薦比賽數量不足：目前僅有 {len(top_games)}場推薦比賽")
            # Header 只能用英文和數字 ( HTTP Header 只支援 ASCII 字元（或 latin-1 編碼），不支援中文字元 )
            response.headers["X-Recommendation-Message"] = f"Only {len(top_games)} games available"

        # step 8 : 記錄推薦結果（開發時用來調整和嘗試）
        logger.debug(f"Recommended games: {[g['game_id'] for g in top_games[:5]]}")


        # 在後端印出五場推薦比賽的資訊，作為確認 (開發階段)
        # print("\n=== Top 5 Recommended Games ===")
        # for idx, game in enumerate(top_games[:5], 1):
        #     print(f"Rank {idx}:")
        #     print(f"  Game ID: {game['game_id']}")
        #     print(f"  Date: {game['game_date']}")
        #     print(f"  Teams: {game['team_home']} vs {game['team_away']}")
        #     print(f"  Stadium: {game['stadium']}")
        #     print(f"  Recommendation Score: {game['recommendation_score']}")
        #     print(f"  Trade Count: {game['trade_count']}")
        #     print(f"  Favorite Team Match: {game['favorite_team_match']}")
        #     print(f"  Ticket Count: {game['ticket_count']}")
        #     print("-" * 40)
    
        # step 9 : 將 top_games 回傳給前端，再次確認只取前 5 名
        return top_games[:5]

    except Exception as e:
        print(f"查詢推薦場次錯誤: {e}")
        raise HTTPException(status_code=500, detail="查詢推薦場次失敗")

# ================================================
