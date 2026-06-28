# tests/test_recommender.py
# services/recommender.py 純函式的單元測試（不碰 DB / FastAPI / 系統時間）。
# 把推薦的關鍵設計決策編碼成可驗證的行為，讓 CI 真正守得住推薦邏輯。

from datetime import date, datetime, timedelta

import pytest

from services.recommender import (
    RecommenderParams, DEFAULT_PARAMS, PERSONALIZED, POPULARITY_ONLY,
    INTERNAL_MEMBER_IDS, assign_variant,
    build_team_scores, rank_candidate_games, apply_cold_start, recommend,
)

TODAY = date(2026, 6, 28)


def make_game(game_id, home, away, trade_count=0):
    return {
        "game_id": game_id, "game_date": date(2026, 7, 1), "start_time": "18:30:00",
        "team_home": home, "team_away": away, "stadium": "測試球場",
        "ticket_count": 10, "trade_count": trade_count,
    }


def make_behavior(home, away, days_ago=0):
    return {"team_home": home, "team_away": away,
            "created_at": datetime(2026, 6, 28) - timedelta(days=days_ago)}


# ── assign_variant：分流的一致性與內部帳號 override ──
class TestAssignVariant:
    def test_internal_accounts_pinned_to_personalized(self):
        for mid in INTERNAL_MEMBER_IDS:
            assert assign_variant(mid) == "personalized"

    def test_deterministic_same_member_same_arm(self):
        for mid in [2, 7, 33, 128, 999]:
            assert assign_variant(mid) == assign_variant(mid)

    def test_only_two_valid_arms(self):
        arms = {assign_variant(mid) for mid in range(2, 300)}
        assert arms <= {"personalized", "popularity"}

    def test_roughly_balanced_split(self):
        arms = [assign_variant(mid) for mid in range(100, 500)]
        ratio = arms.count("personalized") / len(arms)
        assert 0.3 < ratio < 0.7


# ── build_team_scores：喜愛基礎分 + 行為衰減（per-user，無正規化）──
class TestBuildTeamScores:
    def test_favorite_base_score(self):
        assert build_team_scores(["兄弟"], [], [], TODAY)["兄弟"] == DEFAULT_PARAMS.favorite_base

    def test_behavior_boosts_above_base(self):
        base = build_team_scores(["兄弟"], [], [], TODAY)["兄弟"]
        boosted = build_team_scores(["兄弟"], [make_behavior("兄弟", "猿")], [], TODAY)["兄弟"]
        assert boosted > base

    def test_decay_recent_worth_more_than_old(self):
        recent = build_team_scores([], [make_behavior("兄弟", "猿", days_ago=0)], [], TODAY)["兄弟"]
        old = build_team_scores([], [make_behavior("兄弟", "猿", days_ago=300)], [], TODAY)["兄弟"]
        assert recent > old

    def test_scores_stay_bounded_not_blown_up(self):
        # Step 2 修正：per-user 多筆行為加總仍在合理範圍（不會爆到數百）
        behaviors = [make_behavior("兄弟", "猿", days_ago=i) for i in range(10)]
        assert build_team_scores(["兄弟"], behaviors, [], TODAY)["兄弟"] < 50

    def test_popularity_only_arm_zeros_team_scores(self):
        scores = build_team_scores(["兄弟"], [make_behavior("兄弟", "猿")], [], TODAY, POPULARITY_ONLY)
        assert all(v == 0 for v in scores.values())


# ── rank_candidate_games：打分 → 過濾 0 分 → 排序 → top_k ──
class TestRankCandidateGames:
    def test_filters_zero_score_games(self):
        ranked = rank_candidate_games({"兄弟": 2.0},
                                      [make_game(1, "兄弟", "猿"), make_game(2, "獅", "龍")], ["兄弟"])
        ids = [g["game_id"] for g in ranked]
        assert 1 in ids and 2 not in ids

    def test_sorted_descending(self):
        ranked = rank_candidate_games({"兄弟": 2.0, "猿": 5.0},
                                      [make_game(1, "兄弟", "獅"), make_game(2, "猿", "龍")], ["兄弟", "猿"])
        assert ranked[0]["game_id"] == 2

    def test_popularity_weight_contributes(self):
        ranked = rank_candidate_games({}, [make_game(1, "獅", "龍", trade_count=100)], [])
        assert len(ranked) == 1
        assert ranked[0]["recommendation_score"] == pytest.approx(10.0)

    def test_respects_top_k(self):
        games = [make_game(i, "兄弟", "猿") for i in range(10)]
        ranked = rank_candidate_games({"兄弟": 2.0}, games, ["兄弟"], RecommenderParams(top_k=3))
        assert len(ranked) == 3

    def test_favorite_team_match_flag(self):
        ranked = rank_candidate_games({"兄弟": 2.0}, [make_game(1, "兄弟", "猿")], ["兄弟"])
        assert ranked[0]["favorite_team_match"] is True


# ── apply_cold_start：補滿 top_k、去重、補位分數 0 ──
class TestColdStart:
    def test_fills_up_to_top_k(self):
        filled = apply_cold_start([], [make_game(i, "獅", "龍") for i in range(10)], [], DEFAULT_PARAMS)
        assert len(filled) == DEFAULT_PARAMS.top_k

    def test_no_duplicate_game_ids(self):
        filled = apply_cold_start([{"game_id": 1}],
                                  [make_game(1, "獅", "龍"), make_game(2, "兄弟", "猿")], [], DEFAULT_PARAMS)
        ids = [g["game_id"] for g in filled]
        assert ids.count(1) == 1 and 2 in ids

    def test_cold_start_score_is_zero(self):
        filled = apply_cold_start([], [make_game(1, "獅", "龍")], [], DEFAULT_PARAMS)
        assert filled[0]["recommendation_score"] == 0.0

    def test_no_fill_when_already_full(self):
        top = [{"game_id": i} for i in range(DEFAULT_PARAMS.top_k)]
        filled = apply_cold_start(top, [make_game(99, "獅", "龍")], [], DEFAULT_PARAMS)
        assert len(filled) == DEFAULT_PARAMS.top_k and 99 not in [g["game_id"] for g in filled]


# ── recommend：純入口端到端（兩臂行為）──
class TestRecommendEndToEnd:
    def test_personalized_prioritizes_favorite_game(self):
        games = [make_game(1, "兄弟", "猿"), make_game(2, "獅", "龍")]
        recs = recommend(["兄弟"], [], [], games, [], TODAY, PERSONALIZED)
        assert recs[0]["game_id"] == 1

    def test_popularity_arm_falls_back_to_cold_start(self):
        games = [make_game(1, "兄弟", "猿")]  # 純人氣臂下分數 0
        hot = [make_game(5, "獅", "龍"), make_game(6, "象", "鯨")]
        recs = recommend(["兄弟"], [], [], games, hot, TODAY, POPULARITY_ONLY)
        assert len(recs) >= 1
        assert all(r["recommendation_score"] == 0.0 for r in recs)

    def test_respects_top_k_overall(self):
        games = [make_game(i, "兄弟", "猿") for i in range(10)]
        recs = recommend(["兄弟"], [], [], games, [], TODAY, DEFAULT_PARAMS)
        assert len(recs) <= DEFAULT_PARAMS.top_k

    def test_personalized_differs_from_popularity(self):
        games = [make_game(1, "兄弟", "猿", trade_count=0), make_game(2, "獅", "龍", trade_count=3)]
        hot = [make_game(2, "獅", "龍", trade_count=3)]
        p = recommend(["兄弟"], [], [], games, hot, TODAY, PERSONALIZED)
        pop = recommend(["兄弟"], [], [], games, hot, TODAY, POPULARITY_ONLY)
        assert p[0]["game_id"] == 1      # 個人化：喜愛隊排第一
        assert pop[0]["game_id"] != 1    # 純人氣：喜愛但無人氣 → 被濾掉