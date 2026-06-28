# check_personalization.py (Step 1 開發時的歷史產物)
# Step 2 驗證：用合成快照確認 per-user 個人化生效 (Step 2 已故意改變邏輯，不再比對新舊)。
from datetime import date
from recsys_offline.snapshot_loader import load_snapshot
from services.recommender import recommend, build_team_scores

snap = load_snapshot()
today = date.fromisoformat(snap.meta["reference_date"])
ev = snap.events

# 候選未來賽事 + 全站人氣 (popularity prior)
trade_count = ev[ev["event_type"] == "trade"]["game_id"].value_counts().to_dict()
future = snap.games[snap.games["game_date"] > today]
games = [{"game_id": r.game_id, "game_date": r.game_date, "start_time": r.start_time,
          "team_home": r.team_home, "team_away": r.team_away, "stadium": r.stadium,
          "ticket_count": 0, "trade_count": int(trade_count.get(r.game_id, 0))}
         for r in future.itertuples()]
hot_games = sorted(games, key=lambda g: g["trade_count"], reverse=True)[:15]

def own_behavior(uid):
    e = ev[ev["member_id"] == uid]
    tr = e[e["event_type"] == "trade"][["team_home", "team_away", "created_at"]].to_dict("records")
    rs = e[e["event_type"] == "reservation"][["team_home", "team_away", "created_at"]].to_dict("records")
    return tr, rs

# 挑兩位有行為的會員，觀察結果是否「個人化且互不相同」
sample = [u for u in snap.favorites if len(ev[ev["member_id"] == u]) >= 3][:2]
for uid in sample:
    tr, rs = own_behavior(uid)
    ts = build_team_scores(snap.favorites[uid], tr, rs, today)
    top = recommend(snap.favorites[uid], tr, rs, games, hot_games, today)
    print(f"會員{uid} 喜愛 {snap.favorites[uid]} | 自己交易 {len(tr)} / 預約 {len(rs)} 筆")
    print("  隊伍得分(前5):", {k: round(v, 2) for k, v in sorted(ts.items(), key=lambda x: -x[1])[:5]})
    print("  推薦Top5分數:", [g["recommendation_score"] for g in top])
    print()
print("✅ 應看到：分數為個位數(非~343)、高分隊=自己喜愛/互動過、兩位會員結果不同 → per-user 生效")