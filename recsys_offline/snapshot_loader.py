# recsys_offline/snapshot_loader.py
# 讀取「凍結快照」成結構化資料，供離線評估 / A/B 模擬共用。
# 設計重點：下游只認這個 loader 的輸出，不直接碰檔案 → 來源(真實/合成)可隨時替換。

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd

SNAPSHOT_DIR = Path(__file__).parent / "data" / "snapshot"


# 用 dataclass 把四份資料打包成一個物件，下游拿 snap.events / snap.favorites 即可
@dataclass
class Snapshot:
    events: pd.DataFrame            # member_id, event_type, game_id, team_home, team_away, created_at
    games: pd.DataFrame             # game_id, game_date, start_time, team_home, team_away, stadium
    favorites: Dict[int, List[str]] # {member_id: ["中信兄弟", ...]}
    meta: Dict


def load_snapshot(snapshot_dir: Path = SNAPSHOT_DIR) -> Snapshot:
    events = pd.read_parquet(snapshot_dir / "behavior_events.parquet")
    games = pd.read_parquet(snapshot_dir / "games.parquet")
    fav_df = pd.read_parquet(snapshot_dir / "member_favorites.parquet")
    meta = json.loads((snapshot_dir / "snapshot_meta.json").read_text(encoding="utf-8"))

    # 型別正規化：時間欄轉 datetime / date，後續才好做時間切分
    events["created_at"] = pd.to_datetime(events["created_at"])
    games["game_date"] = pd.to_datetime(games["game_date"]).dt.date

    # favorite_teams 在快照是 JSON 字串 (與 prod members 表一致) → 解析成 list
    favorites = {int(r.member_id): json.loads(r.favorite_teams) for r in fav_df.itertuples()}

    return Snapshot(events=events, games=games, favorites=favorites, meta=meta)


if __name__ == "__main__":
    snap = load_snapshot()
    print("meta:", snap.meta)
    print("events:", snap.events.shape, "| games:", snap.games.shape, "| members:", len(snap.favorites))
    # 驗證 per-user 訊號真的存在：抽行為最多的會員，比對其行為隊伍 vs 喜愛球隊
    uid = snap.events["member_id"].value_counts().index[0]
    ev = snap.events[snap.events["member_id"] == uid]
    teams = pd.concat([ev["team_home"], ev["team_away"]]).value_counts()
    print(f"\n會員{uid} 喜愛球隊: {snap.favorites[uid]}")
    print(f"會員{uid} 行為涉及隊伍次數:\n{teams}")