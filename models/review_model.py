from config.database import get_connection

from typing import Optional, Dict, List, Any
from fastapi import HTTPException


# ================================================
# 插入一筆評分相關資料進 ratings 資料表 
def create_rating(
    rater_id: int,
    ratee_id: int, 
    score: int, 
    order_id: int, 
    comment: Optional[str] = None  
) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            # 1.檢查訂單是否存在且為「已出貨」狀態 2.檢查評分者與被評分者是否為同一人 3.檢查被評分者是否為此筆訂單的賣家
            cursor.execute("""
                SELECT id, shipment_status, buyer_id, seller_id, ticket_id
                FROM orders
                WHERE id = %s AND buyer_id = %s
            """, (order_id, rater_id))
            order = cursor.fetchone()
            if not order:
                raise HTTPException(status_code=404, detail="訂單不存在或您無權評分")
            if order["shipment_status"] != "已出貨":
                raise HTTPException(status_code=400, detail="訂單尚未出貨，無法評分")
            if order["seller_id"] == rater_id:
                raise HTTPException(status_code=400, detail="不能對自己評分")
            if ratee_id != order["seller_id"]:
                raise HTTPException(status_code=400, detail="被評分者與賣家不符")

            # 檢查此筆訂單是否過去已被評分過
            cursor.execute("""
                SELECT id FROM ratings WHERE order_id = %s AND rater_id = %s
            """, (order_id, rater_id))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="此訂單已評分")

            # 插入評分相關資料
            query = """
                INSERT INTO ratings (rater_id, ratee_id, score, comment, order_id, ticket_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (
                rater_id,
                order["seller_id"],
                score,
                comment or "",
                order_id,
                order["ticket_id"],  # 使用 orders 表的 ticket_id
            ))
        conn.commit()
    return {"status": "success"}     # 回傳值: 評分狀態為 success
    
    
# ================================================