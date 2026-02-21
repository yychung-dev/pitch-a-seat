# 匯入第二層 config.database 建立好的連線池
from config.database import get_connection

from typing import Dict, List, Any
from datetime import date
import json


# ================================================
# 查詢當月所有販售中的比賽、每場比賽販售中的票券數量
# 回傳值: 回傳列表 (內含每一場有販售中票券的比賽的資訊與販售中票券數量)
def get_events(year, month) -> List[Dict]:
    query = """
        SELECT
            g.id AS game_id,
            g.game_date,
            g.game_number,
            g.team_home,
            g.team_away,
            g.stadium,
            g.start_time,
            COUNT(t.id) AS ticket_count
        FROM games g
        JOIN tickets_for_sale t ON g.id = t.game_id
        WHERE t.is_sold = FALSE AND t.is_removed = FALSE
          AND YEAR(g.game_date) = %s
          AND MONTH(g.game_date) = %s
        GROUP BY g.id
        ORDER BY g.game_date
    """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query,(
                year,
                month,
            ))
            return cursor.fetchall()
# ================================================




# ================================================
# 查詢當月所有存在的比賽資訊 
# 回傳值: 回傳列表 (內含每一場比賽的資訊)
def get_games_by_date_range(year, month) -> List[Dict]:
    query = """
            SELECT id, game_date, stadium, game_number, team_home, team_away, start_time
            FROM games
            WHERE YEAR(game_date) = %s AND MONTH(game_date) = %s
            ORDER BY game_date, start_time
        """
    # with 語法 = 自動資源管理
    with get_connection() as conn:  # 從連線池中借出一條連線
        # 進入時：自動從池中借出連線
        with conn.cursor(dictionary=True) as cursor:  # 建立cursor，回傳結果使用「字典格式」
            # 進入時：自動建立游標
            # print(year,month)
            # print("**********")
            cursor.execute(query, (year, month))            
            results = cursor.fetchall()
            # 離開時：自動關閉游標
            # print(results)
            # print("**********")
            return results
        # 離開時：自動歸還連線到池中


# dictionary=False（預設）
# cursor.fetchone()  回傳 (15,)                  # 回傳的資料型態是 tuple, 必須用索引取值, 例如: result[0] 取得 15

# dictionary=True
# cursor.fetchone()  回傳 {"total_trades": 15}   # 回傳的資料型態是 dict，用欄位名取值, 例如: result["total_trades"] 取得 15
# ================================================




# ================================================
# 查詢訂單資料表中的全部交易次數(總數)
# 回傳值: 若有資料，返回次數總和 (int) (eg. return 30); 若無資料，返回 0 (int) 
def get_total_trades() -> int:
    query = """
        SELECT COUNT(*) AS total_trades
        FROM orders
        WHERE shipment_status IN ('已出貨', '已結案')
    """
    # with 語法 = 自動資源管理
    with get_connection() as conn:  # 進入時：自動從連線池中借出一條連線
        with conn.cursor(dictionary=True) as cursor:  # 進入時：自動建立 cursor，回傳結果使用「字典格式」
            cursor.execute(query)
            result = cursor.fetchone()  # 取得一筆結果
            # 離開時：自動關閉 cursor: cursor 在這裡關閉
        # 離開時：自動歸還連線到池中: conn 在這裡歸還到池中
    return result["total_trades"]  # 回傳查詢結果: 連線已歸還後，才執行 return

    # # COUNT(*) 永遠回傳數字（無資料時回傳 0），不會是 NULL: 
    # 這裡不需寫「return result["total_trades"] if result else 0」: 因為 COUNT(*) 在 SQL 中永遠會回傳數字，不會是 NULL。即使沒有任何資料，COUNT(*) 會回傳 0
    # 但 SUM 不同, 若沒有任何資料, SUM 會回傳 NULL. 所以 get_total_trading_amount() 需要 return result["total_amount"] or 0

# ================================================




# ================================================
# 查詢訂單資料表中的全部交易金額(總和)
# 回傳值: 若有資料，返回總和金額 (int) (eg. return 5560); 若無資料，返回 0 (int) 
def get_total_trading_amount() -> int:   
    query = """
        SELECT SUM(p.amount) AS total_amount
        FROM orders o
        INNER JOIN payments p ON o.id = p.order_id
        WHERE o.shipment_status = '已出貨'
        AND p.tappay_status = 'PAID'
    """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query)
            result = cursor.fetchone()
    
    return result["total_amount"] or 0 

# ================================================




# ================================================
# 查詢本月舉辦比賽的「最熱賣場次前五名」 (比賽必須是本月舉辦的比賽, 但不限訂單成立日期)
# 查詢條件: 已付款、已出貨、且於本月舉辦的比賽, 並且以交易數量(訂單數量)由多至少排序、取前五名
# 回傳值: 比賽資訊、交易數量(訂單數量), 以 list 裝著前五名的 5 個 dict
def get_top_games() -> List[Dict[str, Any]]: 
    query = """
        SELECT 
            g.id AS game_id,
            g.game_date,
            g.team_home,
            g.team_away,
            COUNT(o.id) AS trade_count
        FROM games g
        JOIN tickets_for_sale t ON g.id = t.game_id
        JOIN orders o ON t.id = o.ticket_id
        WHERE o.payment_status = '已付款'
          AND o.shipment_status = '已出貨'
          AND YEAR(g.game_date) = YEAR(CURDATE())    
          AND MONTH(g.game_date) = MONTH(CURDATE())  
        GROUP BY g.id, g.game_date, g.team_home, g.team_away
        ORDER BY trade_count DESC
        LIMIT 5
    """

    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor: # 若資料庫查詢出錯，會拋出 Exception, 原樣拋回上層 Router 層統一處理
            cursor.execute(query)
            results = cursor.fetchall()   # cursor.fetchall()取得回傳值的 python list 
    
    return results
# ================================================




# ================================================
# 查詢與計算 本月熱賣場次前五名的「票價中位數」
# 1.如何篩選前五名比賽: 本月成立的訂單 (不限定於本月舉辦的比賽)、依單場比賽交易數量由多至少排序、取交易數量最多的前五名. 
# 2.例外處理: 交易數量相同的比賽: 依比賽舉辦日期由新到舊排序 (依 game_id排序), eg. 10/18 比賽 (3筆交易) 優先於 10/3 比賽 (3筆交易)
# 3.計算中位數: 計算前五名比賽的訂單金額中位數 
# 回傳值: 本月熱門前五名比賽 List (包含: 熱門前五名比賽的資訊、這五場比賽的訂單金額中位數 )
def get_top_games_with_median_prices() -> List[Dict[str, Any]]:
    query = """
    WITH ranked AS (
        SELECT 
            tfs.game_id,
            tfs.price,
            ROW_NUMBER() OVER (PARTITION BY tfs.game_id ORDER BY tfs.price) AS rn,
            COUNT(*) OVER (PARTITION BY tfs.game_id) AS cnt
        FROM tickets_for_sale tfs
        JOIN orders o ON tfs.id = o.ticket_id
        WHERE o.payment_status = '已付款'
          AND o.shipment_status = '已出貨'
          AND YEAR(o.created_at) = YEAR(CURDATE())
          AND MONTH(o.created_at) = MONTH(CURDATE())
    ),
    median_calc AS (
        SELECT game_id, AVG(price) AS median_price
        FROM ranked
        WHERE rn IN (FLOOR((cnt+1)/2), CEIL((cnt+1)/2))
        GROUP BY game_id
    ),
    top_games AS (
        SELECT 
            g.id AS game_id,
            g.game_date,
            g.team_home,
            g.team_away,
            COUNT(o.id) AS sales_count
        FROM games g
        JOIN tickets_for_sale t ON g.id = t.game_id
        JOIN orders o ON t.id = o.ticket_id
        WHERE o.payment_status = '已付款'
          AND o.shipment_status = '已出貨'
          AND YEAR(o.created_at) = YEAR(CURDATE())
          AND MONTH(o.created_at) = MONTH(CURDATE())
        GROUP BY g.id, g.game_date, g.team_home, g.team_away
        ORDER BY sales_count DESC, g.id DESC
        LIMIT 5
    )
    SELECT 
        tg.game_id,
        tg.game_date,
        tg.team_home,
        tg.team_away,
        mc.median_price
    FROM top_games tg
    LEFT JOIN median_calc mc ON tg.game_id = mc.game_id
    """
    
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query)
            results = cursor.fetchall()
    
    return results

# ---------------------

# median_price 理論上不會是 None（兩個 CTE 條件相同）
# 但使用 LEFT JOIN + NULL 檢查作為防禦性處理: 1.確保錯誤能被發現 2.確保異常時有 log 可追蹤 3.同時使用 continue 跳過異常資料 (不顯示這場異常的比賽資料, 避免「顯示異常資料的中位數為 0 的錯誤資料、誤導網站使用者」)
# ================================================


    

# ================================================
# 查詢各球隊的本月成立訂單數量
# 查詢並計算: 個別球隊本月成立的訂單數量 (不限定於本月舉辦的比賽)、將六支球隊依本月成立訂單數量由多至少排序
# 回傳值: 六支球隊在本月各自成立的訂單數量 List
def get_team_trade_rank() -> List[Dict[str, Any]]:
    query = """
        SELECT 
            team,
            COUNT(*) AS trade_count
        FROM (
            SELECT g.team_home AS team
            FROM games g
            JOIN tickets_for_sale t ON g.id = t.game_id
            JOIN orders o ON t.id = o.ticket_id
            WHERE o.payment_status = '已付款'
              AND o.shipment_status = '已出貨'
              AND YEAR(o.created_at) = YEAR(CURDATE())
              AND MONTH(o.created_at) = MONTH(CURDATE())
            UNION ALL
            SELECT g.team_away AS team
            FROM games g
            JOIN tickets_for_sale t ON g.id = t.game_id
            JOIN orders o ON t.id = o.ticket_id
            WHERE o.payment_status = '已付款'
              AND o.shipment_status = '已出貨'
              AND YEAR(o.created_at) = YEAR(CURDATE())
              AND MONTH(o.created_at) = MONTH(CURDATE())
        ) AS teams
        GROUP BY team
        ORDER BY trade_count DESC
    """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query)
            results = cursor.fetchall()
    
    return results
# ================================================









# ================================================
# 查詢會員的喜愛球隊
# 回傳值: 若會員有設定喜愛球隊, 回傳 ["中信兄弟", "富邦悍將"] 或 ["統一獅"] ; 若會員沒設定喜愛球隊, 回傳 []
def get_member_favorite_teams(user_id: int) -> List[str]:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT favorite_teams FROM members WHERE id = %s",
                (user_id,)
            )
            member = cursor.fetchone()
            # eg. 若會員有設定喜愛球隊，資料庫中的 member 值是 :  {"favorite_teams": '["中信兄弟", "富邦悍將"]'} ; 若會員沒設定喜愛球隊，資料庫中的 member 值是 : {"favorite_teams": None}。

            if member and member["favorite_teams"]:
                favorite_teams_data = member["favorite_teams"]

                # 兼容兩種情況
                if isinstance(favorite_teams_data, str):
                    # 如果是字串，用 json.loads 轉換
                    return json.loads(favorite_teams_data)
                elif isinstance(favorite_teams_data, list):
                    # 如果已經是 list，直接回傳
                    return favorite_teams_data

            return []
# ================================================




# ================================================
# 查詢會員在過去 90 天內的所有交易紀錄 (依訂單成立日期為準, 查詢 90 天內所有已出貨訂單的資料. 不限於球賽舉辦日期)
# 回傳值: 每筆已出貨訂單的資料(主隊名、客隊名、訂單成立日期), 以 list 裝著每筆訂單資料 dict; 若無交易紀錄, 回傳[] 空 list
def get_trades_in_period(start_date: date) -> List[Dict]:
    trade_query = """
        SELECT g.team_home, g.team_away, o.created_at
        FROM orders o
        JOIN tickets_for_sale t ON o.ticket_id = t.id
        JOIN games g ON t.game_id = g.id
        WHERE o.shipment_status = '已出貨'
            AND o.created_at >= %s
    """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(trade_query, (start_date,))
            trades = cursor.fetchall()
    
    return trades
# ================================================




# ================================================
# 查詢會員在過去 90 天內的所有預約紀錄 (依預約成立日期為準, 查詢 90 天內所有預約的資料. 不限於球賽舉辦日期)
# 回傳值: 每筆預約的資料(主隊名、客隊名、預約成立日期), 以 list 裝著每筆預約資料 dict; 若無預約紀錄, 回傳[] 空 list
def get_reservations_in_period(start_date: date) -> List[Dict]:
    reservation_query = """
        SELECT g.team_home, g.team_away, r.created_at
        FROM reservations r
        JOIN games g ON r.game_id = g.id
        WHERE r.created_at >= %s
    """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(reservation_query, (start_date,))
            reservations = cursor.fetchall()

    return reservations
# ================================================




# ================================================
# 查詢未來 30 天內的所有比賽 
# 回傳值: 未來 30 天內的所有比賽 (包含: 個別賽事資訊 & 個別賽事的曾經上架的票券數量 & 個別賽事的已出貨訂單數量 ), 以 list 裝著每筆賽事資料 dict; ; 若無比賽資料, 回傳[] 空 list
def get_games_in_period(start_date: date, end_date: date) -> List[Dict]:
    games_query = """
        SELECT
            g.id AS game_id,
            g.game_date,
            g.start_time,
            g.team_home,
            g.team_away,
            g.stadium,
            COUNT(t.id) AS ticket_count,
            COUNT(DISTINCT o.id) AS trade_count
        FROM games g
        LEFT JOIN tickets_for_sale t ON g.id = t.game_id
        LEFT JOIN orders o ON t.id = o.ticket_id AND o.shipment_status = '已出貨'
        WHERE g.game_date BETWEEN %s AND %s
        GROUP BY g.id
    """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(games_query, (start_date, end_date))
            games = cursor.fetchall()

    return games
# ================================================




# ================================================
# 取得未來 60 天內的所有「有已出貨訂單」的比賽資訊 (依訂單成立數量由多至少排序作為熱門排序，總數限取 needed + 10 筆資料)
# 回傳值: 未來 60 天內的所有有已出貨訂單的比賽資訊 (包含: 個別賽事資訊 & 個別賽事的曾經上架的票券數量 & 個別賽事的訂單數量 ), 以 list 裝著每筆賽事資料 dict; ; 若無比賽資料, 回傳[] 空 list
def get_hot_games_in_period(start_date: date, end_date: date, limit: int) -> List[Dict]:
    hot_games_query = """
        SELECT
            g.id AS game_id,
            g.game_date,
            g.start_time,
            g.team_home,
            g.team_away,
            g.stadium,
            COUNT(t.id) AS ticket_count,
            COUNT(DISTINCT o.id) AS trade_count
        FROM games g
        JOIN tickets_for_sale t ON g.id = t.game_id
        JOIN orders o ON t.id = o.ticket_id
        WHERE o.shipment_status = '已出貨'
            AND g.game_date BETWEEN %s AND %s
        GROUP BY g.id
        ORDER BY trade_count DESC
        LIMIT %s
    """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(hot_games_query, (start_date, end_date, limit)) 
            hot_games = cursor.fetchall()

    return hot_games

# ================================================


