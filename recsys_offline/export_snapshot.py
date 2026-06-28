# recsys_offline/export_snapshot.py
# 從 prod (唯讀) 匯出「去識別化」快照，格式與 synthetic_data.py 完全一致。
# 去識別化：真實會員 id → 代理序號；只取必要欄位 (不取姓名/email/電話)；對照表不落地。
# 執行：在專案根目錄跑 `python3 -m recsys_offline.export_snapshot`
# 建議：用唯讀權限的 DB 帳號執行本腳本。

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict

import pandas as pd

from config.database import get_connection   # 重用既有連線池 (DRY)

OUTPUT_DIR = Path(__file__).parent / "data" / "snapshot"

# 事件表的固定欄位：確保即使查詢回傳 0 筆，空表也帶正確 schema (避免 KeyError)
EVENT_COLS = ["member_id", "event_type", "game_id", "team_home", "team_away", "created_at"]


# 執行查詢並回傳 DataFrame
def _fetch_df(query: str, params: tuple = ()) -> pd.DataFrame:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
    return pd.DataFrame(rows)


# 把單一來源 (交易或預約) 整理成統一格式；空結果也保證欄位齊全
def _tag(df: pd.DataFrame, event_type: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=EVENT_COLS)       # 空表 → 回傳「有欄位、無資料」的空表
    df = df.copy()
    df["event_type"] = event_type
    for col in EVENT_COLS:                            # 補齊任何缺少的欄位
        if col not in df.columns:
            df[col] = pd.NA
    return df[EVENT_COLS]                             # 統一欄位與順序


# favorite_teams 統一成 JSON 字串：處理 str / list / 空(None/NaN/空字串)
def _normalize_fav(v) -> str:
    if isinstance(v, str) and v.strip():
        return v                                      # 已是 JSON 字串 → 原樣保留
    if isinstance(v, list):
        return json.dumps(v, ensure_ascii=False)      # 連線器回傳 list → 轉 JSON 字串
    return "[]"                                       # None / NaN / 空 → 空陣列


# =======================================
def export_snapshot(reference_date: date = None) -> None:
    reference_date = reference_date or date.today()
    past_start = reference_date - timedelta(days=90)

    # --- 1. 交易事件 (已出貨訂單)：帶出 buyer_id 作為 member_id ---
    trades = _fetch_df("""
        SELECT o.buyer_id AS member_id, g.id AS game_id,
               g.team_home, g.team_away, o.created_at
        FROM orders o
        JOIN tickets_for_sale t ON o.ticket_id = t.id
        JOIN games g ON t.game_id = g.id
        WHERE o.shipment_status = '已出貨'
            AND o.created_at >= %s
    """, (past_start,))

    # --- 2. 預約事件：帶出 member_id ---
    reservations = _fetch_df("""
        SELECT r.member_id, r.game_id, g.team_home, g.team_away, r.created_at
        FROM reservations r
        JOIN games g ON r.game_id = g.id
        WHERE r.created_at >= %s
    """, (past_start,))

    # 合併兩種事件 (透過 _tag 保證即使空結果也有正確 schema)
    events = pd.concat([_tag(trades, "trade"), _tag(reservations, "reservation")],
                       ignore_index=True)

    # --- 3. games：靜態屬性 (人氣留到評估時以 T 為界動態算，避免未來洩漏) ---
    games = _fetch_df("""
        SELECT id AS game_id, game_date, start_time, team_home, team_away, stadium
        FROM games
    """)

    # --- 4. member_favorites ---
    favorites = _fetch_df("SELECT id AS member_id, favorite_teams FROM members")

    # --- 防呆提示：資料為空時講清楚原因 ---
    if favorites.empty:
        raise SystemExit("⚠️ members 表查無資料，請確認 .env 連到的是正確且有資料的資料庫。")
    if events.empty:
        print("⚠️ 過去 90 天內沒有任何『已出貨交易』或『預約』 → 將輸出「只有會員與賽事、無行為事件」的快照。")
        print("   （資料都在 90 天以前很正常；可改傳較早的 reference_date，或先用合成快照開發步驟 1~5。）")

    # --- 去識別化：真實 member_id → 代理序號 (對照表只在記憶體，不落地) ---
    real_ids = pd.unique(pd.concat(
        [events["member_id"], favorites["member_id"]], ignore_index=True).dropna())
    id_map: Dict[int, int] = {int(rid): i + 1 for i, rid in enumerate(sorted(real_ids))}
    events["member_id"] = events["member_id"].map(id_map)
    favorites["member_id"] = favorites["member_id"].map(id_map)

    # favorite_teams 統一成 JSON 字串
    favorites["favorite_teams"] = favorites["favorite_teams"].apply(_normalize_fav)

    # 時間欄統一成字串輸出 (與合成快照一致；loader 會再轉回 datetime)
    events["created_at"] = pd.to_datetime(events["created_at"]).astype(str)
    games["game_date"] = pd.to_datetime(games["game_date"]).dt.date.astype(str)
    games["start_time"] = games["start_time"].astype(str)

    events = events[EVENT_COLS]   # 對齊契約順序 (已是此順序，保險用)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    events.to_parquet(OUTPUT_DIR / "behavior_events.parquet", index=False)
    games.to_parquet(OUTPUT_DIR / "games.parquet", index=False)
    favorites.to_parquet(OUTPUT_DIR / "member_favorites.parquet", index=False)

    meta = {
        "source": "real_deidentified",
        "reference_date": reference_date.isoformat(),
        "n_users": len(id_map), "n_games": int(len(games)), "n_events": int(len(events)),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    (OUTPUT_DIR / "snapshot_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 去識別化快照：會員 {len(id_map)}、賽事 {len(games)}、事件 {len(events)}")
# =======================================


if __name__ == "__main__":
    export_snapshot()


# 若之後想要一份「真實 coverage 數字」當佐證,就傳一個落在最後活動後 90 天內的 reference_date,讓窗口涵蓋到那批四個月前的資料。
# 作法: 把 export_snapshot 的括號內容改成某日期(日期依實際活動時間微調). 舉例如下:
# if __name__ == "__main__":
#     from datetime import date
#     export_snapshot(reference_date=date(2026, 5, 1))   # 窗口會回看到約 2026-01-31，涵蓋舊資料