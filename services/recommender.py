# services/recommender.py
# 推薦評分的「純邏輯」層：不碰 DB、不碰 FastAPI、不讀系統時間 (today 由外部傳入)。
# 路由層與離線評估共用同一份計分邏輯，避免「線上服務」與「被評估」的程式碼漂移。

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List
import hashlib   # 檔案頂部

# =======================================
# 推薦參數：把原本散落的魔法數字集中管理 (可調、可比較、可做 A/B 兩臂)
@dataclass(frozen=True)
class RecommenderParams:
    favorite_base: float = 2.0       # 喜愛球隊基礎分
    trade_weight: float = 1.2        # 交易行為的基礎權重
    reservation_weight: float = 1.0  # 預約行為的基礎權重
    decay_rate: float = 0.01         # 時間衰減率 (越大，舊行為衰減越快)
    popularity_weight: float = 0.1   # 人氣 (trade_count) 的加權係數
    top_k: int = 5                   # 回傳前幾名

DEFAULT_PARAMS = RecommenderParams()


# =======================================
# A/B 實驗設定 
PERSONALIZED    = DEFAULT_PARAMS
POPULARITY_ONLY = RecommenderParams(favorite_base=0, trade_weight=0, reservation_weight=0)
VARIANTS = {"personalized": PERSONALIZED, "popularity": POPULARITY_ONLY}
EXPERIMENT_NAME = "recsys_personalization_v1"


# 內部/示範帳號：不參與隨機分流（固定走個人化以利展示），且分析時一律排除
INTERNAL_MEMBER_IDS = {1, 4}   # 內部帳號（測試／示範用），不納入 A/B 實驗分析

def assign_variant(member_id: int, experiment: str = EXPERIMENT_NAME) -> str:
    if member_id in INTERNAL_MEMBER_IDS:
        return "personalized"      # demo/內部帳號固定看個人化（最佳呈現）
    h = int(hashlib.md5(f"{experiment}:{member_id}".encode()).hexdigest(), 16)
    return "personalized" if h % 2 == 0 else "popularity"
# =======================================


# 把一種行為 (交易或預約) 的時間衰減權重「累加」到各隊。
# Step 2：移除原本的 per-event-mean 正規化 (對全站近乎無效、對 per-user 稀疏資料有害)。
def _apply_behavior(team_scores: Dict[str, float], behaviors: List[Dict[str, Any]],
                    today: date, base_weight: float, decay_rate: float) -> None:
    for b in behaviors:
        days_diff = (today - b["created_at"].date()).days
        weight = base_weight * math.exp(-decay_rate * days_diff)
        for team in (b["team_home"], b["team_away"]):
            team_scores[team] = team_scores.get(team, 0) + weight


# 個人分：喜愛球隊基礎分 + 自己交易/預約的時間衰減加總 (per-user，無基準扣除)
def build_team_scores(favorite_teams: List[str], trades: List[Dict[str, Any]],
                      reservations: List[Dict[str, Any]], today: date,
                      params: RecommenderParams = DEFAULT_PARAMS) -> Dict[str, float]:
    team_scores = {team: params.favorite_base for team in favorite_teams}
    _apply_behavior(team_scores, trades, today, params.trade_weight, params.decay_rate)
    _apply_behavior(team_scores, reservations, today, params.reservation_weight, params.decay_rate)
    return team_scores


# 把一場賽事組裝成回傳格式 (候選賽事與冷啟動共用，消除重複)
def _to_recommendation(game: Dict[str, Any], score: float,
                       favorite_teams: List[str]) -> Dict[str, Any]:
    return {
        "game_id": game["game_id"],
        "game_date": game["game_date"].strftime("%Y-%m-%d"),
        "start_time": str(game["start_time"])[:5],
        "team_home": game["team_home"],
        "team_away": game["team_away"],
        "stadium": game["stadium"],
        "ticket_count": game["ticket_count"],
        "recommendation_score": round(score, 2),
        "trade_count": game["trade_count"],
        "favorite_team_match": any(
            t in (game["team_home"], game["team_away"]) for t in favorite_teams),
    }


# 用隊伍得分幫候選賽事打分 → 加人氣 → 過濾 0 分 → 排序 → 取 top_k
def rank_candidate_games(team_scores: Dict[str, float], games: List[Dict[str, Any]],
                         favorite_teams: List[str],
                         params: RecommenderParams = DEFAULT_PARAMS) -> List[Dict[str, Any]]:
    scored = []
    for g in games:
        score = team_scores.get(g["team_home"], 0) + team_scores.get(g["team_away"], 0)
        score += params.popularity_weight * g["trade_count"]
        scored.append(_to_recommendation(g, score, favorite_teams))
    scored = [g for g in scored if g["recommendation_score"] > 0]
    scored.sort(key=lambda x: x["recommendation_score"], reverse=True)
    return scored[:params.top_k]


# 冷啟動：不足 top_k 場時，用熱門賽事補滿 (分數設 0)，並去除重複 game_id
def apply_cold_start(top_games: List[Dict[str, Any]], hot_games: List[Dict[str, Any]],
                     favorite_teams: List[str],
                     params: RecommenderParams = DEFAULT_PARAMS) -> List[Dict[str, Any]]:
    if len(top_games) >= params.top_k:
        return top_games
    existing_ids = {g["game_id"] for g in top_games}
    for g in hot_games:
        if len(top_games) >= params.top_k:
            break
        if g["game_id"] not in existing_ids:
            top_games.append(_to_recommendation(g, 0.0, favorite_teams))
            existing_ids.add(g["game_id"])
    return top_games


# 純入口：串接上面三段。路由層與離線評估都呼叫這個。
def recommend(favorite_teams: List[str], trades: List[Dict[str, Any]],
              reservations: List[Dict[str, Any]], candidate_games: List[Dict[str, Any]],
              hot_games: List[Dict[str, Any]], today: date,
              params: RecommenderParams = DEFAULT_PARAMS) -> List[Dict[str, Any]]:
    team_scores = build_team_scores(favorite_teams, trades, reservations, today, params)
    top_games = rank_candidate_games(team_scores, candidate_games, favorite_teams, params)
    top_games = apply_cold_start(top_games, hot_games, favorite_teams, params)
    return top_games[:params.top_k]