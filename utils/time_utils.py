"""
time_utils.py
Time Utility Functions

Functions:
- utc_now()  - Get current UTC datetime
"""

from datetime import datetime, timezone

# ================================================
# 函數功能: 取得當下的 UTC 標準日期與時間
# 回傳值: 當下的 UTC 標準日期與時間 (資料型態: datetime 物件)

# 呼叫此函數的呼叫端, 可得到 「當下時間的 UTC 標準時間」的 datetime 物件, eg. 2024-06-06 00:02:55.079759+00:00 (日期、時分秒微秒、時區偏移量)
# datetime.now(timezone.utc) 的主要功能: 獲得包含「時區資訊」的當下 UTC 日期與時間
def utc_now() -> datetime:
    return datetime.now(timezone.utc)
# ================================================