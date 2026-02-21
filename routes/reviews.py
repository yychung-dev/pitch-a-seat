"""
reviews.py
Seller rating APIs
- POST /api/ratings  - Submit a rating for a seller after order completion
"""


from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from utils.auth_utils import get_current_user
from models.review_model import create_rating




# ================================================
# API 路徑前綴統一為 /api
router = APIRouter(prefix="/api", tags=["reviews"])
# ================================================




# Pydantic Models 
# ================================================

# 賣家評分請求模型: 買家完成交易後，對賣家進行 1-5 星評分
class RatingIn(BaseModel):
    # rater_id: int                      # 評分者（買家）的會員 ID
    ratee_id: int                        # 被評分者（賣家）的會員 ID
    score: int = Field(..., ge=1, le=5)  # 評分（1-5 星）. ge=大於等於, le=小於等於
    order_id: int                        # 評分對應的訂單 ID
    comment: Optional[str] = None        # 評論內容（選填）
# ================================================




# API Routes 
# ================================================

# 新增對賣家的評分 API
@router.post("/ratings")
async def submit_rating_api(
    rating: RatingIn,
    user: Dict[str, Any] = Depends(get_current_user)
):
    # 1.參數使用 get_current_user 函數依賴注入, 取得目前使用者的資訊 (user_id, name, email). 目前使用者是「評分者」
    rater_id = user["user_id"]
    
    # score 驗證已由 Pydantic Field(ge=1, le=5) 處理, 所以移除手動驗證
    # if not 1 <= rating.score <= 5:
    #     raise HTTPException(status_code=400, detail="評分需介於 1~5 顆星")
    
    try:
        # 2.新增評分到資料庫
        result = create_rating(rater_id, rating.ratee_id, rating.score, rating.order_id, rating.comment)
        
        # 3.回傳: 評分狀態為 success
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        print("評分寫入錯誤：", e)
        raise HTTPException(status_code=500, detail="評分寫入失敗")    

# ================================================