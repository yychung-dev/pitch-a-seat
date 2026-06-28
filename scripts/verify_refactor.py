# verify_refactor.py (Step 1 開發時的歷史產物)
# 回歸驗證：證明「抽離後的 recommend()」與「原本內嵌邏輯」對相同輸入產出相同 top5。
# 用 Step 0 的合成快照當輸入（真實 DB 90 天內無行為，無法測到計分路徑）。

import math
from datetime import date
from recsys_offline.snapshot_loader import load_snapshot
from services.recommender import recommend


# ---- 區塊 A：原本內嵌邏輯的「忠實複製」(照 routes/games.py 改寫前原樣搬來) ----
# 目的：留一份「改之前的標準答案」當比對基準。
def old_recommend(favorite_teams, trades, reservations, games, hot_games, today):
    team_scores = {team: 2.0 for team in favorite_teams}
    trade_contributions = []
    for trade in trades:
        days_diff = (today - trade["created_at"].date()).days
        weight = 1.2 * math.exp(-0.01 * days_diff)
        trade_contributions.append(weight)
        for team in [trade["team_home"], trade["team_away"]]:
            team_scores[team] = team_scores.get(team, 0) + weight
    if trade_contributions:
        mean_trade = sum(trade_contributions) / len(trade_contributions)
        for team in team_scores:
            if team not in favorite_teams:
                team_scores[team] = max(0, team_scores[team] - mean_trade)
    reservation_contributions = []
    for res in reservations:
        days_diff = (today - res["created_at"].date()).days
        weight = 1.0 * math.exp(-0.01 * days_diff)
        reservation_contributions.append(weight)
        for team in [res["team_home"], res["team_away"]]:
            team_scores[team] = team_scores.get(team, 0) + weight
    if reservation_contributions:
        mean_res = sum(reservation_contributions) / len(reservation_contributions)
        for team in team_scores:
            if team not in favorite_teams:
                team_scores[team] = max(0, team_scores[team] - mean_res)
    recommended_games = []
    for game in games:
        score = team_scores.get(game["team_home"], 0) + team_scores.get(game["team_away"], 0)
        score += 0.1 * game["trade_count"]
        fm = any(t in [game["team_home"], game["team_away"]] for t in favorite_teams)
        recommended_games.append({
            "game_id": game["game_id"], "game_date": game["game_date"].strftime("%Y-%m-%d"),
            "start_time": str(game["start_time"])[:5], "team_home": game["team_home"],
            "team_away": game["team_away"], "stadium": game["stadium"],
            "ticket_count": game["ticket_count"], "recommendation_score": round(score, 2),
            "trade_count": game["trade_count"], "favorite_team_match": fm})
    recommended_games = [g for g in recommended_games if g["recommendation_score"] > 0]
    recommended_games.sort(key=lambda x: x["recommendation_score"], reverse=True)
    top_games = recommended_games[:5]
    if len(top_games) < 5:
        existing_ids = {g["game_id"] for g in top_games}
        for game in hot_games:
            if len(top_games) >= 5:
                break
            if game["game_id"] not in existing_ids:
                fm = any(t in [game["team_home"], game["team_away"]] for t in favorite_teams)
                top_games.append({
                    "game_id": game["game_id"], "game_date": game["game_date"].strftime("%Y-%m-%d"),
                    "start_time": str(game["start_time"])[:5], "team_home": game["team_home"],
                    "team_away": game["team_away"], "stadium": game["stadium"],
                    "ticket_count": game["ticket_count"], "recommendation_score": 0.0,
                    "trade_count": game["trade_count"], "favorite_team_match": fm})
                existing_ids.add(game["game_id"])
    return top_games[:5]


# ---- 區塊 B：從合成快照組裝「與目前線上邏輯相同」的輸入 ----
# 注意：目前線上邏輯用的是「全站」交易/預約，所以這裡也餵全站 (Step 2 才改 per-user)。
snap = load_snapshot()
today = date.fromisoformat(snap.meta["reference_date"])   # 用快照鎖定的「今天」
ev = snap.events

trades = ev[ev["event_type"] == "trade"][["team_home", "team_away", "created_at"]].to_dict("records")
reservations = ev[ev["event_type"] == "reservation"][["team_home", "team_away", "created_at"]].to_dict("records")

# 候選賽事 = 未來賽事；trade_count = 該場的交易事件數 (只是為了讓新舊拿到相同輸入)
trade_count_by_game = ev[ev["event_type"] == "trade"]["game_id"].value_counts().to_dict()
future = snap.games[snap.games["game_date"] > today]

def build_games(df):
    out = []
    for r in df.itertuples():
        out.append({"game_id": r.game_id, "game_date": r.game_date, "start_time": r.start_time,
                    "team_home": r.team_home, "team_away": r.team_away, "stadium": r.stadium,
                    "ticket_count": 0, "trade_count": int(trade_count_by_game.get(r.game_id, 0))})
    return out

candidate_games = build_games(future)
hot_games = sorted(build_games(future), key=lambda g: g["trade_count"], reverse=True)[:15]


# ---- 區塊 C：逐位會員比對「舊邏輯」vs「新邏輯」的 top5 ----
mismatch = 0
checked = 0
for uid, fav in list(snap.favorites.items())[:50]:
    old = old_recommend(fav, trades, reservations, candidate_games, hot_games, today)
    new = recommend(fav, trades, reservations, candidate_games, hot_games, today)
    checked += 1
    if old != new:
        mismatch += 1
        print(f"❌ 會員{uid} 不一致 | old={[g['game_id'] for g in old]} new={[g['game_id'] for g in new]}")

print(f"\n比對 {checked} 位會員：一致 {checked - mismatch} 位、不一致 {mismatch} 位")
print("✅ 重構忠實，新舊輸出完全相同" if mismatch == 0 else "⚠️ 有差異，需檢查")