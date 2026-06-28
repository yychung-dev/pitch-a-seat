-- 推薦事件表：記錄曝光(impression)與點擊(click)，供 CTR / A-B 分析
-- 部署時在正式 DB 執行一次：mysql -h <host> -u <user> -p <db> < schema/recommendation_events.sql

CREATE TABLE IF NOT EXISTS recommendation_events (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id    CHAR(36) NOT NULL,                          -- 一次推薦的唯一 id (UUID)，綁定曝光與點擊
    member_id     INT NOT NULL,
    game_id       INT NOT NULL,
    rank_pos      TINYINT NOT NULL,                           -- 在推薦清單的名次 1~5 (rank 是 MySQL 保留字，所以用 rank_pos)
    variant       VARCHAR(32) NOT NULL DEFAULT 'personalized',-- A/B 臂別 
    event_type    ENUM('impression','click') NOT NULL,
    recommendation_score FLOAT NULL,                          -- 曝光當下的分數 (分析用，可為 NULL)
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_request (request_id),
    INDEX idx_member_time (member_id, created_at),
    INDEX idx_type_variant (event_type, variant)
);
