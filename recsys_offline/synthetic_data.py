# recsys_offline/synthetic_data.py
# 合成資料產生器：產出與「快照契約」相同格式的測試資料 (固定 seed → 可重現)
# 用途：(1) 真實資料稀疏時，讓離線評估有足夠 per-user 訊號 (2) 當作評估管線本身的測試 fixture

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


# =======================================
# 常數設定 (TEAMS / STADIUMS 請對齊你 games 表的實際值)
TEAMS = ["中信兄弟", "統一7-ELEVEn獅", "樂天桃猿", "富邦悍將", "味全龍", "台鋼雄鷹"]
STADIUMS = ["大巨蛋", "樂天桃園", "臺南", "天母", "新莊", "洲際", "嘉義市", "花蓮", "斗六", "台東"]

SEED = 42            # 固定亂數種子 → 可重現
N_USERS = 200        # 合成會員數
N_GAMES = 300        # 合成賽事數
P_FAVORITE = 0.7     # 行為事件「命中喜愛球隊」的機率 (製造 per-user 訊號)
OUTPUT_DIR = Path(__file__).parent / "data" / "snapshot"
# =======================================


# 在 [start, end] 之間隨機回傳一個 datetime (含時分)
def _rand_dt(start: date, end: date, rng: random.Random) -> datetime:
    d = start + timedelta(days=rng.randint(0, (end - start).days))
    return datetime(d.year, d.month, d.day, rng.randint(9, 21), rng.randint(0, 59))


# =======================================
# 產生並寫出三份快照檔 + meta
def generate_snapshot(reference_date: date = None) -> None:
    rng = random.Random(SEED)                       # 用獨立的 Random 物件帶 seed，不污染全域亂數
    reference_date = reference_date or date.today()
    past_start = reference_date - timedelta(days=90)
    future_end = reference_date + timedelta(days=60)

    # --- 1. games：過去 90 天 ~ 未來 60 天的賽事 ---
    games = []
    for gid in range(1, N_GAMES + 1):
        home, away = rng.sample(TEAMS, 2)           # sample 確保主客隊不同隊
        gdate = past_start + timedelta(days=rng.randint(0, (future_end - past_start).days))
        games.append({
            "game_id": gid,
            "game_date": gdate.isoformat(),
            "start_time": f"{rng.choice([14, 17, 18])}:05:00",
            "team_home": home,
            "team_away": away,
            "stadium": rng.choice(STADIUMS),
        })
    # 只有「已發生」的賽事才可能產生行為事件
    past_games = [g for g in games if date.fromisoformat(g["game_date"]) <= reference_date]

    # --- 2. member_favorites：每位會員 1~2 個喜愛球隊 (與 prod 一致，存成 JSON 字串) ---
    favorites, member_rows = {}, []
    for uid in range(1, N_USERS + 1):
        fav = rng.sample(TEAMS, rng.choice([1, 1, 2]))   # 多數人 1 隊、少數 2 隊
        favorites[uid] = fav
        member_rows.append({"member_id": uid, "favorite_teams": json.dumps(fav, ensure_ascii=False)})

    # --- 3. behavior_events：交易 + 預約，偏向喜愛球隊以製造 per-user 訊號 ---
    events = []
    for uid in range(1, N_USERS + 1):
        fav = favorites[uid]
        # 刻意製造稀疏性：部分會員 0 筆 (冷啟動 / coverage 測試)
        for _ in range(rng.choice([0, 0, 1, 2, 3, 5, 8])):
            if rng.random() < P_FAVORITE:
                # 從「含喜愛球隊」的過去賽事中挑一場
                pool = [g for g in past_games
                        if any(f in (g["team_home"], g["team_away"]) for f in fav)]
                game = rng.choice(pool) if pool else rng.choice(past_games)
            else:
                game = rng.choice(past_games)        # 30% 機率隨機 (雜訊)
            events.append({
                "member_id": uid,
                "event_type": rng.choice(["trade", "reservation"]),
                "game_id": game["game_id"],
                "team_home": game["team_home"],
                "team_away": game["team_away"],
                "created_at": _rand_dt(past_start, reference_date, rng).isoformat(sep=" "),
            })

    # --- 寫出快照 (parquet) + meta ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(games).to_parquet(OUTPUT_DIR / "games.parquet", index=False)
    pd.DataFrame(member_rows).to_parquet(OUTPUT_DIR / "member_favorites.parquet", index=False)
    pd.DataFrame(events).to_parquet(OUTPUT_DIR / "behavior_events.parquet", index=False)

    meta = {
        "source": "synthetic", "seed": SEED,
        "reference_date": reference_date.isoformat(),
        "n_users": N_USERS, "n_games": N_GAMES, "n_events": len(events),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (OUTPUT_DIR / "snapshot_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 合成快照：會員 {N_USERS}、賽事 {N_GAMES}、事件 {len(events)}、ref={reference_date}")
# =======================================


if __name__ == "__main__":
    generate_snapshot()