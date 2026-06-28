# recsys_offline/evaluate.py
# Step 3 離線評估：時間切分 (temporal holdout)，量化「個人化 vs 純人氣」的 precision@K / hit-rate@K。
# 跑法：專案根目錄 python3 -m recsys_offline.evaluate (需先有合成快照)

from datetime import date, timedelta
from recsys_offline.snapshot_loader import load_snapshot
from services.recommender import recommend, RecommenderParams, DEFAULT_PARAMS

# 兩臂：實驗組(個人化)=預設；對照組(純人氣)=個人訊號權重全設 0
PERSONALIZED    = DEFAULT_PARAMS
POPULARITY_ONLY = RecommenderParams(favorite_base=0, trade_weight=0, reservation_weight=0)

# 可調參數 (這四個就是上面的 ⭐ 決策)
K = 5
TEST_WINDOW_DAYS = 30      # 測試窗口長度：最後幾天當「未來」
MIN_TRAIN_EVENTS = 2       # cohort 門檻：切分點前至少幾筆行為


# 把事件 DataFrame 轉成 recommend() 要的格式
def _records(df):
    return df[["team_home", "team_away", "created_at"]].to_dict("records")


def evaluate():
    snap = load_snapshot()
    if len(snap.events) == 0:
        print("⚠️ 快照沒有任何行為事件，無法評估。請先跑 python3 -m recsys_offline.synthetic_data")
        return

    ref = date.fromisoformat(snap.meta["reference_date"])
    T = ref - timedelta(days=TEST_WINDOW_DAYS)         # 切分點

    ev = snap.events.copy()
    ev["d"] = ev["created_at"].dt.date
    train = ev[ev["d"] < T]                            # T 之前：建檔
    test  = ev[ev["d"] >= T]                           # T 之後：當 ground truth

    # 候選未來賽事 (game_date > T) + as-of-T 人氣 (只用 train 的交易，避免未來洩漏)
    trade_count = train[train["event_type"] == "trade"]["game_id"].value_counts().to_dict()
    future = snap.games[snap.games["game_date"] > T]
    candidate_games = [{"game_id": r.game_id, "game_date": r.game_date, "start_time": r.start_time,
                        "team_home": r.team_home, "team_away": r.team_away, "stadium": r.stadium,
                        "ticket_count": 0, "trade_count": int(trade_count.get(r.game_id, 0))}
                       for r in future.itertuples()]
    hot_games = sorted(candidate_games, key=lambda g: g["trade_count"], reverse=True)[:15]

    # cohort：T 前 ≥ MIN_TRAIN_EVENTS 筆，且 T 後至少有 1 筆 (才有東西可預測)
    train_counts = train.groupby("member_id").size()
    test_members = set(test["member_id"].unique())
    cohort = [m for m in snap.favorites
              if train_counts.get(m, 0) >= MIN_TRAIN_EVENTS and m in test_members]

    # 對單一使用者、單一參數設定，算 precision@K 與是否命中
    def eval_user(uid, params):
        ut = train[train["member_id"] == uid]
        tr = _records(ut[ut["event_type"] == "trade"])
        rs = _records(ut[ut["event_type"] == "reservation"])
        recs = recommend(snap.favorites[uid], tr, rs, candidate_games, hot_games, T, params)

        ut_test = test[test["member_id"] == uid]
        gt = set(ut_test["team_home"]) | set(ut_test["team_away"])   # 標準答案：他 T 後實際碰的球隊
        if not recs:
            return 0.0, 0
        hits = sum(1 for g in recs if g["team_home"] in gt or g["team_away"] in gt)
        return hits / len(recs), (1 if hits > 0 else 0)

    print(f"切分點 T={T} | 測試窗口 {TEST_WINDOW_DAYS} 天 | cohort {len(cohort)} 人 / 全體 {len(snap.favorites)} 人")
    res = {}
    for name, params in [("純人氣", POPULARITY_ONLY), ("個人化", PERSONALIZED)]:
        scores = [eval_user(u, params) for u in cohort]
        prec = sum(p for p, _ in scores) / len(cohort)
        hr   = sum(h for _, h in scores) / len(cohort)
        res[name] = prec
        print(f"  {name:6s}  precision@{K}={prec:.3f}  hit-rate@{K}={hr:.3f}")
    if res["純人氣"] > 0:
        print(f"  → 個人化較純人氣 precision 提升 {(res['個人化'] - res['純人氣']) / res['純人氣'] * 100:.1f}%")


if __name__ == "__main__":
    evaluate()