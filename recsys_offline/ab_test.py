# recsys_offline/ab_test.py
# Step 5：模擬 A/B（真實流量不足 → 反事實模擬）。對照=純人氣、實驗=個人化，比較 CTR。
# 誠實前提：這是模擬。結果是「使用者更愛點命中其偏好的推薦」這個點擊傾向模型的後果，
#           把 Step 3 量到的相關性優勢轉成 CTR 結論。有真實流量時，改用 ctr_report.py 的真實數據。

import math
import random
from datetime import date
from recsys_offline.snapshot_loader import load_snapshot
from services.recommender import recommend, assign_variant, VARIANTS

# ── 點擊傾向模型（明確假設，可辯護）──
BASE_CTR = 0.03           # 與偏好無關的基線點擊率
RELEVANCE_LIFT = 0.15     # 推薦命中使用者真實偏好時，點擊率增加量
VISITS_PER_USER = 4       # 模擬實驗期間每位使用者平均到訪次數（代表實驗長度/累積流量）
SEED = 7

def _phi(x):              # 標準常態 CDF
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def simulate():
    snap = load_snapshot()
    today = date.fromisoformat(snap.meta["reference_date"])
    ev = snap.events
    rng = random.Random(SEED)

    tc = ev[ev["event_type"] == "trade"]["game_id"].value_counts().to_dict()
    future = snap.games[snap.games["game_date"] > today]
    games = [{"game_id": r.game_id, "game_date": r.game_date, "start_time": r.start_time,
              "team_home": r.team_home, "team_away": r.team_away, "stadium": r.stadium,
              "ticket_count": 0, "trade_count": int(tc.get(r.game_id, 0))}
             for r in future.itertuples()]
    hot = sorted(games, key=lambda g: g["trade_count"], reverse=True)[:15]

    def prefs(uid):  # 使用者真實偏好 = 喜愛球隊 ∪ 互動過的球隊
        e = ev[ev["member_id"] == uid]
        return set(snap.favorites[uid]) | set(e["team_home"]) | set(e["team_away"])
    def own(uid):
        e = ev[ev["member_id"] == uid]
        tr = e[e["event_type"] == "trade"][["team_home", "team_away", "created_at"]].to_dict("records")
        rs = e[e["event_type"] == "reservation"][["team_home", "team_away", "created_at"]].to_dict("records")
        return tr, rs

    counts = {"personalized": [0, 0], "popularity": [0, 0]}   # [曝光, 點擊]
    split = {"personalized": 0, "popularity": 0}
    for uid in snap.favorites:
        v = assign_variant(uid); split[v] += 1
        tr, rs = own(uid)
        recs = recommend(snap.favorites[uid], tr, rs, games, hot, today, VARIANTS[v])
        p = prefs(uid)
        for _ in range(VISITS_PER_USER):                       # 多次到訪累積流量
            for g in recs:
                counts[v][0] += 1
                relevant = (g["team_home"] in p) or (g["team_away"] in p)
                click_p = min(1.0, BASE_CTR + RELEVANCE_LIFT * (1 if relevant else 0))
                if rng.random() < click_p:
                    counts[v][1] += 1

    nA, kA = counts["popularity"]      # 對照
    nB, kB = counts["personalized"]    # 實驗
    ctrA, ctrB = kA / nA, kB / nB
    pooled = (kA + kB) / (nA + nB)
    se = math.sqrt(pooled * (1 - pooled) * (1 / nA + 1 / nB))
    z = (ctrB - ctrA) / se
    pval = 2 * (1 - _phi(abs(z)))
    se_diff = math.sqrt(ctrA * (1 - ctrA) / nA + ctrB * (1 - ctrB) / nB)
    lo, hi = (ctrB - ctrA) - 1.96 * se_diff, (ctrB - ctrA) + 1.96 * se_diff
    need = (1.96 + 0.84) ** 2 * (ctrA * (1 - ctrA) + ctrB * (1 - ctrB)) / (ctrB - ctrA) ** 2

    print(f"假設: 基線CTR={BASE_CTR}、命中偏好加成={RELEVANCE_LIFT}、每人{VISITS_PER_USER}次到訪、seed={SEED}")
    print(f"分流：個人化 {split['personalized']} 人 / 純人氣 {split['popularity']} 人")
    print(f"對照(純人氣) : 曝光 {nA}、點擊 {kA}、CTR={ctrA:.3f}")
    print(f"實驗(個人化) : 曝光 {nB}、點擊 {kB}、CTR={ctrB:.3f}")
    print(f"絕對提升 {ctrB - ctrA:+.3f}（相對 {(ctrB - ctrA) / ctrA * 100:+.1f}%)| 差異95%CI [{lo:+.3f}, {hi:+.3f}]")
    print(f"雙比例 z 檢定: z={z:.2f}、雙尾 p={pval:.2e} → {'顯著' if pval < 0.05 else '不顯著'}(α=0.05)")
    print(f"檢定力：偵測此效應(80% power, α=0.05)需每臂約 {math.ceil(need)} 次曝光")

if __name__ == "__main__":
    simulate()