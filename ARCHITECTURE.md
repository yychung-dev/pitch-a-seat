# Architecture Notes

專案架構與設計決策的備忘錄。

---

## API 設計備註

## GET /api/recommendations 推薦演算法

### 演算法概述

基於會員的歷史行為（交易、預約、喜愛球隊）計算每支球隊的偏好分數，再推薦包含這些球隊的比賽。

### Step 1: 初始化球隊分數

```python
favorite_teams = get_member_favorite_teams(user_id)
team_scores = {team: 2.0 for team in favorite_teams}
# 例如：{"中信兄弟": 2.0, "統一獅": 2.0}
```

### Step 2: 計算交易貢獻

```python
for trade in trades:
    # days_diff: 這筆交易距離今天幾天
    days_diff = (today - trade["created_at"].date()).days
    # 例如：今天 2/12，交易日 2/10 → days_diff = 2

    # weight: 指數衰減權重（越近期的交易權重越高）
    weight = 1.2 * math.exp(-0.01 * days_diff)
    # days_diff=0  → weight ≈ 1.2（最高）
    # days_diff=30 → weight ≈ 0.89
    # days_diff=90 → weight ≈ 0.49

    # 為這筆交易涉及的兩支球隊加分
    for team in [trade["team_home"], trade["team_away"]]:
        team_scores[team] = team_scores.get(team, 0) + weight
```

### Step 3: 正規化交易得分

```python
if trade_contributions:
    mean_trade = sum(trade_contributions) / len(trade_contributions)
    for team in team_scores:
        if team not in favorite_teams:
            # 非喜愛球隊：減去平均值，避免所有球隊分數都很高
            team_scores[team] = max(0, team_scores[team] - mean_trade)
```

**為什麼要正規化？**

- 如果使用者有 50 筆交易，所有球隊都會累積很高分數
- 減去平均值後，只有「真正偏好」的球隊才會保持高分
- 喜愛球隊不減分，確保它們始終有優勢

### Step 4: 預約貢獻（同交易邏輯）

```python
weight = 1.0 * math.exp(-0.01 * days_diff)  # 預約權重略低於交易
```

### Step 5: 計算推薦分數

```python
for game in games:
    # 基礎分數：主客隊的球隊分數加總
    score = team_scores.get(game["team_home"], 0) + team_scores.get(game["team_away"], 0)

    # 熱門加權：交易量大的比賽額外加分
    score += 0.1 * game["trade_count"]
```

### Step 6: 冷啟動處理

當推薦不足 5 場時，補充熱門比賽：

```python
if len(top_games) < 5:
    needed = 5 - len(top_games)
    hot_games = get_hot_games_in_period(today, future_60_days, needed + 10)
    # 多撈 10 筆，確保過濾重複後還夠

    existing_ids = {g["game_id"] for g in top_games}
    for game in hot_games:
        if len(top_games) >= 5:
            break
        if game["game_id"] not in existing_ids:
            top_games.append({...})
            existing_ids.add(game["game_id"])
```

### 權重設計圖解

```
                    權重
                      │
                 1.2 ─┼─ ★ 交易（今天）
                      │    ╲
                 1.0 ─┼─    ╲─ ★ 預約（今天）
                      │       ╲
                 0.8 ─┼─        ╲
                      │          ╲
                 0.6 ─┼─           ╲
                      │             ╲
                 0.4 ─┼─              ╲─ ★ 交易（90天前）
                      │
                 0.2 ─┼─
                      │
                    0 ┼───┬───┬───┬───┬───┬───►
                      0  15  30  45  60  75  90  天數
```

### 重點整理

| 問題                     | 回答要點                                           |
| ------------------------ | -------------------------------------------------- |
| 為什麼用指數衰減？       | 近期行為更能代表當前偏好，遠期行為影響應該遞減     |
| 為什麼要正規化？         | 避免發生「高活躍會員的所有球隊都高分」，保持區分度 |
| 喜愛球隊為什麼不正規化？ | 確保明確表態的偏好不會被稀釋                       |
| 冷啟動如何處理？         | 補充熱門比賽，確保新會員也有推薦內容               |
| 為什麼多撈 10 筆？       | 過濾重複後可能不夠，預留緩衝                       |

---

## GET /api/top_games 快取設計

### 設計目標

本月熱門賽事排行榜是**高頻讀取、低頻變動**的資料，適合使用快取。

### 架構流程

```
┌─────────────────────────────────────────────────────────────┐
│ 請求進入                                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 1: 嘗試從 Redis 取得快取                                │
├─────────────────────────────────────────────────────────────┤
│ cache_key = "top_games:2025-07"                             │
│ cached_data = redis_client.get(cache_key)                   │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
       快取命中 (HIT)                   快取未命中 (MISS)
              │                          或 Redis 錯誤
              ▼                               │
┌─────────────────────────┐                   │
│ 直接回傳快取資料         │                   │
│ return json.loads(data) │                   │
└─────────────────────────┘                   │
                                              ▼
                    ┌─────────────────────────────────────────┐
                    │ Step 2: 降級查詢資料庫                   │
                    ├─────────────────────────────────────────┤
                    │ top_games = get_top_games()             │
                    └─────────────────────────────────────────┘
                                              │
                                              ▼
                    ┌─────────────────────────────────────────┐
                    │ Step 3: 寫入 Redis 快取（TTL = 1 天）    │
                    ├─────────────────────────────────────────┤
                    │ redis_client.setex(key, 86400, payload) │
                    │ （寫入失敗不中斷，只記錄 log）            │
                    └─────────────────────────────────────────┘
                                              │
                                              ▼
                    ┌─────────────────────────────────────────┐
                    │ Step 4: 回傳資料庫查詢結果               │
                    └─────────────────────────────────────────┘
```

### 降級策略

| Redis 狀態    | 行為                         |
| ------------- | ---------------------------- |
| 正常 + 有快取 | 直接回傳快取                 |
| 正常 + 無快取 | 查 DB → 存快取 → 回傳        |
| 連線失敗      | 查 DB → 回傳（不存快取）     |
| 寫入失敗      | 查 DB → 回傳（忽略寫入錯誤） |

### 關鍵設計原則

1. **快取是輔助功能**：Redis 壞了不應該影響核心功能
2. **只有 DB 錯誤才中斷**：DB 是必要條件，失敗就回 500
3. **Log 區分問題來源**：記錄 key、bytes、error 方便除錯

### TTL 設計考量

```python
redis_client.setex(cache_key, 86400, payload)  # 86400 秒 = 1 天
```

- **為什麼 1 天？** 排行榜不需要即時更新，1 天內的變化可接受
- **效益**：假設每天 10,000 次請求，只有第 1 次查 DB，其餘 9,999 次從快取取

---

## GET /api/top_games_median_prices SQL 設計

### SQL 結構

```sql
WITH ranked AS (
    -- CTE 1: 計算每場比賽的票價排名（為了算中位數）
),
median_calc AS (
    -- CTE 2: 計算每場比賽的票價中位數
),
top_games AS (
    -- CTE 3: 取銷量前 5 名的場次
)
SELECT ...
FROM top_games tg
LEFT JOIN median_calc mc ON tg.game_id = mc.game_id
```

### 為什麼用 LEFT JOIN？

| 寫法                  | 異常時的行為                               | 可追蹤性       |
| --------------------- | ------------------------------------------ | -------------- |
| INNER JOIN            | 資料直接消失，沒有任何提示                 | ❌ 難發現問題  |
| LEFT JOIN + NULL 檢查 | 資料存在但 median_price = NULL，可記錄 log | ✓ 容易發現問題 |

### 異常處理策略

```python
if row["median_price"] is None:
    # 防禦性處理：理論上不會發生，但如果發生要記錄並跳過
    print(f"[Warning] 場次 {row['game_id']} 中位數為 NULL（不應發生）")
    continue  # 跳過，不回傳錯誤的 0
```

**為什麼不設為 0？**

- 有交易的比賽，票價不可能是 0 元
- 顯示 0 會誤導使用者
- 跳過資料比顯示錯誤資料更好

---

## GET /api/team_trade_rank UNION ALL 設計

### 問題背景

一筆訂單涉及兩支球隊（主隊 vs 客隊），需要分別計算每支球隊的交易次數。

### SQL 結構

```sql
SELECT team, COUNT(*) AS trade_count
FROM (
    -- 子查詢 1: 取出所有訂單的主隊
    SELECT g.team_home AS team
    FROM orders o JOIN ...

    UNION ALL

    -- 子查詢 2: 取出所有訂單的客隊
    SELECT g.team_away AS team
    FROM orders o JOIN ...
) AS teams
GROUP BY team
ORDER BY trade_count DESC
```

### 為什麼用 UNION ALL？

假設有 3 筆訂單：

| 訂單 | 主隊     | 客隊     |
| ---- | -------- | -------- |
| 1    | 中信兄弟 | 統一獅   |
| 2    | 中信兄弟 | 富邦悍將 |
| 3    | 樂天桃猿 | 中信兄弟 |

**子查詢 1（team_home）**：

```
中信兄弟
中信兄弟
樂天桃猿
```

**子查詢 2（team_away）**：

```
統一獅
富邦悍將
中信兄弟
```

**UNION ALL 合併**：

```
中信兄弟
中信兄弟
樂天桃猿
統一獅
富邦悍將
中信兄弟
```

**GROUP BY team 後**：

| 球隊     | trade_count |
| -------- | ----------- |
| 中信兄弟 | 3           |
| 樂天桃猿 | 1           |
| 統一獅   | 1           |
| 富邦悍將 | 1           |

### UNION vs UNION ALL

| 語法      | 行為             |
| --------- | ---------------- |
| UNION     | 去除重複（較慢） |
| UNION ALL | 保留全部（較快） |

這裡必須用 **UNION ALL**，因為我們要計算所有出現次數，不能去重。

---

## TapPay 付款 API 設計

### API 流程圖

```
POST /api/tappay_pay
        │
        ▼
┌─────────────────────────────────────┐
│ 1. 驗證訂單                          │
│    - 訂單是否存在                    │
│    - 是否為買家本人                  │
│    - 訂單狀態是否為「媒合成功」       │
│    - 付款狀態是否為「未付款」         │
└─────────────────────────────────────┘
        │ 驗證失敗 → 回傳 4XX 錯誤
        ▼
┌─────────────────────────────────────┐
│ 2. 建立付款紀錄 (tappay_status=UNPAID)│
│    目的：即使後續失敗，也有紀錄可查   │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 3. 呼叫 TapPay API                   │
│    - 設定 timeout=10s 避免資源耗盡   │
│    - 使用 async httpx 非同步請求     │
└─────────────────────────────────────┘
        │
        ├── API 呼叫失敗（網路/DNS/TapPay 掛掉）
        │   → 更新 tappay_status=FAILED
        │   → 回傳 500
        │
        ▼
┌─────────────────────────────────────┐
│ 4. 處理 TapPay 回傳結果              │
└─────────────────────────────────────┘
        │
        ├── status=0（付款成功）
        │   → 更新 payments 表
        │   → 更新 orders 表（payment_status=已付款）
        │   → 新增通知、寄信給賣家
        │   → 回傳 success
        │
        └── status≠0（付款失敗，如餘額不足）
            → 更新 tappay_status=FAILED
            → 回傳 400（客戶端問題，非系統錯誤）
```

### 錯誤處理策略

| 錯誤類型                      | HTTP 狀態碼 | 原因                      |
| ----------------------------- | ----------- | ------------------------- |
| 訂單不存在                    | 404         | 業務邏輯錯誤              |
| 無權限操作                    | 403         | 業務邏輯錯誤              |
| 訂單狀態不符                  | 400         | 業務邏輯錯誤              |
| TapPay API 呼叫失敗           | 500         | 系統/網路錯誤（不可預期） |
| TapPay 授權失敗（餘額不足等） | 400         | 客戶端問題（可預期）      |
| 資料庫更新失敗                | 500         | 系統錯誤                  |

### 為什麼先建立 UNPAID 付款紀錄？

```python
payment_id = create_payment_unpaid(order_id, amount)
```

**目的**：

1. **可追溯性**：即使 TapPay API 失敗，也有紀錄知道「曾經發起過付款」
2. **問題排查**：可以從 payments 表看到失敗原因（tappay_status_message）
3. **對帳需求**：方便與 TapPay 後台對帳

### 為什麼設定 timeout=10s？

```python
async with httpx.AsyncClient(timeout=10.0) as client:
```

**原因**：

- 若每個請求都卡在外部 API，會佔用連線資源
- 即使有 async，大量卡住的請求仍會拖垮 Server
- 10 秒是合理的金流 API 回應時間上限

### 為什麼使用 async httpx？

```python
async with httpx.AsyncClient() as client:
    resp = await client.post(...)
```

**優點**：

- 非同步請求，不會阻塞其他請求
- 提升併發處理能力
- 適合 I/O 密集型操作（呼叫外部 API）

---

## 賣家出貨 API 設計

### API 流程圖

```
POST /api/mark_shipped
        │
        ▼
┌─────────────────────────────────────┐
│ 1. 原子更新訂單狀態                  │
│    UPDATE ... WHERE 多重條件         │
│    - id = order_id                  │
│    - seller_id = 當前用戶           │
│    - payment_status = '已付款'       │
│    - shipment_status = '未出貨'      │
└─────────────────────────────────────┘
        │
        ├── rowcount=0（更新失敗）
        │   → 查詢訂單，判斷具體原因
        │   → 回傳對應的 4XX 錯誤
        │
        ▼ rowcount=1（更新成功）
┌─────────────────────────────────────┐
│ 2. 查詢訂單資料（用於後續通知）       │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 3. 新增站內通知                      │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 4. 查詢買家 Email（commit 前查詢）   │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 5. Transaction Commit               │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 6. 寄信通知買家（發送到 SQS）        │
│    Commit 成功後才寄，避免寄了卻沒更新│
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 7. 無效化 Redis 快取                 │
│    出貨後排行榜統計會改變            │
└─────────────────────────────────────┘
        │
        ▼
    回傳 success
```

### 原子更新（Atomic Update）設計

**問題**：使用者連擊兩次出貨按鈕

```
請求 1: 檢查狀態=未出貨 → 更新為已出貨 → 寄信
請求 2: 檢查狀態=未出貨 → 更新為已出貨 → 寄信（重複寄信！）
```

**解決方案**：把檢查和更新合併成一個 SQL

```python
cursor.execute("""
    UPDATE orders
    SET shipment_status='已出貨', shipped_at=%s
    WHERE id=%s
      AND seller_id=%s
      AND payment_status='已付款'
      AND shipment_status='未出貨'  -- 關鍵：只更新「未出貨」的訂單
""", (shipped_time, order_id, seller_id))
```

**效果**：

- 請求 1：條件符合，rowcount=1，繼續後續流程
- 請求 2：shipment_status 已經是「已出貨」，條件不符，rowcount=0，不會重複寄信

### Transaction 設計

**為什麼在 Router 層管理 Transaction？**

```python
with get_connection() as conn:
    with conn.cursor() as cursor:
        update_order_shipped_atom(cursor, ...)  # 傳入 cursor
        get_order_by_id(cursor, ...)            # 共用同一個 cursor
        notify_shipped(cursor, ...)             # 共用同一個 cursor
    conn.commit()  # Router 層決定何時 commit
```

**原因**：

- 多個 Model 函數需要在同一個 Transaction 內執行
- 必須共用同一個 cursor，否則會是不同的連線/Transaction
- Router 層統一管理，確保「全部成功才 commit」

### 為什麼 Commit 後才寄信？

```python
conn.commit()  # 先 commit

if notification_data:  # 再寄信
    send_email_async(...)
```

**原因**：

- 如果先寄信後 commit，萬一 commit 失敗，使用者收到「已出貨」通知，但訂單狀態沒更新
- Commit 成功後再寄信，確保「資料庫狀態」和「通知內容」一致

### 為什麼寄信失敗不影響 API 結果？

```python
# 寄信失敗不會 raise，API 仍回傳 success
send_email_async(...)  # 失敗時內部 catch，不影響主流程

return {"status": "success"}  # 一定會執行到這裡
```

**原因**：

- 出貨是核心功能，寄信是輔助功能
- 不能因為寄信失敗，就讓出貨狀態不更新
- 寄信失敗可以後續補救（重寄、查 SQS 紀錄）

### 為什麼無效化 Redis 快取？

```python
redis_client.delete(cache_key)
```

**原因**：

- 出貨後，該訂單變成「已出貨」
- 排行榜統計會改變（多了一筆已完成交易）
- 刪除舊快取，讓下次請求查詢資料庫並寫入最新資料

---

### GET /api/user/auth

**現況：**

- `auth.py` 的 `UserProfileOut` 多定義了 `avg_rating: Union[float, None] = None`
- 導致 Response 中出現 `avg_rating: null`（無實際影響）

**設計意圖：**

- `/api/user/auth`：僅用於身份驗證，不需要 `avg_rating`
- `/api/user/profile`：渲染個人資料頁時才撈取 `avg_rating`

**TODO：**

- [ ] 考慮從 `UserProfileOut` 移除 `avg_rating`，或建立獨立的 `AuthResponse` model

---

### GET /api/user/auth 的 response_model

**現況：**

- `response_model=Optional[UserProfileOut]` 暗示可能回傳 `None`

**實際行為：**

- 若 `get_current_user` 驗證失敗 → 直接拋 `HTTPException 401`，不會進入函數
- 只有當 `get_member_row_by_id(user_id)` 查無資料時才回傳 `None`
- 但這幾乎不可能發生，因為 token 中的 `user_id` 來自有效註冊

**結論：**

- `Optional` 在此處語意不精確，實際上不會回傳 `None`

**TODO：**

- [ ] 移除 `Optional`，改為 `response_model=UserProfileOut`
- [ ] 查無資料時改拋 `HTTPException 404`

---

### Token Payload 與 get_current_user 的 Key 命名

**現況：**

- `create_access_token` 傳入的 payload key 是 `"id"`

```python
  data={"id": user_id, "email": data.email, "name": data.name}
```

- `get_current_user` 回傳的 key 是 `"user_id"`

```python
  user["user_id"]
```

- 因為 `get_current_user` 內部的`verify_token` 有做轉換，所以目前可正常運作

**問題：**

- 命名不一致，增加維護時的認知負擔
- 新開發者容易混淆

**TODO：**

- [ ] 統一命名為 `id` 或 `user_id`（擇一）
- [ ] 同步修改 `create_access_token` 與 `verify_token`

---

### GET /api/user/profile vs GET /api/user/auth

**設計區別：**

| API                 | 用途                     | 是否包含 `avg_rating` |
| ------------------- | ------------------------ | --------------------- |
| `/api/user/auth`    | 驗證登入狀態、渲染導覽列 | ✗ 不需要              |
| `/api/user/profile` | 渲染個人資料頁           | ✓ 需要                |

**現況：**

- 兩者都使用 `UserProfileOut`，但定義在不同檔案（`auth.py` 和 `users.py`）
- 造成重複定義

**TODO：**

- [ ] 考慮將 `UserProfileOut` 集中到 `schemas/user.py`
- [ ] 或為 `/api/user/auth` 建立獨立的 `AuthResponse` model

---

### PUT /api/user/profile 的回傳值

**現況：**

- 更新完成後呼叫 `await get_profile(user)` 取得最新資料
- 這會再次查詢資料庫

**討論：**

- 優點：確保回傳的是資料庫中的最新狀態
- 缺點：多一次資料庫查詢

**結論：**

- 目前做法可接受，資料一致性優先

---

### 路由前綴重複

**現況：**

- `auth.py` 使用 `prefix="/api/user"`
- `users.py` 也使用 `prefix="/api/user"`

**說明：**

- 這是正確的設計，FastAPI 允許多個 router 使用相同前綴
- 在 `main.py` 中分別 `include_router` 即可

---

## Model 層設計原則

### HTTPException 的處理位置

**現況：**

- 部分 Model 函數直接拋 `HTTPException`（如 `ensure_email_unique_for_update`）
- 部分 Model 函數回傳 `None` 讓 Router 處理（如 `get_user_profile`）
- 風格不一致

**理想做法：**

- Model 層只做資料庫操作，回傳資料或 `None`
- Router 層負責判斷並拋出 `HTTPException`

**目前決定：**

- 暫時維持現狀，功能正常運作
- 日後有空再統一重構

**TODO：**

- [ ] 將所有 Model 層的 `HTTPException` 移到 Router 層

---

## 程式碼重構建議

### 重複的資料處理邏輯

`get_buyer_orders_api` 和 `get_seller_orders_api` 有大量重複的資料處理邏輯：

```python
# 以下邏輯在兩個 API 中完全相同
row["start_time"] = str(row["start_time"])[:5]
row["weekday"] = ["一", "二", "三", "四", "五", "六", "日"][row["game_date"].weekday()]
row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
row["stadium_url"] = {...}.get(row["stadium"], "#")
row["image_urls"] = json.loads(row["image_urls"]) if row["image_urls"] else []
row["note"] = row["note"] if row["note"] else ""
```

#### 建議重構方式

**Step 1：將球場 URL 抽到 constants.py**

```python
# config/constants.py
STADIUM_URLS = {
    "大巨蛋": "https://maps.app.goo.gl/m53dt8TAUQkWXBvD9",
    "樂天桃園": "https://maps.app.goo.gl/otKHfBHksTKJk8uV8",
    "台南": "https://maps.app.goo.gl/Y4SgmRbEBCehqaH89",
    "天母": "https://maps.app.goo.gl/WGsmw7y38Apdkcsm7",
    "新莊": "https://maps.app.goo.gl/evnUECyJsLx3rkaE8",
    "澄清湖": "https://maps.app.goo.gl/T4wG6E4ED5jKnxaz6",
    "洲際": "https://maps.app.goo.gl/U6ZfbxwGp1t9APvN7",
    "嘉義市": "https://maps.app.goo.gl/rv8mNF2bnW5xuFcZ8",
    "花蓮": "https://maps.app.goo.gl/UCvKfG29V7uEUc4G6",
    "斗六": "https://maps.app.goo.gl/VmwmTQKSVQ5SBPVFA",
    "台東": "https://maps.app.goo.gl/9yAJEH2JvA5utWfx5",
}
```

**Step 2：抽出共用函數**

```python
# utils/format_utils.py
import json
from datetime import date
from config.constants import STADIUM_URLS

def format_order_row(row: dict, rating_field: str = "rating") -> dict:
    """
    格式化訂單資料，處理時間、球場 URL、評分、圖片等欄位

    Args:
        row: 資料庫回傳的訂單資料
        rating_field: 評分欄位名稱（buyerOrders 用 "seller_rating"，sellerOrders 用 "rating"）
    """
    # start_time: timedelta → "HH:MM"
    row["start_time"] = str(row["start_time"])[:5]

    # game_date: date → weekday + "YYYY-MM-DD"
    if isinstance(row["game_date"], date):
        row["weekday"] = ["一", "二", "三", "四", "五", "六", "日"][row["game_date"].weekday()]
        row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
    else:
        row["weekday"] = "--"

    # stadium → stadium_url
    row["stadium_url"] = STADIUM_URLS.get(row["stadium"], "#")

    # rating: Decimal → float
    if rating_field in row:
        row[rating_field] = float(row[rating_field]) if row[rating_field] is not None else None

    # image_urls: JSON 字串 → list
    row["image_urls"] = json.loads(row["image_urls"]) if row["image_urls"] else []

    # note: None → 空字串
    row["note"] = row["note"] if row["note"] else ""

    return row
```

**Step 3：在 API 中使用**

```python
# routes/orders.py
from utils.format_utils import format_order_row

@router.get("/buyerOrders")
async def get_buyer_orders_api(user: Dict[str, Any] = Depends(get_current_user)):
    try:
        buyer_id = user["user_id"]
        rows = get_buyer_orders(buyer_id)

        for row in rows:
            format_order_row(row, rating_field="seller_rating")

        return rows
    except Exception as e:
        print(f"查詢買家訂單失敗：{e}")
        raise HTTPException(status_code=500, detail="查詢買家訂單失敗")


@router.get("/sellerOrders")
async def get_seller_orders_api(user: Dict[str, Any] = Depends(get_current_user)):
    try:
        seller_id = user["user_id"]
        rows = get_seller_orders(seller_id)

        for row in rows:
            format_order_row(row, rating_field="rating")

        return rows
    except HTTPException:
        raise
    except Exception as e:
        print(f"查詢賣家訂單失敗：{e}")
        raise HTTPException(status_code=500, detail="查詢賣家訂單失敗")
```

#### 重構的好處

| 好處       | 說明                                 |
| ---------- | ------------------------------------ |
| DRY 原則   | 不重複自己（Don't Repeat Yourself）  |
| 單一修改點 | 修改格式邏輯時，只需改一處           |
| 易於測試   | 可以單獨測試 `format_order_row` 函數 |
| 可讀性     | API 程式碼更簡潔，意圖更清楚         |

---

### get_member_email 為什麼要傳入 cursor？

**設計原因：**

- 用於需要 transaction 一致性的場景
- 例如：「更新訂單狀態 → 查詢 email → 寄送通知信」必須在同一個 transaction 中執行
- 若中途失敗，整個操作可以 rollback

**呼叫方式：**

```python
notification_data = None

with get_connection() as conn:
    with conn.cursor(dictionary=True) as cursor:
        # 1. 更新訂單狀態
        cursor.execute("UPDATE orders SET status = %s WHERE id = %s", ...)

        # 2. 查詢 email（沿用同一個 cursor）
        buyer_email = get_member_email(cursor, buyer_id)

        # 3. 暫存通知資料
        notification_data = {"to": buyer_email, "subject": "...", "body": "..."}

    # 4. 全部成功才 commit（在 cursor 區塊外）
    conn.commit()

# 5. commit 後再寄信（在 connection 區塊外，確保連線已釋放）
if notification_data:
    send_email_async(...)
```

**對比其他函數：**

- `get_user_profile` 自己開連線，因為是獨立操作，不需要與其他操作共用 transaction

---

### POST /api/ratings 評分機制

**業務邏輯：**

- 買家在訂單「已出貨」後，可對賣家進行 1-5 星評分
- 每筆訂單只能評分一次

**驗證規則（由 Model 層 `create_rating` 處理）：**

| 規則                         | 驗證位置                     | 錯誤代碼 |
| ---------------------------- | ---------------------------- | -------- |
| 評分需介於 1-5               | Pydantic `Field(ge=1, le=5)` | 422      |
| 需登入才能評分               | `Depends(get_current_user)`  | 401      |
| 訂單必須存在且為該買家的訂單 | Model 層                     | 404      |
| 訂單必須為「已出貨」狀態     | Model 層                     | 400      |
| 不能對自己評分               | Model 層                     | 400      |
| 被評分者必須是該訂單的賣家   | Model 層                     | 400      |
| 同一訂單不可重複評分         | Model 層                     | 400      |

**平均評分計算：**

- `avg_rating` 在 `get_user_profile` 中透過 `LEFT JOIN ratings` + `AVG(r.score)` 動態計算
- 不額外儲存欄位，每次查詢時即時計算

---

## 預約刪除的原子性設計

### 目前實作：SELECT FOR UPDATE + DELETE

**程式碼位置**：`reservation_model.py` 的 `delete_reservation_with_lock()`

**流程**：

1. `SELECT ... FOR UPDATE`：檢查預約是否存在且屬於該會員，同時加排他鎖
2. 若存在 → 執行 `DELETE`
3. `COMMIT` 釋放鎖

**優點**：

- 明確的鎖定機制，語意清楚
- 增進對 transaction 的理解

**缺點**：

- 程式碼較長
- 需要手動管理 transaction

---

### 替代方案：單一 SQL 原子操作

```python
def delete_reservation_atomic(reservation_id: int, member_id: int) -> bool:
    """
    用單一 DELETE 語句刪除預約

    回傳：
    - True：rowcount == 1，有刪到一筆
    - False：rowcount == 0，沒刪到（不存在或不屬於該會員）
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM reservations WHERE id = %s AND member_id = %s",
                (reservation_id, member_id)
            )
            conn.commit()
            # rowcount：這次 SQL 影響的資料筆數
            # == 1 → 有刪到
            # == 0 → 沒刪到（資料不存在或條件不符）
            return cursor.rowcount == 1
```

**優點**：

- 程式碼簡潔
- 檢查 + 刪除在同一個 SQL，天然原子化
- 實務上常用

**缺點**：

- 無法區分「不存在」和「不屬於該會員」兩種情況

**結論**：

- 兩種方式都可以，目前採用 `SELECT FOR UPDATE` 方案
- 若需要更詳細的錯誤訊息，維持現有方案
- 若追求簡潔，可考慮改用單一 SQL 方案

---

### cursor.rowcount 的用法

`cursor.rowcount` 回傳這次 SQL 操作影響的資料筆數。

| SQL 類型 | rowcount 意義                       |
| -------- | ----------------------------------- |
| INSERT   | 插入的筆數（通常是 1）              |
| UPDATE   | 被更新的筆數                        |
| DELETE   | 被刪除的筆數                        |
| SELECT   | -1 或查詢結果筆數（依驅動程式而定） |

**常見應用模式**：

```python
# 刪除操作
cursor.execute("DELETE FROM table WHERE id = %s AND owner_id = %s", (id, owner_id))
if cursor.rowcount == 0:
    # 沒刪到 → 資料不存在 or 不屬於該使用者
    return False
else:
    # rowcount >= 1 → 有刪到
    return True

# 更新操作
cursor.execute("UPDATE table SET status = %s WHERE id = %s", (status, id))
if cursor.rowcount == 0:
    # 沒更新到 → 資料可能不存在
    raise HTTPException(404, "資料不存在")
```

**為什麼用 rowcount 而不是先 SELECT 再判斷？**

1. 減少一次資料庫查詢
2. 天然原子化，不會有 race condition
3. 程式碼更簡潔

---

### 原子寫法 vs SELECT FOR UPDATE 的風險比較

| 寫法                       | Race Condition | 死鎖風險   | 程式碼複雜度 |
| -------------------------- | -------------- | ---------- | ------------ |
| 單一 SQL 原子操作          | ✓ 安全         | ✓ 幾乎沒有 | 簡單         |
| SELECT FOR UPDATE + DELETE | ✓ 安全         | ⚠️ 較高    | 較複雜       |

**死鎖發生情境**：

當一個 transaction 持有鎖 A 並嘗試取得鎖 B，同時另一個 transaction 持有鎖 B 並嘗試取得鎖 A，就會產生死鎖。

**單一 SQL 為什麼沒有死鎖風險？**

只執行一個操作，不會「持有鎖的同時又去等待另一個鎖」。

**目前專案的選擇**：

採用 `SELECT FOR UPDATE` 方案，因為：

1. 可以區分「不存在」和「無權限」兩種錯誤
2. 此場景只鎖單一 row，死鎖風險極低

---

## 資料庫 Transaction 與鎖機制

### 基本概念

#### Transaction（交易）

一個 transaction 是一組「要嘛全部成功，要嘛全部失敗」的資料庫操作。

```python
conn.start_transaction()  # 開始 transaction
cursor.execute("UPDATE ...")
cursor.execute("DELETE ...")
conn.commit()             # 全部成功 → 提交
# 或
conn.rollback()           # 任一失敗 → 全部撤銷
```

#### 為什麼要在同一個 Connection 和 Transaction 內操作？

**鎖是綁定在 transaction 上的**，只在該 transaction 內有效。

| 情況                                   | 結果         |
| -------------------------------------- | ------------ |
| 同一個 connection + 同一個 transaction | ✓ 鎖有效     |
| 不同 connection                        | ✗ 鎖無效     |
| 同一個 connection 但開新 transaction   | ✗ 舊鎖已釋放 |

**錯誤示範**：

```python
with get_connection() as conn1:
    cursor1.execute("SELECT ... FOR UPDATE")  # 取得鎖

with get_connection() as conn2:  # ← 新 connection，鎖已失效
    cursor2.execute("DELETE ...")  # ← 其他人可能已修改資料
```

---

### 併發情境：多個請求同時操作

當多個使用者同時操作同一筆資料時，會產生多個 transaction：

```
使用者 A                          使用者 B
────────                          ────────
SELECT ... FOR UPDATE (取得鎖)
                                  SELECT ... FOR UPDATE (等待中...)
DELETE
COMMIT (釋放鎖)
                                  (取得鎖，但資料已被刪除)
                                  查無資料 → 回傳 False
```

`SELECT FOR UPDATE` 確保在你完成操作前，其他請求必須等待。

---

### 為什麼只做 SELECT 也要 ROLLBACK？

`SELECT FOR UPDATE` 會取得排他鎖，這個鎖會一直持有直到：

- `COMMIT`
- `ROLLBACK`
- 連線關閉

**即使沒有修改資料，也需要明確釋放鎖**，否則其他 transaction 會一直等待。

```python
if not row:
    conn.rollback()  # 沒有要修改，但仍需釋放鎖
    return False
```

---

## 票券上架流程

### POST /api/sell_tickets

**完整流程**：

1. **圖片處理**
   - 驗證副檔名（jpg, jpeg, png）
   - 驗證檔案大小（≤ 5MB）
   - 驗證圖片有效性（使用 PIL）
   - 上傳至 S3，取得 CloudFront URL

2. **票券資料處理**
   - 解析前端傳來的 JSON 字串
   - 將每張票券對應的圖片 URL 整理成 `img_map`

3. **Transaction 操作**（同一個連線內完成）
   - 新增票券到 `tickets_for_sale`
   - 查詢該場次的預約資料
   - 比對價格與座位條件
   - 若匹配成功：新增站內通知 + 收集 Email 資料
   - Commit

4. **寄送通知**（Commit 成功後）
   - 將 Email 發送到 SQS Queue

**為什麼 Email 要在 Commit 後才寄？**

避免「資料庫操作失敗但 Email 已寄出」的情況，確保通知與資料狀態一致。

---

## 函數呼叫流程與返回時機

### 基本原則

Python 函數是**同步執行**的，每一行必須等前一行完成，才會執行下一行。函數到達尾端（或執行 `return`）時，流程才會返回呼叫處。

```python
def outer_function():
    result = inner_function()  # ← 必須等 inner_function 執行完畢
    return result              # ← 才會執行這行
```

### Model 層呼叫 SQS 的流程

當 Transaction 和寄信邏輯都在 Model 層時：

```
Router 層                          Model 層                         SQS 相關函數
    │                                  │                                   │
    │  update_order_and_ticket_status  │                                   │
    ├─────────────────────────────────>│                                   │
    │                                  │                                   │
    │                                  ├── Transaction 操作                │
    │                                  ├── conn.commit()                   │
    │                                  │                                   │
    │                                  │  send_email_async()               │
    │                                  ├──────────────────────────────────>│
    │                                  │                                   ├── send_email_to_queue()
    │                                  │                                   │   (同步：等待 SQS 回應)
    │                                  │                                   │
    │                                  │                                   ├── if 失敗: send_email()
    │                                  │                                   │   (同步：等待 SMTP 回應)
    │                                  │                                   │
    │                                  │  send_email_async 返回            │
    │                                  │<──────────────────────────────────│
    │                                  │                                   │
    │  model 函數結束，返回            │                                   │
    │<─────────────────────────────────│                                   │
    │                                   │                                   │
    ├── return {"status": "success"}   │                                   │
    ▼                                  │                                   │
```

### 「非同步寄信」的真正含義

| 動作                      | 執行方式   | 說明                        |
| ------------------------- | ---------- | --------------------------- |
| `send_email_async()`      | 同步       | 函數執行完才返回            |
| `send_email_to_queue()`   | 同步       | 呼叫 SQS API，等待回應      |
| `send_email()` (fallback) | 同步       | 呼叫 SMTP，等待回應         |
| Lambda 取出任務並寄信     | **非同步** | 在背景執行，與 API 完全無關 |

**「非同步」指的是**：實際寄信由 Lambda 在背景處理，API 不需要等待寄信完成。

**「把任務放進 Queue」本身是同步的**：`send_email_to_queue` 會等待 SQS 回應（成功/失敗）後才返回。

### 為什麼流程一定會返回 Router 層？

`send_email_async` 設計為**永不 raise**：

```python
def send_email_async(to, subject, body) -> None:
    success = send_email_to_queue(...)  # ← 回傳 True/False，不 raise
    if not success:
        send_email(...)                  # ← 內部 try-except，不 raise
    # 函數正常結束，返回 None
```

| 情況                | `send_email_to_queue` | `send_email`         | 結果         |
| ------------------- | --------------------- | -------------------- | ------------ |
| SQS 成功            | return True           | 不執行               | 函數正常結束 |
| SQS 失敗，SMTP 成功 | return False          | 成功                 | 函數正常結束 |
| SQS 失敗，SMTP 失敗 | return False          | catch 例外，記錄 log | 函數正常結束 |

**結論**：無論發生什麼情況，`send_email_async` 都會正常結束，流程一定會返回 Model 層 → 返回 Router 層。

### 時序圖：詳細版

```
時間軸 →

Router:  ─────┬─────────────────────────────────────────────────────┬─────────>
              │                                                     │
              │ 呼叫 update_order_and_ticket_status                 │ return success
              ▼                                                     │
Model:        ├── SELECT ─── UPDATE ─── INSERT ─── commit ──┬───────┤
                                                            │       │
                                                            │ 呼叫  │ 返回
                                                            ▼       │
send_email_async:                                           ├───────┤
                                                            │       │
                                                      ┌─────┴─────┐ │
                                                      │ SQS 成功? │ │
                                                      └─────┬─────┘ │
                                                       Yes  │  No   │
                                                            │   │   │
                                                            │   ▼   │
                                                            │ send_email (fallback)
                                                            │   │   │
                                                            ▼   ▼   │
                                                         返回 ─────>│
                                                                    │
                                                                    ▼
                                                              API 回傳
```

### 設計原則總結

| 原則           | 說明                                             |
| -------------- | ------------------------------------------------ |
| Commit 優先    | 核心功能（Transaction）完成後，才處理寄信        |
| 寄信不影響核心 | `send_email_async` 永不 raise，不會導致 API 失敗 |
| 有 Fallback    | SQS 失敗時，降級為同步寄信                       |
| 可追溯         | 所有失敗都有 log 記錄                            |

---

## SQS 非同步寄信：流程與觀念

### 白話理解

**`send_email_async`（發送任務到 SQS Queue）**：

- 這是一個**同步**函數
- 功能是「把寄信任務放進 SQS Queue」
- 無論成功或失敗，都會在做完這個發送動作後正常結束
- 結束後，流程自動返回呼叫它的函數（例如 Model 層的 `update_order_and_ticket_status`）

**Lambda Function（實際執行寄信）**：

- 這是**非同步**運作的
- 設計成「當有任務被放到 SQS Queue 時，AWS 自動觸發 Lambda 來執行寄信」
- 這個實際寄信的動作是在**背景執行**，與 API 完全無關
- API 不會等待 Lambda 執行完畢

**兩者的關係**：

- Model 層的 `update_order_and_ticket_status` 只與 `send_email_async` 有關
- 只要 `send_email_async` 正常結束（不 raise），`update_order_and_ticket_status` 就會正常結束並返回 Router 層
- Lambda 是另外獨立運作的程式，與 `update_order_and_ticket_status` 函數無關

### 流程說明

```python
def update_order_and_ticket_status(...) -> None:
    # ... Transaction 操作 ...
    conn.commit()              # ← 1. commit 執行完畢後

    send_email_async(...)      # ← 2. 才呼叫 send_email_async
                               #      send_email_async 是同步函數，執行完畢後才會返回
                               #      內部設計為「永不 raise」，無論成功或失敗都正常結束

    # ← 3. send_email_async 返回後，本函數到達尾端，流程返回 Router 層
    # ← 4. 真正的「非同步」是 Lambda 從 SQS 取出任務並寄信，與本函數無關
```

### 為什麼這樣設計？

| 設計決策                      | 原因                                            |
| ----------------------------- | ----------------------------------------------- |
| `send_email_async` 永不 raise | 寄信是輔助功能，不應影響核心功能（Transaction） |
| 任務放進 SQS 後立即返回       | API 快速回應，不需等待實際寄信完成              |
| Lambda 在背景執行             | 寄信可能需要 2-5 秒，不應阻塞 API               |
| Lambda 獨立運作               | 即使 Lambda 失敗，API 早已回傳成功              |

### 時序圖

```
API 請求
    │
    ▼
Transaction Commit（核心功能完成）
    │
    ▼
send_email_async()（同步：把任務放進 Queue）
    │
    ├── 成功 → 任務進入 SQS Queue
    │
    └── 失敗 → fallback 同步寄信（也不會 raise）
    │
    ▼
函數結束，返回 Router 層
    │
    ▼
return {"status": "success"}
    │
    ▼
API 回傳給前端

                    ════════════════════════════════════════
                    ║ 以下是背景執行，與 API 完全無關        ║
                    ════════════════════════════════════════
                                        │
                                        ▼
                                SQS Queue 有新任務
                                        │
                                        ▼
                              AWS 觸發 Lambda Function
                                        │
                                        ▼
                              Lambda 執行實際寄信
                                        │
                                        ├── 成功 → 訊息從 Queue 刪除
                                        │
                                        └── 失敗 → 重試 → 超過次數進 DLQ
```

### 常見誤解釐清

| 誤解                               | 正確理解                                         |
| ---------------------------------- | ------------------------------------------------ |
| `send_email_async` 是非同步函數    | 它是**同步**函數，只是名稱有 async               |
| 呼叫 `send_email_async` 後立即返回 | 必須等它執行完畢才會返回                         |
| API 會等待 Email 寄出              | API 只等待「任務放進 Queue」，不等待「實際寄信」 |
| Lambda 失敗會影響 API              | Lambda 是獨立運作，與 API 無關                   |

---

---

## SQS 非同步寄信機制

### 架構概述

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              非同步寄信架構                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌───────────┐  │
│  │   FastAPI   │      │  SQS Queue  │      │   Lambda    │      │   SMTP    │  │
│  │  (EC2 上)   │ ──── │  (AWS 上)   │ ──── │  (AWS 上)   │ ──── │  Server   │  │
│  │             │      │             │      │             │      │  (Gmail)  │  │
│  └─────────────┘      └─────────────┘      └─────────────┘      └───────────┘  │
│        │                                                                        │
│        │ SQS 失敗時 fallback                                                    │
│        ▼                                                                        │
│  ┌─────────────┐                                                                │
│  │  同步寄信   │                                                                │
│  │  (直接呼叫  │                                                                │
│  │   SMTP)    │                                                                │
│  └─────────────┘                                                                │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 三個檔案的職責

| 檔案              | 位置          | 職責                                  |
| ----------------- | ------------- | ------------------------------------- |
| `email_utils.py`  | FastAPI (EC2) | 對外統一介面，決定用 SQS 或同步寄信   |
| `sqs_utils.py`    | FastAPI (EC2) | 發送任務到 SQS Queue（Producer）      |
| `email_sender.py` | AWS Lambda    | 從 SQS 取出任務並實際寄信（Consumer） |

---

### 完整流程圖

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              完整寄信流程                                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  Model 層 (eg. commit_payment_success_tx)                                       │
│       │                                                                         │
│       │ 1. 資料庫操作完成                                                        │
│       │ 2. conn.commit()                                                        │
│       │ 3. 呼叫 send_email_async()                                              │
│       ▼                                                                         │
│  ┌─────────────────────────────────────────┐                                    │
│  │         email_utils.py                  │                                    │
│  │         send_email_async()              │                                    │
│  │              │                          │                                    │
│  │              │ 呼叫 send_email_to_queue()                                    │
│  │              ▼                          │                                    │
│  │  ┌─────────────────────────────────┐    │                                    │
│  │  │       sqs_utils.py              │    │                                    │
│  │  │       send_email_to_queue()     │    │                                    │
│  │  │            │                    │    │                                    │
│  │  │            ├── 檢查 SQS_URL     │    │                                    │
│  │  │            ├── 取得 SQS Client  │    │                                    │
│  │  │            ├── 發送訊息到 Queue │    │                                    │
│  │  │            │                    │    │                                    │
│  │  │            ▼                    │    │                                    │
│  │  │     return True / False         │    │                                    │
│  │  └─────────────────────────────────┘    │                                    │
│  │              │                          │                                    │
│  │              ▼                          │                                    │
│  │     if not success:                     │                                    │
│  │         send_email() ← Fallback 同步寄信│                                    │
│  │                                         │                                    │
│  │     函數結束，返回 Model 層             │                                    │
│  └─────────────────────────────────────────┘                                    │
│       │                                                                         │
│       ▼                                                                         │
│  Model 層函數結束，返回 Router 層                                                │
│       │                                                                         │
│       ▼                                                                         │
│  API 回傳 {"status": "success"} 給前端                                          │
│                                                                                 │
│  ════════════════════════════════════════════════════════════════════════════   │
│                                                                                 │
│  【與此同時，在 AWS 背景】                                                       │
│                                                                                 │
│  SQS Queue 有新訊息                                                             │
│       │                                                                         │
│       │ AWS 自動觸發                                                            │
│       ▼                                                                         │
│  ┌─────────────────────────────────────────┐                                    │
│  │       email_sender.py (Lambda)          │                                    │
│  │       lambda_handler()                  │                                    │
│  │            │                            │                                    │
│  │            ├── 解析 SQS 訊息            │                                    │
│  │            ├── 檢查訊息類型             │                                    │
│  │            ├── 取出 Email 資訊          │                                    │
│  │            ├── 呼叫 send_email()        │                                    │
│  │            │                            │                                    │
│  │            ▼                            │                                    │
│  │     實際寄出 Email                      │                                    │
│  └─────────────────────────────────────────┘                                    │
│       │                                                                         │
│       ▼                                                                         │
│  Lambda 正常結束 → SQS 自動刪除訊息                                              │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 生產者/消費者模式

| 角色               | 說明                  | 在本專案中              |
| ------------------ | --------------------- | ----------------------- |
| 生產者（Producer） | 把任務放進 Queue      | `send_email_to_queue()` |
| 消費者（Consumer） | 從 Queue 取出任務處理 | `lambda_handler()`      |
| Queue              | 暫存任務的緩衝區      | AWS SQS                 |

```
Producer                    Queue                     Consumer
(FastAPI)                   (SQS)                     (Lambda)
    │                         │                          │
    │  send_message()         │                          │
    ├────────────────────────>│                          │
    │                         │                          │
    │                         │  AWS 自動觸發            │
    │                         ├─────────────────────────>│
    │                         │                          │
    │                         │                          ├── 處理任務
    │                         │                          │
    │                         │  處理完成，刪除訊息      │
    │                         │<─────────────────────────│
    │                         │                          │
```

---

### 「非同步」的真正含義

| 動作                      | 執行方式   | 說明                                 |
| ------------------------- | ---------- | ------------------------------------ |
| `send_email_async()`      | **同步**   | 函數執行完才返回（只是名稱有 async） |
| `send_email_to_queue()`   | **同步**   | 呼叫 SQS API，等待回應               |
| `send_email()` (fallback) | **同步**   | 呼叫 SMTP，等待回應                  |
| Lambda 取出任務並寄信     | **非同步** | 在背景執行，與 API 完全無關          |

**重點**：API 只等待「任務放進 Queue」，不等待「實際寄信」。

---

### 錯誤處理策略：為何「永不 raise」

#### 設計原則

```
核心功能（資料庫操作）          輔助功能（寄信）
        │                           │
        │ commit 成功               │
        ├───────────────────────────┤
        │                           │ 可能失敗
        │                           │
        ▼                           ▼
   API 應回 200              不應影響 API 結果
```

#### 如果 raise 會發生什麼事？

```
Model 層
    │
    ├── conn.commit()  ← 成功
    │
    ├── send_email_async()
    │       │
    │       └── send_email_to_queue()
    │               │
    │               └── raise Exception  ← 寄信失敗
    │
    │   例外往上拋
    ▼
Router 層
    │
    └── 包成 HTTP 500 回給前端

結果：資料庫成功寫入，但前端收到 500，與真實情況不符！
```

#### 三個檔案的錯誤處理設計

| 檔案             | 函數                    | 錯誤處理               | 原因              |
| ---------------- | ----------------------- | ---------------------- | ----------------- |
| `sqs_utils.py`   | `send_email_to_queue()` | return False，不 raise | 讓呼叫端 fallback |
| `email_utils.py` | `send_email_async()`    | 呼叫 fallback 同步寄信 | 功能不中斷        |
| `email_utils.py` | `send_email()`          | 記 log，不 raise       | 不影響核心流程    |

---

### Lambda 與 SQS 的整合機制

#### Lambda 處理結果與 SQS 行為

| Lambda 行為              | SQS 反應                                                   |
| ------------------------ | ---------------------------------------------------------- |
| 正常結束（return）       | AWS Lambda Service 呼叫 SQS DeleteMessage API，訊息被刪除  |
| 拋出例外（raise）        | 不呼叫 DeleteMessage，訊息在 visibility timeout 後重新可見 |
| 重試超過 maxReceiveCount | 訊息移到 Dead Letter Queue (DLQ)                           |

#### 運作原理圖

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         Lambda + SQS 整合機制                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. SQS 把訊息傳給 Lambda                                                       │
│     │                                                                           │
│     │ 此時訊息進入「處理中」狀態（不可見）                                        │
│     │ visibility timeout 開始倒數（預設 30 秒）                                  │
│     ▼                                                                           │
│  2. Lambda 執行 lambda_handler                                                  │
│     │                                                                           │
│     ├── 正常結束（return）                                                      │
│     │   │                                                                       │
│     │   │ AWS Lambda Service 呼叫 SQS 的 DeleteMessage API                      │
│     │   ▼                                                                       │
│     │   訊息被刪除 ✓                                                            │
│     │                                                                           │
│     └── 拋出例外（raise）                                                       │
│         │                                                                       │
│         │ AWS Lambda Service 不呼叫 DeleteMessage                               │
│         │ 訊息維持「處理中」狀態                                                 │
│         ▼                                                                       │
│         visibility timeout 到期後，訊息重新可見                                  │
│         │                                                                       │
│         ▼                                                                       │
│         下一個 Lambda 實例取走訊息，重試處理                                     │
│         │                                                                       │
│         ▼                                                                       │
│         超過 maxReceiveCount（3 次）→ 訊息移到 DLQ                              │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### Exception 分類處理原則

**設計原則：已知的永久性問題不重試，未知問題預設重試（保守策略）**

| 錯誤類型          | 處理方式 | 原因                             |
| ----------------- | -------- | -------------------------------- |
| `JSONDecodeError` | 不 raise | 格式錯誤是永久性問題，重試也沒用 |
| `SMTPException`   | 不 raise | 可能是收件人無效，重試也沒用     |
| 未預期錯誤        | raise    | 可能是暫時性問題，重試可能成功   |

#### 批次處理的影響

| 情況           | 發生的事                                                                    |
| -------------- | --------------------------------------------------------------------------- |
| 某一筆 raise   | 整批任務（這次 Lambda 收到的所有 Records）都被視為失敗，全部回到 Queue 重試 |
| 某一筆不 raise | 只有那筆不會重試（被視為成功刪除），其他正常處理                            |

**結論**：對已知的永久性問題不 raise，避免一筆壞訊息影響整批。

---

### Singleton Pattern：SQS Client 連線管理

#### 建立連線的時機

```
時間軸 →

1. import sqs_utils
   │
   └── _sqs_client = None  ← 只是初始化變數為 None，沒有建立連線

2. 第一次呼叫 send_email_to_queue()
   │
   └── sqs = get_sqs_client()
       │
       └── if _sqs_client is None:  ← 是 None
           │
           └── _sqs_client = boto3.client(...)  ← 這時才建立連線！

3. 第二次呼叫 send_email_to_queue()
   │
   └── sqs = get_sqs_client()
       │
       └── if _sqs_client is None:  ← 不是 None
           │
           └── 直接 return _sqs_client  ← 重複使用，不重新連線
```

#### 為什麼使用 Singleton Pattern

| 問題                                     | 解決方案                        |
| ---------------------------------------- | ------------------------------- |
| 每次呼叫 `boto3.client()` 都會建立新連線 | 用 Singleton 只建立一次         |
| 連線建立需要時間（網路延遲）             | 重複使用已建立的連線            |
| 如果每封 Email 都建立新連線，浪費資源    | 整個程式執行期間共用一個 Client |

#### 為什麼變數要宣告在函數外面

```python
# ❌ 錯誤寫法：寫在函數裡面
def get_sqs_client():
    _sqs_client = None  # ← 區域變數，每次呼叫都會重設為 None
    if _sqs_client is None:
        _sqs_client = boto3.client(...)  # ← 每次都會重新建立！
    return _sqs_client

# ✓ 正確寫法：寫在函數外面（模組層級）
_sqs_client = None  # ← 模組層級變數，只在 import 時執行一次

def get_sqs_client():
    global _sqs_client  # ← 宣告要修改的是模組層級的變數
    if _sqs_client is None:
        _sqs_client = boto3.client(...)  # ← 只有第一次呼叫才會建立
    return _sqs_client
```

#### Python 變數作用域原則

| 情況                         | 需要 global 嗎                           |
| ---------------------------- | ---------------------------------------- |
| 在函數內「讀取」模組層級變數 | 不需要                                   |
| 在函數內「修改」模組層級變數 | 需要 `global` 宣告                       |
| 沒有 `global` 就修改         | 會建立新的區域變數，不會修改模組層級變數 |

---

### Lambda 觸發來源比較

| 觸發來源        | 用途         | statusCode 要求             | body 格式要求                      |
| --------------- | ------------ | --------------------------- | ---------------------------------- |
| **SQS**         | 背景任務處理 | 不需要（看有沒有 raise）    | 不需要（AWS 不看 body）            |
| **API Gateway** | HTTP API     | **必須**（HTTP 需要狀態碼） | **必須是字串**（HTTP body 是字串） |

#### 本專案的設計

```python
# 雖然是 SQS 觸發，但保持標準格式
result = {
    'statusCode': 200,
    'body': json.dumps({
        'message': 'completed',
        'success': success_count,
        'failed': fail_count,
        'total': len(event['Records'])
    })
}
```

**保持標準格式的好處**：

- 一致性：所有 Lambda 都用相同格式，方便維護
- 可擴展：未來如果要加 API Gateway 觸發，不用改
- 可讀性：看 CloudWatch Logs 時，result 內容清楚

---

### Fallback 機制設計

```
                    send_email_async()
                          │
                          ▼
              send_email_to_queue()
                          │
            ┌─────────────┴─────────────┐
            │                           │
       return True                 return False
            │                           │
            ▼                           ▼
     任務進入 Queue              fallback: send_email()
            │                           │
            │                           │
            ▼                           ▼
    Lambda 背景寄信              直接同步寄信
```

**設計原則**：

1. SQS 正常時：快速將任務放進 Queue，API 可更快回應
2. SQS 異常時：降級成同步寄信，功能不中斷
3. 同步寄信失敗時：記 log 但不 raise，不影響核心流程

---

### 兩個 send_email 函數的比較

| 項目     | FastAPI 版 (`email_utils.py`) | Lambda 版 (`email_sender.py`)   |
| -------- | ----------------------------- | ------------------------------- |
| 位置     | EC2 上                        | AWS Lambda 上                   |
| 角色     | Fallback 備援                 | 主要寄信方式                    |
| 錯誤處理 | 記 log，不 raise              | 讓錯誤往上拋給 `lambda_handler` |
| 重試機制 | 無（失敗就記 log）            | 有（SQS 會重試，最多 3 次）     |
| 監控方式 | 需手動設定 CloudWatch Agent   | 自動整合 CloudWatch Logs        |

**為什麼 Lambda 版讓錯誤往上拋？**

因為 Lambda 的主要職責就是「寄信」，失敗時應該：

1. 讓 `lambda_handler` 的 `try-except` 接住
2. 根據錯誤類型決定是否重試
3. 超過重試次數進入 DLQ，觸發告警通知開發者

---

### messageId 的用途

| 項目     | 說明                            |
| -------- | ------------------------------- |
| 分配時機 | 訊息進入 SQS Queue 時           |
| 重試時   | 沿用原本的編號，不會改變        |
| 用途     | 追蹤同一筆訊息的處理歷程        |
| Debug    | 可串連 FastAPI 和 Lambda 的 log |

---

## 分頁查詢設計

### GET /api/browse_tickets

### 基本概念

分頁用於控制每次查詢回傳的資料筆數，避免一次載入過多資料。

**API 參數**：

| 參數         | 說明                   | 預設值       |
| ------------ | ---------------------- | ------------ |
| `game_id`    | 場次 ID                | 必填         |
| `sort_by`    | 排序欄位               | `created_at` |
| `sort_order` | 排序方向               | `desc`       |
| `seat_areas` | 座位區篩選（逗號分隔） | 無           |
| `page`       | 目前頁碼（從 1 開始）  | 1            |
| `per_page`   | 每頁筆數               | 6            |

**分頁計算**：

| 項目          | 說明       | 計算方式 / 範例值       |
| ------------- | ---------- | ----------------------- |
| `offset`      | 跳過前幾筆 | `(page - 1) * per_page` |
| `total_count` | 總資料筆數 | 由後端查詢後回傳        |

```python
offset = (page - 1) * per_page
# page=1, per_page=6 → offset=0  → 取第 1-6 筆
# page=2, per_page=6 → offset=6  → 取第 7-12 筆
```

### 範例：7 張票券，每頁 6 張

```
總共 7 張票券：[票1, 票2, 票3, 票4, 票5, 票6, 票7]

┌─────────────────────────────────────────────────────┐
│ 第 1 頁 (page=1)                                    │
├─────────────────────────────────────────────────────┤
│ offset = (1-1) * 6 = 0                              │
│ SQL: LIMIT 6 OFFSET 0                               │
│ 結果: [票1, 票2, 票3, 票4, 票5, 票6]  ← 6 筆        │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ 第 2 頁 (page=2)                                    │
├─────────────────────────────────────────────────────┤
│ offset = (2-1) * 6 = 6                              │
│ SQL: LIMIT 6 OFFSET 6                               │
│ 結果: [票7]  ← 只剩 1 筆                            │
└─────────────────────────────────────────────────────┘
```

### SQL 語法

```sql
-- 第 1 頁：跳過 0 筆，取 6 筆
SELECT * FROM tickets LIMIT 6 OFFSET 0;

-- 第 2 頁：跳過 6 筆，取 6 筆（實際只剩 1 筆）
SELECT * FROM tickets LIMIT 6 OFFSET 6;
```

### 前端如何計算總頁數

```javascript
const totalPages = Math.ceil(total_count / per_page);
// Math.ceil(7 / 6) = Math.ceil(1.17) = 2 頁
```

---

## SQL 動態查詢與參數化

### 問題情境

當使用者在前端選擇多個座位區（如「內野」和「外野」）時，後端需要組出這樣的 SQL：

```sql
SELECT * FROM tickets WHERE seat_area IN ('內野', '外野')
```

但我們不能直接把使用者輸入塞進 SQL（會有 SQL Injection 風險），所以要用**參數化查詢**：

```python
cursor.execute(
    "SELECT * FROM tickets WHERE seat_area IN (%s, %s)",
    ("內野", "外野")
)
```

### 完整流程圖

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: 前端發送 Request                                        │
├─────────────────────────────────────────────────────────────────┤
│ URL: /api/browse_tickets?seat_areas=內野,外野                    │
│                                      ↑                          │
│                               逗號分隔的「字串」                  │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: 後端收到字串                                            │
├─────────────────────────────────────────────────────────────────┤
│ seat_areas = "內野,外野"        # 型別: str                      │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: 轉成 list                                               │
├─────────────────────────────────────────────────────────────────┤
│ seat_filters = seat_areas.split(",")                            │
│ seat_filters = ["內野", "外野"]  # 型別: list                    │
│                                                                 │
│ 為什麼要轉 list？                                                │
│ → 需要用 len() 計算有幾個值，才知道要產生幾個 %s                   │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: 產生 placeholder 字串                                   │
├─────────────────────────────────────────────────────────────────┤
│ ["%s"] * len(seat_filters)      # ["%s", "%s"]                  │
│ ", ".join(["%s", "%s"])         # "%s, %s"                      │
│ placeholders = "%s, %s"          # 型別: str                    │
│                                                                 │
│ 為什麼要轉字串？                                                 │
│ → 因為要塞進 f-string 組成 SQL 字串                              │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: 組成 SQL 字串                                           │
├─────────────────────────────────────────────────────────────────┤
│ query = f"SELECT * FROM t WHERE seat_area IN ({placeholders})"  │
│ query = "SELECT * FROM t WHERE seat_area IN (%s, %s)"           │
│                                              ↑                  │
│                                     這是 SQL 語法的小括號        │
│                                     不是 Python tuple           │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: 執行查詢                                                │
├─────────────────────────────────────────────────────────────────┤
│ cursor.execute(query, tuple(seat_filters))                      │
│                       ↑                                         │
│                       ("內野", "外野")  # 型別: tuple            │
│                                                                 │
│ 為什麼最後要轉 tuple？                                           │
│ → cursor.execute() 的第二個參數習慣用 tuple                      │
│ → 其實 list 也可以，但 tuple 是慣例                              │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 7: 資料庫實際執行的 SQL                                     │
├─────────────────────────────────────────────────────────────────┤
│ SELECT * FROM t WHERE seat_area IN ('內野', '外野')              │
│                                                                 │
│ 資料庫驅動程式會自動：                                           │
│ 1. 把 %s 替換成參數值                                           │
│ 2. 自動加上引號                                                 │
│ 3. 自動處理跳脫字元（防止 SQL Injection）                        │
└─────────────────────────────────────────────────────────────────┘
```

### 型別轉換總覽

| 步驟 | 變數                | 型別  | 值                 |
| ---- | ------------------- | ----- | ------------------ |
| 1    | URL 參數            | str   | `"內野,外野"`      |
| 2    | seat_filters        | list  | `["內野", "外野"]` |
| 3    | placeholders        | str   | `"%s, %s"`         |
| 4    | query               | str   | `"...IN (%s, %s)"` |
| 5    | tuple(seat_filters) | tuple | `("內野", "外野")` |

### 為什麼過程中要用 list 而不是直接用 tuple？

```python
# list 可以動態增加元素
data_params = [game_id]              # 先放第一個參數
data_params.extend(seat_filters)     # 追加座位條件
data_params.extend([per_page, offset])  # 追加分頁參數

# tuple 不能修改，所以最後才轉
cursor.execute(query, tuple(data_params))
```

### 三種括號的區別

| 符號                  | 出現位置      | 意義             |
| --------------------- | ------------- | ---------------- |
| `["內野", "外野"]`    | Python 程式碼 | Python list      |
| `("內野", "外野")`    | Python 程式碼 | Python tuple     |
| `IN ('內野', '外野')` | SQL 語法      | SQL 的集合表示法 |

這三種括號只是長得像，但意義完全不同。

---

## SQL Injection 防範

### 什麼是 SQL Injection？

攻擊者在輸入欄位插入惡意 SQL，試圖操控資料庫。

### 防範方式一：參數化查詢

```python
# ❌ 危險：直接拼接
query = f"SELECT * FROM users WHERE name = '{user_input}'"

# ✅ 安全：參數化查詢
cursor.execute("SELECT * FROM users WHERE name = %s", (user_input,))
```

### 防範方式二：白名單 Mapping

對於無法參數化的部分（如 ORDER BY 欄位名），使用 mapping：

```python
# ❌ 危險：直接使用前端參數
query = f"ORDER BY {sort_by}"  # 攻擊者可傳入 "id; DROP TABLE users"

# ✅ 安全：用 mapping 對應
sort_column = {
    "created_at": "t.created_at",
    "price": "t.price",
    "rating": "IFNULL(avg_rating, 0)",
}[sort_by]
query = f"ORDER BY {sort_column}"
```

即使攻擊者傳入惡意字串，也只會因為 key 不存在而報 KeyError，不會被執行。

---

## IFNULL 函數

### 語法

```sql
IFNULL(A, B)
-- 如果 A 不是 NULL → 回傳 A
-- 如果 A 是 NULL → 回傳 B
```

### 用途：排序時處理 NULL

```sql
ORDER BY IFNULL(avg_rating, 0) DESC
```

| 賣家 | avg_rating | IFNULL 結果 | 排序 |
| ---- | ---------- | ----------- | ---- |
| A    | 4.5        | 4.5         | 1    |
| B    | 3.0        | 3.0         | 2    |
| C    | NULL       | 0           | 3    |

沒有評分的賣家會被當作 0 分來排序。

---

## Python Dict 取值方式

### `dict["key"]` vs `dict.get("key")`

| 寫法              | key 不存在時                | 適用情境          |
| ----------------- | --------------------------- | ----------------- |
| `dict["key"]`     | 拋出 `KeyError`，程式崩潰   | 確定 key 一定存在 |
| `dict.get("key")` | 回傳 `None`（或指定預設值） | key 可能不存在    |

**專案中的選擇**：

```python
# 使用 dict["key"]
member_id = user["user_id"]
```

因為 `user` 來自 `get_current_user`，若驗證通過，`user_id` 一定存在。
若 key 不存在代表程式邏輯有誤，應該讓程式崩潰以便發現問題。

---

## 查詢參數 vs 路徑參數

### 差異比較

| 項目     | 路徑參數 (Path Parameter) | 查詢參數 (Query Parameter)      |
| -------- | ------------------------- | ------------------------------- |
| URL 格式 | `/api/events/2025/7`      | `/api/events?year=2025&month=7` |
| 用途     | 識別**特定資源**          | 篩選/過濾/分頁                  |
| 必填性   | 通常必填                  | 可選（有預設值）                |
| 語意     | 「取得這個資源」          | 「用這些條件查詢」              |

### 本專案的選擇

`/api/events` 和 `/api/schedule` 使用**查詢參數**：

```python
@router.get("/events")
async def get_events_api(year: int, month: int):  # 查詢參數
```

**原因**：

1. **語意正確**：查詢「2025 年 7 月的比賽」是一種篩選行為，不是取得特定資源
2. **彈性更高**：未來可輕鬆新增其他篩選條件（如 `team`、`stadium`）
3. **前端習慣**：前端組 URL 時，查詢參數更直觀

```javascript
fetch(`/api/events?year=${y}&month=${m}`);
```

### 何時用路徑參數？

當你要取得「特定一筆資料」時：

```python
@router.get("/games/{game_id}")  # 取得特定比賽
async def get_game(game_id: int):
```

---

## Python Logging 機制

### 設定方式

**Step 1：在 config/settings.py 定義 LOG_LEVEL**

```python
# config/settings.py
ENV = os.getenv("ENV", "development")
DEBUG = ENV == "development"

# 開發環境預設 DEBUG，正式環境預設 WARNING
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "WARNING")
```

**Step 2：在 app.py 設定全域 root logger**

```python
# app.py
import logging
from config.settings import LOG_LEVEL

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
```

`getattr(logging, "INFO")` 的作用是把字串 `"INFO"` 轉成 `logging.INFO`（數字 20），因為 `logging.basicConfig()` 的 level 參數需要數字。

**Step 3：在各模組取得專屬 logger**

```python
# routes/games.py
import logging
logger = logging.getLogger(__name__)
```

`__name__` 會是模組的完整路徑，例如 `routes.games`，方便從 log 訊息中辨識來源。

---

### Log 層級

| 層級     | 數值 | 用途                   | 範例                      |
| -------- | ---- | ---------------------- | ------------------------- |
| DEBUG    | 10   | 開發除錯用             | 變數值、流程追蹤          |
| INFO     | 20   | 正常運作資訊           | 請求開始、快取命中        |
| WARNING  | 30   | 警告但不影響功能       | Redis 連線失敗，降級查 DB |
| ERROR    | 40   | 錯誤，功能受影響       | 資料庫查詢失敗            |
| CRITICAL | 50   | 嚴重錯誤，系統可能崩潰 | 無法啟動服務              |

---

### 層級過濾機制

```
DEBUG(10) < INFO(20) < WARNING(30) < ERROR(40) < CRITICAL(50)
```

設定的 level 決定「最低顯示層級」，低於此層級的訊息會被過濾：

```python
# 設定 level=INFO (20)
logger.debug("不會顯示")    # 10 < 20，被過濾
logger.info("會顯示")       # 20 >= 20，顯示
logger.warning("會顯示")    # 30 > 20，顯示
```

---

### 本專案的環境變數設定

**config/settings.py**

```python
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "WARNING")
```

**.env（本機開發）**

```ini
ENV=development
LOG_LEVEL=DEBUG
```

**.env（EC2 生產環境）**

```ini
ENV=production
LOG_LEVEL=WARNING
```

**.env-example（給其他開發者參考）**

```ini
# Log 設定
# 可選值: DEBUG, INFO, WARNING, ERROR
# 本機開發: DEBUG
# EC2 生產環境: WARNING
LOG_LEVEL=DEBUG
```

| 環境 | LOG_LEVEL | 說明                          |
| ---- | --------- | ----------------------------- |
| 開發 | DEBUG     | 顯示所有訊息，方便除錯        |
| 正式 | WARNING   | 只顯示警告和錯誤，減少 log 量 |

---

### Log 輸出位置（stdout）

**stdout（Standard Output）** 是程式輸出訊息的預設出口，顯示在終端機畫面上。

```python
print("Hello")           # 輸出到 stdout
logger.info("Hello")     # 預設輸出到 stderr（也顯示在終端機）
```

`logging.basicConfig()` 不指定 `filename` 時，預設輸出到終端機：

```
2026-02-12 14:30:15 [INFO] routes.games - request start key=top_games:2026-02
2026-02-12 14:30:15 [INFO] routes.games - cache MISS key=top_games:2026-02
2026-02-12 14:30:16 [INFO] routes.games - DB query done rows=5
```

如需輸出到檔案，可加上 `filename` 參數：

```python
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    filename="app.log"
)
```

注意：若使用檔案輸出，需在 `.gitignore` 中加入 `*.log`。

---

### 本專案的 Log 設計範例

```python
# 請求開始：記錄 cache_key，方便追蹤
logger.info(f"request start key={cache_key}")

# 快取命中：記錄 bytes 大小，快速判斷資料是否異常
logger.info(f"cache HIT key={cache_key} bytes={len(cached_data)}")

# 快取未命中：區分「沒 key」和「Redis 出錯」
logger.info(f"cache MISS key={cache_key}")

# Redis 錯誤：降級處理，不中斷服務
logger.warning(f"Redis 連線錯誤，降級查詢資料庫: err={e}")

# 資料庫錯誤：中斷服務，回傳 500
logger.error(f"查詢資料庫失敗: {e}")

# 開發調試用：正式環境 level=WARNING 時不會顯示
logger.debug(f"Recommended games: {[g['game_id'] for g in top_games[:5]]}")
```

**Log 設計原則**：

| 原則                | 說明                                         |
| ------------------- | -------------------------------------------- |
| 記錄 key/id         | 方便定位是哪筆資料出問題                     |
| 記錄 bytes/rows     | 快速判斷資料量是否異常（空、太大）           |
| 區分 hit/miss/error | 從 log 一眼看出是「沒資料」還是「系統出錯」  |
| WARNING 不中斷      | 輔助功能（快取）出錯時降級，核心功能繼續運作 |
| ERROR 才中斷        | 核心功能（資料庫）出錯時才回傳錯誤           |

---

## MySQL cursor 回傳格式

### 基本規則

| 方法                | 回傳格式                      | 無資料時        |
| ------------------- | ----------------------------- | --------------- |
| `cursor.fetchone()` | 單筆 dict 或 tuple            | `None`          |
| `cursor.fetchall()` | list of dict 或 list of tuple | `[]`（空 list） |

### dictionary=True 的差異

```python
# dictionary=False（預設）
cursor.fetchone()   # (15,)
cursor.fetchall()   # [(15,), (20,)]

# dictionary=True
cursor.fetchone()   # {"total_trades": 15}
cursor.fetchall()   # [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
```

### 重要觀念

```python
# fetchall() 無資料時回傳空 list，不是 None
results = cursor.fetchall()  # []
for row in results:  # 迴圈執行 0 次，不會報錯
    ...

# fetchone() 無資料時回傳 None
result = cursor.fetchone()  # None
result["key"]  # ❌ TypeError: 'NoneType' object is not subscriptable
```

### COUNT(\*) vs SUM() 的差異

```sql
-- 無資料時
SELECT COUNT(*) FROM orders WHERE 1=0  -- 回傳 0（數字）
SELECT SUM(amount) FROM orders WHERE 1=0  -- 回傳 NULL
```

```python
# COUNT(*) 不需要額外檢查
return result["total_trades"]

# SUM() 需要處理 NULL
return result["total_amount"] or 0
```

---

---

## 安全性設計：信任邊界與 Race Condition

### 信任邊界（Trust Boundary）

#### 定義

**信任邊界**是系統中「可信任區域」與「不可信任區域」的分界線。

```
┌─────────────────────────────────────────────────────────┐
│                    不可信任區域                          │
│  ┌─────────┐     ┌─────────┐     ┌─────────────┐       │
│  │  使用者  │     │  前端    │     │ 外部 API   │        │
│  └─────────┘     └─────────┘     └─────────────┘       │
└─────────────────────────────────────────────────────────┘
                         │
                         │ ← 信任邊界
                         ▼
┌─────────────────────────────────────────────────────────┐
│                    可信任區域                            │
│  ┌─────────┐     ┌─────────┐     ┌─────────────┐       │
│  │  後端    │     │ 資料庫  │     │ 內部服務    │        │
│  └─────────┘     └─────────┘     └─────────────┘       │
└─────────────────────────────────────────────────────────┘
```

#### 核心原則

**永遠不要信任來自不可信任區域的資料**

前端傳來的任何資料都可能是：

- 被竄改的（使用者修改了 JavaScript 或 API 請求）
- 過期的（資料在傳輸過程中已經改變）
- 惡意的（攻擊者刻意構造的資料）

#### 常見的信任邊界驗證

| 驗證項目   | 說明                     | 範例                                    |
| ---------- | ------------------------ | --------------------------------------- |
| 資料存在性 | 確認 ID 對應的資料存在   | `SELECT ... WHERE id = %s`              |
| 權限檢查   | 確認使用者有權操作該資料 | `order["seller_id"] != current_user_id` |
| 狀態檢查   | 確認資料處於可操作的狀態 | `order["status"] == "媒合中"`           |
| 格式驗證   | 確認資料格式正確         | Pydantic Model 驗證                     |

---

### Race Condition（競爭條件）

#### 定義

**Race Condition** 是指多個並發操作同時存取共享資源時，因為執行順序的不確定性，導致結果不符合預期。

#### 本專案的兩個 Race Condition 發生點

| 發生點               | 函數                             | 後果                             | 嚴重程度 |
| -------------------- | -------------------------------- | -------------------------------- | -------- |
| 多人同時發送媒合請求 | `create_order`                   | 同一張票產生多筆「媒合中」訂單   | **低**   |
| 賣家快速接受多筆訂單 | `update_order_and_ticket_status` | 同一張票產生多筆「媒合成功」訂單 | **高**   |

---

#### Race Condition 1：create_order（影響較小）

**問題說明**

```python
def create_order(ticket_id: int, buyer_id: int) -> None:
    # Step 1: 檢查票券是否已售出
    cursor.execute("SELECT is_sold FROM tickets_for_sale WHERE id = %s", (ticket_id,))
    if ticket["is_sold"]:
        raise HTTPException(status_code=400, detail="此票券已售出")

    # ← 這裡有時間差！

    # Step 2: INSERT 新訂單（狀態為「媒合中」）
    cursor.execute("INSERT INTO orders ...")

    conn.commit()
```

**實際情境**

場景：有一張票券 `ticket_id=100`，兩個買家 A 和 B **幾乎同時**想要這張票。

```
時間軸 →

買家 A:  ─── [SELECT 檢查] ─────────────────── [INSERT 訂單] ─── [commit]
                  ↓
              票券未售出 ✓

買家 B:  ──────────── [SELECT 檢查] ─── [INSERT 訂單] ─── [commit]
                            ↓
                        票券未售出 ✓
                        （A 還沒 commit，is_sold 還是 False）
```

**結果**：同一張票產生了**兩筆「媒合中」的訂單**。

**為什麼影響較小？**

因為「媒合中」只是表示買家提出了請求，票券還沒有真正賣出。

```
訂單生命週期：

買家發送媒合請求 → 訂單狀態「媒合中」（可以有多筆）
                        ↓
賣家接受其中一筆 → 該筆訂單變成「媒合成功」，票券 is_sold = True
                        ↓
                    其他「媒合中」的訂單：賣家拒絕，或維持「媒合中」
```

| 步驟 | 發生的事                                      |
| ---- | --------------------------------------------- |
| 1    | 買家 A 和 B 同時對票券 100 發送媒合請求       |
| 2    | 產生兩筆「媒合中」的訂單（訂單 #1 和 #2）     |
| 3    | 賣家在「我的售票」頁面看到兩筆媒合請求        |
| 4    | 賣家選擇接受訂單 #1（買家 A）                 |
| 5    | 訂單 #1 變成「媒合成功」，票券 is_sold = True |
| 6    | 賣家拒絕訂單 #2，或訂單 #2 維持「媒合中」     |

**結論**：

- 最多就是產生多筆「媒合中」的訂單
- 賣家只會接受其中一筆
- 不會造成「同一張票賣給兩個人」的嚴重問題
- 真正決定誰買到票的是「賣家接受媒合」，而非「發送媒合請求」

---

#### Race Condition 2：update_order_and_ticket_status（潛在嚴重問題）

**問題說明**

如果賣家快速點擊多個「接受」按鈕呢？

```
時間軸 →

接受訂單 #1:  ─── [檢查狀態=媒合中 ✓] ─────────────── [UPDATE 媒合成功] ─── [UPDATE is_sold=True] ─── [commit]

接受訂單 #2:  ──────── [檢查狀態=媒合中 ✓] ─── [UPDATE 媒合成功] ─── [UPDATE is_sold=True] ─── [commit]
                              ↑
                        訂單 #2 的狀態確實是「媒合中」
                        此時訂單 #1 還沒 commit，is_sold 還是 False
```

**結果**：同一張票有**兩筆「媒合成功」的訂單**！這是嚴重問題！

**現實中的緩解因素**

| 緩解因素     | 說明                                        |
| ------------ | ------------------------------------------- |
| 前端 UI 保護 | 點擊「接受」後按鈕會 disable 或顯示 loading |
| 使用情境     | 賣家通常不會同時快速點擊多個「接受」        |
| 業務流程     | 同一張票通常只會有少數幾個買家同時搶        |

---

### 解決方案

#### 方案 1：原子更新（Atomic Update）

**把「檢查」和「更新」合併成一個 SQL 操作**

```python
# ❌ 非原子操作（有 race condition 風險）
cursor.execute("SELECT shipment_status FROM orders WHERE id = %s", (order_id,))
order = cursor.fetchone()
if order["shipment_status"] == "未出貨":
    cursor.execute("UPDATE orders SET shipment_status = '已出貨' WHERE id = %s", (order_id,))

# ✓ 原子更新（把條件寫進 WHERE）
cursor.execute("""
    UPDATE orders
    SET shipment_status = '已出貨', shipped_at = %s
    WHERE id = %s
      AND seller_id = %s
      AND payment_status = '已付款'
      AND shipment_status = '未出貨'
""", (now, order_id, seller_id))

if cursor.rowcount == 0:
    # 條件不符合，查詢具體原因
    ...
```

**原理**：資料庫保證單一 SQL 語句的原子性，WHERE 條件在執行時才檢查，不會有時間差。

#### 方案 2：資料庫鎖（SELECT FOR UPDATE）

```python
# 使用 FOR UPDATE 鎖定資料列，其他 transaction 必須等待
cursor.execute("""
    SELECT * FROM tickets_for_sale
    WHERE id = %s
    FOR UPDATE
""", (ticket_id,))
ticket = cursor.fetchone()

if not ticket["is_sold"]:
    cursor.execute("UPDATE tickets_for_sale SET is_sold = TRUE WHERE id = %s", (ticket_id,))
    cursor.execute("INSERT INTO orders ...")

conn.commit()  # 釋放鎖
```

**注意**：鎖會降低並發效能，應謹慎使用。

---

### 本專案的應用範例

#### 範例：出貨 API 使用原子更新防止重複出貨

```python
# routes/orders.py - mark_shipped_api

# 使用原子更新，防止使用者連擊出貨按鈕
rows_affected = update_order_shipped_atom(cursor, now, order_id, seller_id)

if rows_affected == 0:
    # 更新失敗，查詢具體原因
    order = get_order_by_id(cursor, order_id)
    if order["shipment_status"] == "已出貨":
        raise HTTPException(status_code=400, detail="此訂單已出貨")
    ...
```

```python
# models/order_model.py

def update_order_shipped_atom(cursor, shipped_time, order_id, seller_id) -> int:
    cursor.execute("""
        UPDATE orders
        SET shipment_status='已出貨', shipped_at=%s
        WHERE id=%s
          AND seller_id=%s
          AND payment_status='已付款'
          AND shipment_status='未出貨'  -- 關鍵：只更新「未出貨」的訂單
    """, (shipped_time, order_id, seller_id))

    return cursor.rowcount  # 0 表示沒更新，1 表示成功更新
```

**效果**：

```
時間軸 →

請求 1: [UPDATE ... WHERE shipment_status='未出貨'] → rowcount=1 → 繼續寄信
                                                           ↓
請求 2:                    [UPDATE ... WHERE shipment_status='未出貨'] → rowcount=0 → 回傳錯誤
                                                                              ↑
                                              此時 shipment_status 已經是 '已出貨'，條件不符
```

---

### 信任邊界 + Race Condition 的組合防護

在 `create_order` 函數中，同時處理了兩個問題：

```python
def create_order(ticket_id: int, buyer_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            # 【信任邊界】驗證票券存在且未售出
            cursor.execute("SELECT is_sold, seller_id FROM tickets_for_sale WHERE id = %s", (ticket_id,))
            ticket = cursor.fetchone()
            if not ticket:
                raise HTTPException(status_code=404, detail="找不到票券")
            if ticket["is_sold"]:
                raise HTTPException(status_code=400, detail="此票券已售出")

            # 【信任邊界】驗證買賣雙方不同人
            if ticket["seller_id"] == buyer_id:
                raise HTTPException(status_code=400, detail="不能對自己販售的票發送媒合請求")

            # 【Race Condition 風險說明】
            # - 此處檢查和 INSERT 之間有時間差，多人同時發送媒合請求可能產生多筆「媒合中」訂單
            # - 影響較小：因為「媒合中」只是請求狀態，賣家只會接受其中一筆
            # - 真正決定誰買到票的是「賣家接受媒合」，而非「發送媒合請求」
            cursor.execute("INSERT INTO orders ...")

            conn.commit()
```

---

### Race Condition 防護整理

| 情境         | 解決方案                       | 本專案範例                  |
| ------------ | ------------------------------ | --------------------------- |
| 防止重複操作 | 原子更新（WHERE 加入狀態條件） | `update_order_shipped_atom` |
| 搶購/秒殺    | SELECT FOR UPDATE              | 進階防護方案                |
| 計數器增減   | `UPDATE SET count = count + 1` | -                           |
| 唯一性檢查   | 資料庫 UNIQUE 約束             | -                           |
| 前端防護     | 按鈕 disable、loading 狀態     | 點擊後 disable              |

---

## Python date 物件與 JSON 序列化

### 問題背景

MySQL 的 `DATE` 欄位在 Python 中會被轉換成 `date` 物件：

```python
row["game_date"] = date(2026, 2, 24)  # 不是字串，是 date 物件
```

### 為什麼需要手動轉換？

JSON 只支援基本型別（字串、數字、布林、null、陣列、物件），不支援 Python 的 `date` 物件。

```python
# ❌ date 物件無法直接序列化成 JSON
json.dumps({"game_date": date(2026, 2, 24)})
# TypeError: Object of type date is not JSON serializable

# ✅ 字串可以
json.dumps({"game_date": "2026-02-24"})
```

### 轉換方式

```python
if isinstance(row["game_date"], date):
    row["game_date"] = row["game_date"].strftime("%Y-%m-%d")
    # date(2026, 2, 24) → "2026-02-24"
```

### timedelta 也需要轉換

MySQL 的 `TIME` 欄位會被轉換成 `timedelta`：

```python
row["start_time"] = timedelta(seconds=66900)  # 18:35:00

# 轉換方式
total_seconds = int(row["start_time"].total_seconds())  # 66900
hours = total_seconds // 3600                            # 18
minutes = (total_seconds % 3600) // 60                   # 35
row["start_time"] = f"{hours:02}:{minutes:02}"           # "18:35"
```

---

## MySQL 欄位設計與 NULL 處理

### INSERT 時沒指定欄位會發生什麼？

當 INSERT 語句沒有指定某個欄位時，MySQL 按以下優先順序決定該欄位的值：

| 優先順序 | 條件                         | 結果            |
| -------- | ---------------------------- | --------------- |
| 1        | 有設定 `DEFAULT` 值          | 使用 DEFAULT 值 |
| 2        | 欄位允許 `NULL`              | 填入 `NULL`     |
| 3        | 欄位 `NOT NULL` 且無 DEFAULT | **報錯**        |

**範例**：

```sql
CREATE TABLE orders (
    id INT PRIMARY KEY AUTO_INCREMENT,
    payment_status VARCHAR(20) DEFAULT '未付款',  -- 有 DEFAULT
    paid_at DATETIME NULL,                         -- 允許 NULL，無 DEFAULT
    buyer_id INT NOT NULL                          -- NOT NULL 且無 DEFAULT
);
```

```sql
INSERT INTO orders (buyer_id) VALUES (123);
```

| 欄位             | 結果                       |
| ---------------- | -------------------------- |
| `payment_status` | `'未付款'`（使用 DEFAULT） |
| `paid_at`        | `NULL`（允許 NULL）        |
| `buyer_id`       | `123`（有指定）            |

如果 `buyer_id` 沒指定：

```sql
INSERT INTO orders (payment_status) VALUES ('已付款');
-- Error: Field 'buyer_id' doesn't have a default value
```

---

### 沒有指定 NULL 或 NOT NULL 的預設行為

**MySQL 預設允許 NULL**：

```sql
-- 這兩行效果相同
note TEXT
note TEXT NULL
```

驗證方式：

```sql
DESCRIBE orders;
```

| Field | Type | Null | Key | Default |
| ----- | ---- | ---- | --- | ------- |
| note  | text | YES  |     | NULL    |

`Null` 欄位顯示 `YES`，表示允許 NULL。

---

### NULL 回傳前端為什麼不會報錯？

**JSON 原生支援 null**：

```python
# Python 後端
data = {"paid_at": None}

# FastAPI 回傳的 JSON
{"paid_at": null}
```

`null` 是 JSON 的合法值（與 string、number、boolean、array、object 並列），前端 JavaScript 可以正常接收。

**前端處理 null 的情況**：

```javascript
const data = await res.json();
console.log(data.paid_at); // null，不會報錯

// 正確處理：先檢查再使用
const paidTime = data.paid_at ? formatDateTime(data.paid_at) : "--";
```

**會報錯的情況**：

```javascript
// ❌ 對 null 呼叫方法
data.paid_at.toUpperCase();
// TypeError: Cannot read property 'toUpperCase' of null

// ❌ 對 null 取屬性
data.paid_at.length;
// TypeError: Cannot read property 'length' of null

// ✓ 先檢查再使用
data.paid_at ? data.paid_at.toUpperCase() : "--";
```

**總結**：

| 情況                           | 結果                  |
| ------------------------------ | --------------------- |
| 後端回傳 `null`                | 正常，JSON 支援       |
| 前端接收 `null`                | 正常，JavaScript 支援 |
| 前端對 `null` 呼叫方法或取屬性 | **報錯**              |
| 前端先檢查 `null` 再操作       | 正常                  |

---

### 資料庫欄位設計原則

#### 原則 1：決定欄位是否允許 NULL

| 情境         | 設計        | 範例                    |
| ------------ | ----------- | ----------------------- |
| 必填欄位     | `NOT NULL`  | `buyer_id INT NOT NULL` |
| 選填欄位     | 允許 `NULL` | `note TEXT NULL`        |
| 未來才會有值 | 允許 `NULL` | `paid_at DATETIME NULL` |

#### 原則 2：狀態欄位給 DEFAULT 值

**為什麼狀態欄位建議給 DEFAULT？ ( 本處以「媒合中」舉例, 但本專案當初設計時疏忽沒把 status 設為 NOT NULL DEFAULT '媒合中', 必須記得靠程式碼手動插入status )**

**原因 1：業務邏輯上，新資料一定有初始狀態**

```sql
-- 訂單的生命週期
媒合中 → 媒合成功 → 已付款 → 已出貨

-- 新訂單一定是從「媒合中」開始，不可能是 NULL
```

**原因 2：減少程式碼重複，避免人為疏忽**

```python
# ❌ 沒有 DEFAULT：每次 INSERT 都要手動寫
cursor.execute("""
    INSERT INTO orders (ticket_id, buyer_id, status, payment_status, shipment_status)
    VALUES (%s, %s, '媒合中', '未付款', '未出貨')
""", (ticket_id, buyer_id))
# 如果某次忘記寫，就會是 NULL，造成 bug

# ✓ 有 DEFAULT：只需指定必要欄位
cursor.execute("""
    INSERT INTO orders (ticket_id, buyer_id)
    VALUES (%s, %s)
""", (ticket_id, buyer_id))
# status、payment_status、shipment_status 自動填入 DEFAULT 值
```

**原因 3：確保資料一致性**

```sql
-- 有 DEFAULT + NOT NULL：狀態欄位永遠有值
status VARCHAR(20) NOT NULL DEFAULT '媒合中'

-- 不可能出現 NULL
SELECT * FROM orders WHERE status IS NULL;  -- 永遠是 0 筆
```

**原因 4：方便維護**

```python
# 如果初始狀態要改名（例如「媒合中」改成「待確認」）

# ❌ 沒有 DEFAULT：要找出所有 INSERT 語句逐一修改

# ✓ 有 DEFAULT：只需改資料庫一處
# ALTER TABLE orders ALTER COLUMN status SET DEFAULT '待確認';
```

#### 原則 3：NOT NULL + 無 DEFAULT = INSERT 時必填

```sql
-- 這些欄位 INSERT 時必須指定，否則報錯
ticket_id INT NOT NULL,
buyer_id INT NOT NULL,
seller_id INT NOT NULL
```

---

### 完整設計範例

```sql
CREATE TABLE orders (
    id INT PRIMARY KEY AUTO_INCREMENT,

    -- 必填欄位（INSERT 時必須指定，否則報錯）
    ticket_id INT NOT NULL,
    buyer_id INT NOT NULL,
    seller_id INT NOT NULL,

    -- 狀態欄位（有 DEFAULT，INSERT 可不指定）
    status VARCHAR(20) NOT NULL DEFAULT '媒合中',
    payment_status VARCHAR(20) NOT NULL DEFAULT '未付款',
    shipment_status VARCHAR(20) NOT NULL DEFAULT '未出貨',

    -- 時間欄位（NULL 表示事件尚未發生）
    match_requested_at DATETIME NOT NULL,   -- 必填：訂單建立時一定有
    paid_at DATETIME NULL,                   -- 付款後才填入
    shipped_at DATETIME NULL,                -- 出貨後才填入

    -- 建立時間（自動填入當前時間）
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 選填欄位
    note TEXT NULL
);
```

**對應的程式碼**：

```python
# 後端 INSERT（只需指定必要欄位）
cursor.execute("""
    INSERT INTO orders (ticket_id, buyer_id, seller_id, match_requested_at)
    VALUES (%s, %s, %s, %s)
""", (ticket_id, buyer_id, seller_id, utc_now()))
# status = '媒合中'（DEFAULT）
# payment_status = '未付款'（DEFAULT）
# paid_at = NULL（允許 NULL）
```

```javascript
// 前端處理 null 欄位
const paidTime = data.paid_at ? formatDateTime(data.paid_at) : "--";
const note = data.note || "無備註"; // null 或空字串都顯示「無備註」
```

---

### 設計決策整理

| 欄位類型         | 設計建議                             | 範例                                                     |
| ---------------- | ------------------------------------ | -------------------------------------------------------- |
| 外鍵 / ID        | `NOT NULL`                           | `buyer_id INT NOT NULL`                                  |
| 狀態欄位         | `NOT NULL DEFAULT '初始狀態'`        | `status VARCHAR(20) NOT NULL DEFAULT '媒合中'`           |
| 建立時間         | `NOT NULL DEFAULT CURRENT_TIMESTAMP` | `created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| 未來才發生的時間 | `NULL`                               | `paid_at DATETIME NULL`                                  |
| 選填文字         | `NULL` 或 `DEFAULT ''`               | `note TEXT NULL`                                         |
| 選填數值         | `NULL` 或 `DEFAULT 0`                | `discount INT NULL`                                      |

---

## 資料庫回傳值的型別轉換

### 為什麼需要手動轉換？

資料庫回傳的某些型別無法直接 JSON 序列化，或轉換後的格式不符合前端需求。

### 常見情況與處理方式

#### 1. Decimal → float

| 情況   | 資料庫回傳值     | 問題                            | 處理方式     |
| ------ | ---------------- | ------------------------------- | ------------ |
| 有評分 | `Decimal('4.5')` | Decimal 無法直接 JSON 序列化    | 轉成 `float` |
| 無評分 | `None`           | 維持 `None`（JSON 中是 `null`） | 不處理       |

```python
# 處理方式
row["rating"] = float(row["rating"]) if row["rating"] is not None else None
```

**補充說明**：

- FastAPI 內部會使用 `jsonable_encoder` 自動把 `Decimal` 轉成 `float`
- 但手動轉換的好處：程式碼意圖明確、不依賴框架隱性行為、換框架時不會出錯

#### 2. JSON 字串 → list

| 情況   | 資料庫回傳值                 | 問題                       | 處理方式    |
| ------ | ---------------------------- | -------------------------- | ----------- |
| 有圖片 | `'["url1", "url2"]'`（字串） | 前端收到字串，無法直接使用 | 轉成 `list` |
| 無圖片 | `None` 或 `""`               | 前端需要空陣列             | 轉成 `[]`   |

```python
# 處理方式
row["image_urls"] = json.loads(row["image_urls"]) if row["image_urls"] else []
```

**為什麼資料庫存 JSON 字串？**

- MySQL 的 `TEXT` 或 `VARCHAR` 欄位存的是字串
- 即使用 `JSON` 型別，Python mysql-connector 回傳的仍是字串
- 必須用 `json.loads()` 解析成 Python list

#### 3. None → 空字串

| 情況   | 資料庫回傳值 | 問題                  | 處理方式  |
| ------ | ------------ | --------------------- | --------- |
| 有備註 | `"請面交"`   | 正常                  | 不處理    |
| 無備註 | `None`       | 前端需額外處理 `null` | 轉成 `""` |

```python
# 處理方式
row["note"] = row["note"] if row["note"] else ""
```

**這行是必要的嗎？**

- 非必要，但建議保留
- 好處：前端不用寫 `data.note || ""`，程式碼更簡潔
- 後端統一處理，所有前端（Web、App）都受益

### 完整處理範例

```python
for row in rows:
    # 1. Decimal → float（評分）
    row["rating"] = float(row["rating"]) if row["rating"] is not None else None

    # 2. JSON 字串 → list（圖片）
    row["image_urls"] = json.loads(row["image_urls"]) if row["image_urls"] else []

    # 3. None → 空字串（備註）
    row["note"] = row["note"] if row["note"] else ""
```

### 設計原則

| 原則             | 說明                                   |
| ---------------- | -------------------------------------- |
| 後端負責型別轉換 | API 回傳正確型別，任何前端都能直接使用 |
| 前端做防禦性處理 | 萬一後端出錯，前端也能處理             |
| 明確優於隱性     | 手動轉換比依賴框架自動轉換更可靠       |

---

## 靜態頁面路由機制

### 頁面路由 vs API 路由

| 類型     | 範例             | 回傳內容  | 用途                       |
| -------- | ---------------- | --------- | -------------------------- |
| 頁面路由 | `GET /buy`       | HTML 檔案 | 給瀏覽器渲染成網頁         |
| API 路由 | `GET /api/games` | JSON      | 給 JavaScript fetch() 使用 |

### Router 與 App 的關係

```
┌─────────────────────────────────────────────────────────────────────┐
│                    啟動時的載入流程                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. uvicorn app:app 啟動                                            │
│                                                                     │
│  2. 執行 app.py                                                     │
│     from routes import pages  ← 載入 pages.py                       │
│                      │                                              │
│                      ▼                                              │
│     pages.py 被執行：                                                │
│     • router = APIRouter()  ← 建立路由收集器                         │
│     • @router.get("/") ...  ← 把路由「登記」到 router                │
│     • @router.get("/buy") ...                                       │
│                                                                     │
│  3. app.include_router(pages.router)                                │
│     把 pages.router 裡登記的所有路由「複製」到 app 上                 │
│                                                                     │
│  4. app 的路由表變成：                                               │
│     ┌─────────────────────────────────────────────────┐             │
│     │ GET /           → pages.index()                 │             │
│     │ GET /buy        → pages.buy_page()              │             │
│     │ GET /sell       → pages.sell()                  │             │
│     │ GET /api/games  → games.get_games() ← 其他路由  │             │
│     └─────────────────────────────────────────────────┘             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 請求處理流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    請求時的處理流程                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. 使用者在網址列輸入 https://example.com/buy                       │
│                                                                     │
│  2. 瀏覽器發送 GET /buy                                             │
│                                                                     │
│  3. uvicorn 收到請求，交給 app                                       │
│                                                                     │
│  4. app 查路由表：GET /buy → buy_page()                             │
│                                                                     │
│  5. 執行 buy_page()：                                                │
│     return FileResponse("./static/buy.html", ...)                   │
│                                                                     │
│  6. FastAPI 讀取 buy.html 檔案內容                                  │
│                                                                     │
│  7. 回傳 HTML 給瀏覽器                                               │
│                                                                     │
│  8. 瀏覽器渲染成網頁顯示給使用者                                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 為什麼 Router 必須併入 App？

```
uvicorn app:app
       │
       └── 意思是：去 app.py 找 app 變數，執行它
```

**伺服器只認識 app，不認識 router。** 如果 router 沒有用 `app.include_router()` 併入 app，這些路由就不會被執行。

### async vs 普通函數

| 寫法        | 適合場景                                      |
| ----------- | --------------------------------------------- |
| `async def` | 有 I/O 操作（讀檔案、查資料庫、呼叫外部 API） |
| `def`       | 純運算、沒有等待的操作                        |

```python
# 兩種都能運作
async def index():           # ← 非同步函數（建議）
    return FileResponse(...)

def index():                 # ← 普通函數（也可以）
    return FileResponse(...)
```

**建議**：統一用 `async`，因為 FastAPI 官方推薦，且 FileResponse 內部會讀取檔案（I/O 操作）。

### 檔案路徑說明

```python
FileResponse("./static/index.html", media_type="text/html")
             │
             └── 相對路徑，相對於執行 uvicorn 的工作目錄
```

| 路徑部分      | 說明                               |
| ------------- | ---------------------------------- |
| `.`           | 執行指令時的工作目錄（專案根目錄） |
| `/static`     | static 資料夾                      |
| `/index.html` | 目標檔案                           |

**注意**：必須從專案根目錄執行 `uvicorn app:app`，否則路徑會出錯。

---

## JWT 身份驗證機制

### JWT 是什麼？

JWT（JSON Web Token）是一種**無狀態**的身份驗證機制。伺服器不需要在資料庫或 Session 中儲存登入狀態，只需要驗證 Token 的簽名即可確認使用者身份。

### JWT 的組成結構

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTIzLCJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJuYW1lIjoiVG9tIiwiZXhwIjoxNzY5OTEzOTMwfQ.abc123signature
│                                      │                                                                                                      │
└──────── Header ──────────────────────┴──────────────────────────────────── Payload ──────────────────────────────────────────────────────────┴─── Signature ───
```

| 部分          | 內容                                       | 說明                 |
| ------------- | ------------------------------------------ | -------------------- |
| **Header**    | `{"alg": "HS256", "typ": "JWT"}`           | 演算法和類型         |
| **Payload**   | `{"id": 123, "email": "...", "exp": ...}`  | 使用者資料和過期時間 |
| **Signature** | `HMACSHA256(header + payload, SECRET_KEY)` | 用密鑰簽名，防止竄改 |

### 為什麼使用 JWT？

| 特性         | 說明                                       |
| ------------ | ------------------------------------------ |
| **無狀態**   | 伺服器不需儲存 Session，適合分散式系統     |
| **自包含**   | Token 本身包含所有必要資訊，不需查詢資料庫 |
| **跨域友好** | 可以輕鬆在不同服務間傳遞                   |
| **可驗證**   | 簽名機制確保資料未被竄改                   |

### JWT vs Session 比較

| 項目     | JWT                    | Session                   |
| -------- | ---------------------- | ------------------------- |
| 狀態儲存 | 客戶端（Token）        | 伺服器端（記憶體/資料庫） |
| 擴展性   | 高（無狀態）           | 低（需共享 Session）      |
| 安全性   | 需防止 Token 洩漏      | 需防止 Session 劫持       |
| 登出機制 | 較複雜（需維護黑名單） | 簡單（刪除 Session）      |

---

### JWT Token 生成與驗證程式碼解析

#### 生成 Token

```python
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    # 1. 複製 payload（避免修改原始資料）
    to_encode = data.copy()  # {"id": 123, "email": "...", "name": "Tom"}

    # 2. 計算過期時間
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})

    # 3. 簽名生成 JWT
    #    jwt.encode(payload, 密鑰, 演算法) → JWT 字串
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt  # "eyJhbGciOi..."
```

#### 驗證 Token

```python
def verify_token(token: str) -> Dict[str, Any]:
    try:
        # 1. 解碼 JWT（同時驗證簽名和過期時間）
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # 2. 取出使用者資訊
        user_id = payload.get("id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token payload invalid")

        return {"user_id": user_id, "name": payload.get("name"), "email": payload.get("email")}

    except jwt.ExpiredSignatureError:
        # PyJWT 自動檢查 exp 欄位
        raise HTTPException(status_code=401, detail="Token 已過期")

    except jwt.PyJWTError:
        # 簽名錯誤、格式錯誤等
        raise HTTPException(status_code=401, detail="無效的 token")
```

---

### FastAPI 依賴注入：Header()

```python
def get_current_user(authorization: str = Header(None)) -> Dict[str, Any]:
```

```
def get_current_user(authorization: str = Header(None)) -> Dict[str, Any]:
                                │     │           │
                                │     │           └── Header(None)：告訴 FastAPI「從 HTTP Header 取值」
                                │     │                             如果沒有這個 Header，回傳 None
                                │     │
                                │     └── str：期望的型別
                                │
                                └── authorization：參數名稱，FastAPI 會自動對應到 HTTP Header 的 "Authorization"

```

**運作原理**：

```

HTTP Request
┌─────────────────────────────────────────┐
│ GET /api/orders HTTP/1.1                │
│ Host: example.com                       │
│ Authorization: Bearer eyJhbGciOi...     │ ← FastAPI 自動取出這個值
│ Content-Type: application/json          │
└─────────────────────────────────────────┘
                │
                ▼
        FastAPI 依賴注入系統
                │
                │ 參數名稱 "authorization"
                │ 對應到 Header "Authorization"（不區分大小寫）
                ▼
   authorization = "Bearer eyJhbGciOi..."

```

| 語法           | 說明                                        |
| -------------- | ------------------------------------------- |
| `Header(None)` | 從 HTTP Header 取值，若不存在則回傳 None    |
| `Header(...)`  | 從 HTTP Header 取值，若不存在則報錯（必填） |
| `Query(None)`  | 從 URL Query String 取值                    |
| `Body(...)`    | 從 Request Body 取值                        |

---

### JWT 安全性注意事項

| 項目           | 建議                                                               |
| -------------- | ------------------------------------------------------------------ |
| **SECRET_KEY** | 使用強密鑰（至少 256 bits），存放在環境變數                        |
| **過期時間**   | 設定合理的 exp                                                     |
| **HTTPS**      | 生產環境必須使用 HTTPS，防止 Token 被攔截                          |
| **敏感資料**   | 不要在 Payload 放密碼、信用卡號等敏感資訊                          |
| **Token 儲存** | 前端使用 localStorage 或 httpOnly Cookie (本專案使用 localStorage) |

---

## 單元測試設計原則

### AAA 模式（Arrange-Act-Assert）

```python
def test_verify_password_correct(self, sample_password):
    # Arrange（準備）- 準備測試需要的資料
    hashed = hash_password(sample_password)

    # Act（執行）- 呼叫要被測試的函數
    result = verify_password(sample_password, hashed)

    # Assert（驗證）- 檢查結果是否符合預期
    assert result is True
```

### 測試類型

| 類型         | 說明                       | 範例                     |
| ------------ | -------------------------- | ------------------------ |
| **正向測試** | 測試正常情況是否能成功     | 正確密碼應該驗證通過     |
| **負向測試** | 測試錯誤情況是否被正確拒絕 | 錯誤密碼應該驗證失敗     |
| **邊界測試** | 測試極端或邊界情況         | 空字串、None、過期 Token |

### pytest.raises 用法

用來測試「預期會拋出例外」的情況：

```python
def test_verify_invalid_token_raises_error(self):
    invalid_token = "this.is.not.valid"

    # with pytest.raises 捕捉例外
    with pytest.raises(HTTPException) as exc_info:
        verify_token(invalid_token)  # 這行應該拋出 HTTPException

    # exc_info.value 是捕捉到的例外物件
    assert exc_info.value.status_code == 401
    assert "無效" in exc_info.value.detail
```

### 測試「在哪裡被擋住」

當多個函數都可能拋出相同錯誤時，檢查錯誤訊息可以確認錯誤發生在正確的位置：

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           get_current_user 的兩道防線                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  def get_current_user(authorization):                                           │
│      │                                                                          │
│      │  第一道防線：檢查 Header 格式                                             │
│      ├── if authorization is None:                                              │
│      │       raise 401 "Missing..."  ← 測試 2 應該在這裡被擋住                  │
│      │                                                                          │
│      │  第二道防線：驗證 Token                                                   │
│      └── return verify_token(token)                                             │
│              │                                                                  │
│              └── raise 401 "無效的 token"  ← 測試 4 在這裡被擋住也 OK            │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

| 測試   | 傳入值      | 測試目的              | 是否檢查錯誤訊息 |
| ------ | ----------- | --------------------- | ---------------- |
| 測試 2 | `None`      | 確認第一道防線有作用  | ✓ 檢查 "Missing" |
| 測試 4 | `"Bearer "` | 確認空 token 會被拒絕 | ✗ 只檢查 401     |

### Fixture 的使用

Fixture 是 pytest 提供的「可重用測試資料」機制：

```python
# conftest.py
@pytest.fixture
def sample_password():
    return "TestPassword123"

@pytest.fixture
def sample_user_data():
    return {"id": 1, "email": "test@example.com", "name": "Test User"}

# test_auth_utils.py
def test_hash_password(self, sample_password):  # ← 自動注入 fixture
    result = hash_password(sample_password)
    assert result != sample_password
```

### JWT 相關測試重點

| 測試重點                | 為什麼重要                      |
| ----------------------- | ------------------------------- |
| **密碼有被加密**        | 確保不會把明碼存入資料庫        |
| **每次加密結果不同**    | 確保有使用 salt（防彩虹表攻擊） |
| **正確密碼通過驗證**    | 確保使用者能正常登入            |
| **錯誤密碼被拒絕**      | 確保不會讓任何密碼都通過        |
| **Token 包含正確資料**  | 確保使用者身份資訊正確          |
| **過期 Token 被拒絕**   | 確保過期機制有作用              |
| **被竄改 Token 被拒絕** | 確保簽名驗證有作用（安全性）    |

### 安全測試：被竄改的 Token

```python
def test_verify_tampered_token_raises_error(self, sample_user_data):
    # 建立有效 token
    token = create_access_token(data=sample_user_data)

    # 竄改 token（修改最後 5 個字元）
    tampered_token = token[:-5] + "XXXXX"

    # 被竄改的 token 應該被拒絕
    with pytest.raises(HTTPException) as exc_info:
        verify_token(tampered_token)

    assert exc_info.value.status_code == 401
```

**原理**：JWT 的 Signature 是用 SECRET_KEY 對 Header + Payload 簽名。如果內容被竄改，重新計算的 Signature 會與原本不同，`jwt.decode()` 會拋出錯誤。

---

## AWS S3 + CloudFront 機制

### 架構概述

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              S3 + CloudFront 架構                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  使用者上傳票券圖片                                                              │
│        │                                                                        │
│        ▼                                                                        │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐                      │
│  │   FastAPI   │ ──── │   AWS S3    │ ──── │ CloudFront  │                      │
│  │  (EC2 上)   │      │  (儲存圖片)  │      │   (CDN)     │                      │
│  └─────────────┘      └─────────────┘      └─────────────┘                      │
│        │                                          │                             │
│        │                                          │                             │
│        ▼                                          ▼                             │
│  回傳 CloudFront URL              使用者瀏覽器請求圖片時                         │
│  給前端顯示                        從最近的節點快速取得                           │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### CloudFront URL 存在時機

**CLOUDFRONT_URL 是「部署時就已存在」，不是「上傳時動態產生」。**

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              時間線                                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  【部署階段】在 AWS Console 設定（只做一次）                                      │
│       │                                                                         │
│       ├── 1. 建立 S3 Bucket                                                     │
│       │                                                                         │
│       ├── 2. 建立 CloudFront Distribution，指向這個 S3 Bucket                    │
│       │       │                                                                 │
│       │       └── AWS 分配一個固定 Domain：d1234abcd.cloudfront.net             │
│       │           （這個 Domain 從此刻起就已存在，不會改變）                      │
│       │                                                                         │
│       └── 3. 把這個 Domain 設定到環境變數：CLOUDFRONT_URL                        │
│                                                                                 │
│  ════════════════════════════════════════════════════════════════════════════   │
│                                                                                 │
│  【執行階段】使用者上傳檔案（每次上傳都會執行）                                    │
│       │                                                                         │
│       ├── s3_client.put_object() → 檔案進入 S3                                  │
│       │                                                                         │
│       └── 組裝 URL：CLOUDFRONT_URL + "/tickets/" + file_name                    │
│           │                                                                     │
│           └── CLOUDFRONT_URL 早就存在，這裡只是「使用」它來組裝完整路徑           │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 一個 CloudFront Distribution = 一個固定 URL

所有上傳到這個 S3 Bucket 的檔案，都共用同一個 `CLOUDFRONT_URL`，只是**路徑**不同：

```
https://d1234abcd.cloudfront.net/tickets/image001.jpg
https://d1234abcd.cloudfront.net/tickets/image002.jpg
https://d1234abcd.cloudfront.net/tickets/image003.jpg
│                              │
└── 同一個 CLOUDFRONT_URL ─────┴── 不同的檔案路徑
```

### 「先上傳再組裝」的商業邏輯設計

```python
# 程式碼順序
s3_client.put_object(...)                              # 1. 先上傳
cloudfront_url = f"{CLOUDFRONT_URL}/tickets/{file_name}"  # 2. 再組裝 URL
```

**為什麼這樣設計？**

| 順序       | 原因                          |
| ---------- | ----------------------------- |
| 先上傳     | 確保檔案**確實存在**於 S3     |
| 再組裝 URL | 確保這個 URL **有東西可存取** |

**如果順序反過來會怎樣？（技術上可行，但商業邏輯不合理）**

```
情境：先組裝 URL，再上傳（但上傳失敗了）

1. cloudfront_url = f"{CLOUDFRONT_URL}/tickets/{file_name}"  ← 組裝成功
2. s3_client.put_object(...)  ← 上傳失敗！

結果：
- 你有一個「看起來正確」的 URL
- 但這個 URL 指向一個「不存在的檔案」
- 使用者點擊 → 404 Not Found
```

### 簡單比喻

```
CLOUDFRONT_URL 就像「大樓地址」
檔案路徑就像「房間號碼」
上傳檔案就像「把東西放進房間」

┌─────────────────────────────────────────────────────────┐
│                                                         │
│  大樓地址（CLOUDFRONT_URL）                              │
│  └── 蓋好大樓時就有了，永遠不變                          │
│      https://d1234abcd.cloudfront.net                   │
│                                                         │
│  房間號碼（檔案路徑）                                    │
│  └── 每次上傳時決定                                      │
│      /tickets/image001.jpg                              │
│                                                         │
│  放東西進房間（put_object）                              │
│  └── 必須先放進去，別人才能來拿                          │
│                                                         │
│  完整地址 = 大樓地址 + 房間號碼                          │
│  https://d1234abcd.cloudfront.net/tickets/image001.jpg  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 常見誤解澄清

| 誤解                               | 正確理解                                                       |
| ---------------------------------- | -------------------------------------------------------------- |
| 上傳成功後才「產生」CLOUDFRONT_URL | ✗ 錯誤。CLOUDFRONT_URL 在設定 CloudFront 時就已存在            |
| 每個檔案有不同的 CLOUDFRONT_URL    | ✗ 錯誤。所有檔案共用同一個，只是路徑不同                       |
| 先組裝 URL 再上傳也可以            | △ 技術上可行，但商業邏輯不合理（可能產生指向不存在檔案的 URL） |

### 完整上傳流程

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           S3 上傳完整流程                                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. 使用者在前端選擇圖片                                                         │
│       │                                                                         │
│       ▼                                                                         │
│  2. POST /api/sell_tickets（包含圖片檔案）                                       │
│       │                                                                         │
│       ▼                                                                         │
│  3. FastAPI 驗證檔案（副檔名、大小等）                                           │
│       │                                                                         │
│       ▼                                                                         │
│  4. 呼叫 upload_file_to_s3()                                                    │
│       │                                                                         │
│       ├── s3_client.put_object()  ← 上傳到 S3（此時才建立網路連線）              │
│       │       │                                                                 │
│       │       └── 成功：檔案存入 S3 Bucket                                      │
│       │                                                                         │
│       └── 組裝 CloudFront URL                                                   │
│           │                                                                     │
│           └── f"{CLOUDFRONT_URL}/tickets/{file_name}"                           │
│               （使用早就存在的 CLOUDFRONT_URL + 這次的檔名）                      │
│       │                                                                         │
│       ▼                                                                         │
│  5. 回傳 CloudFront URL 給 API                                                  │
│       │                                                                         │
│       ▼                                                                         │
│  6. 將 URL 存入資料庫（tickets_for_sale.image_url）                             │
│       │                                                                         │
│       ▼                                                                         │
│  7. 前端顯示圖片時，使用這個 CloudFront URL                                      │
│       │                                                                         │
│       └── 使用者瀏覽器 → CloudFront CDN → S3 → 取得圖片                         │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### MIME 類型的作用

```
上傳時
    │
    │  s3_client.put_object(ContentType="image/jpeg")
    ▼
S3 儲存 metadata
    │
    │  記住「這個檔案的 Content-Type 是 image/jpeg」
    ▼
使用者請求圖片
    │
    │  GET https://cloudfront.../tickets/image123.jpg
    ▼
S3/CloudFront 回傳
    │
    │  HTTP Response Header: Content-Type: image/jpeg
    ▼
瀏覽器知道這是圖片
    │
    └── 直接顯示（而不是下載）
```

---

## Singleton Pattern：兩種實作方式

### Eager Singleton（急切初始化）

```python
# s3_utils.py 的寫法
s3_client = boto3.client("s3", ...)  # import 時就建立
```

**特點**：

- 程式碼簡單（一行）
- import 時就建立，不管有沒有用到
- 適合：幾乎一定會用到的服務

### Lazy Singleton（延遲初始化）

```python
# sqs_utils.py 的寫法
_sqs_client = None  # import 時只宣告

def get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client('sqs', ...)
    return _sqs_client
```

**特點**：

- 程式碼較複雜（需要函數 + global）
- 第一次使用時才建立
- 適合：可能不會用到的服務

### 比較

| 項目         | Eager（S3） | Lazy（SQS）        |
| ------------ | ----------- | ------------------ |
| 建立時機     | import 時   | 第一次呼叫時       |
| 程式碼複雜度 | 低          | 高                 |
| 沒用到時     | 還是會建立  | 不會建立           |
| 適合場景     | 核心功能    | 有 fallback 的功能 |

**兩者都是 Singleton**：模組層級變數在整個程式期間只有一個實例。

### 為什麼 Python 模組變數是 Singleton？

```python
# 第一次 import s3_utils
import s3_utils  # Python 執行模組，建立 s3_client

# 第二次 import s3_utils
import s3_utils  # Python 發現已經 import 過，不會重新執行
                 # 直接使用之前的 s3_client

# 結論：模組層級變數天生就是 Singleton
```

---

## Redis 快取機制完整解析

### 核心觀念總覽

| 名詞                 | 是什麼                     | 什麼時候建立                  | 是 Singleton 嗎                    |
| -------------------- | -------------------------- | ----------------------------- | ---------------------------------- |
| **連線池物件**       | 管理多條連線的容器         | import 時                     | ✓ 是（模組層級變數 `REDIS_POOL`）  |
| **Redis 客戶端物件** | 執行操作的介面（get、set） | 每次呼叫 `get_redis_client()` | ✗ 不是（每次都建立新的，但很輕量） |
| **網路連線**         | 與 Redis 伺服器的 TCP 連線 | 第一次執行操作時              | 由連線池管理                       |

---

### 關鍵觀念釐清

#### 觀念 1：建立「物件」≠ 建立「連線」

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           物件 vs 連線                                           │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  redis.ConnectionPool(...)                                                      │
│       │                                                                         │
│       └── 建立「連線池物件」 ✓                                                  │
│           建立「網路連線」 ✗  ← 池是空的，沒有任何連線！                         │
│                                                                                 │
│  redis.Redis(connection_pool=REDIS_POOL)                                        │
│       │                                                                         │
│       └── 建立「客戶端物件」 ✓                                                  │
│           建立「網路連線」 ✗  ← 還是沒有連線！                                  │
│                                                                                 │
│  redis_client.get("key")                                                        │
│       │                                                                         │
│       └── 建立「網路連線」 ✓  ← 這時才真正連線！                                │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### 觀念 2：max_connections=10 是「上限」，不是「初始數量」

```
max_connections=10 的意思：

✗ 錯誤理解：一開始就建立 10 條連線放著
✓ 正確理解：最多只能有 10 條連線，按需建立
```

| 情況                       | 池中連線數 | 發生什麼             |
| -------------------------- | ---------- | -------------------- |
| 第一次請求                 | 0 → 1      | 建立 1 條            |
| 第二次請求（前一個已歸還） | 1          | 取出使用，不建立     |
| 同時 3 個請求              | 1 → 3      | 不夠用，建立到 3 條  |
| 同時 15 個請求             | 3 → 10     | 最多 10 條，其餘等待 |

#### 觀念 3：「歸還」≠「關閉」

```
使用完連線後：

✗ 錯誤理解：連線關閉，下次要重新建立
✓ 正確理解：連線放回池中保持存活，下次直接取出使用
```

連線的生命週期：

- **建立**：第一次需要時
- **使用**：執行 Redis 操作
- **歸還**：放回池中（保持 TCP 連線）
- **關閉**：應用程式結束時

---

### 完整流程圖：第一次 vs 之後的請求

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    【應用程式啟動】import redis_utils                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. 載入環境變數                                                                 │
│     REDIS_HOST, REDIS_PORT, REDIS_PASSWORD                                      │
│                                                                                 │
│  2. 建立連線池物件（模組層級變數，Singleton）                                    │
│     REDIS_POOL = redis.ConnectionPool(...)                                      │
│                                                                                 │
│     此時的狀態：                                                                 │
│     ┌─────────────────────┐                                                     │
│     │     REDIS_POOL      │                                                     │
│     │  ┌───────────────┐  │                                                     │
│     │  │   （空的）     │  │  ← 沒有任何連線                                    │
│     │  └───────────────┘  │                                                     │
│     └─────────────────────┘                                                     │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                    【第一次請求】GET /api/top_games                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. API 呼叫 get_redis_client()                                                 │
│     └── 建立 Redis 客戶端物件（輕量，每次都建立新的）                            │
│         redis_client = redis.Redis(connection_pool=REDIS_POOL)                  │
│                                                                                 │
│     此時：還沒有網路連線！                                                       │
│                                                                                 │
│  2. API 執行 redis_client.get("top_games:2025-07")                              │
│     │                                                                           │
│     ├── 連線池檢查：池中有閒置連線嗎？                                          │
│     │   └── 沒有（池是空的）                                                    │
│     │                                                                           │
│     ├── 建立網路連線 #1（TCP 連線到 Redis 伺服器）                              │
│     │                                                                           │
│     ├── 使用連線 #1 執行 GET 操作                                               │
│     │                                                                           │
│     └── 操作完成，連線 #1 歸還到池中                                            │
│                                                                                 │
│     此時的狀態：                                                                 │
│     ┌─────────────────────┐                                                     │
│     │     REDIS_POOL      │                                                     │
│     │  ┌───────────────┐  │                                                     │
│     │  │  連線 #1 ●    │  │  ← 1 條連線，閒置中，保持 TCP 連線                 │
│     │  └───────────────┘  │                                                     │
│     └─────────────────────┘                                                     │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                    【第二次請求】GET /api/top_games                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. API 呼叫 get_redis_client()                                                 │
│     └── 建立新的 Redis 客戶端物件（很輕量，無所謂）                              │
│                                                                                 │
│  2. API 執行 redis_client.get("top_games:2025-07")                              │
│     │                                                                           │
│     ├── 連線池檢查：池中有閒置連線嗎？                                          │
│     │   └── 有！連線 #1 正在閒置                                                │
│     │                                                                           │
│     ├── 取出連線 #1（不需要建立新連線！）                                       │
│     │                                                                           │
│     ├── 使用連線 #1 執行 GET 操作                                               │
│     │                                                                           │
│     └── 操作完成，連線 #1 歸還到池中                                            │
│                                                                                 │
│     效能提升：省去了建立 TCP 連線的時間！                                        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                    【高併發情境】同時 3 個請求                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  初始狀態：池中有 1 條閒置連線（#1）                                             │
│                                                                                 │
│  請求 A：redis_client.get("keyA")                                               │
│     └── 取出 #1 → 使用中...                                                     │
│                                                                                 │
│  請求 B：redis_client.get("keyB")（同時發生）                                   │
│     └── #1 正在被 A 用 → 池中沒閒置 → 建立 #2 → 使用中...                       │
│                                                                                 │
│  請求 C：redis_client.get("keyC")（同時發生）                                   │
│     └── #1、#2 都在用 → 建立 #3 → 使用中...                                     │
│                                                                                 │
│  三個請求都完成後的狀態：                                                        │
│  ┌─────────────────────┐                                                        │
│  │     REDIS_POOL      │                                                        │
│  │  ┌───────────────┐  │                                                        │
│  │  │  連線 #1 ●    │  │                                                        │
│  │  │  連線 #2 ●    │  │  ← 3 條連線，全部閒置，等待下次使用                   │
│  │  │  連線 #3 ●    │  │                                                        │
│  │  └───────────────┘  │                                                        │
│  └─────────────────────┘                                                        │
│                                                                                 │
│  之後的請求：從 #1、#2、#3 中取出使用，不需要建立新的                            │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 與 S3、SQS 的比較

#### 三種工具的 Singleton 設計比較

| 項目                     | s3_utils       | sqs_utils          | redis_utils          |
| ------------------------ | -------------- | ------------------ | -------------------- |
| **Singleton 類型**       | Eager          | Lazy               | Eager（連線池）      |
| **Singleton 對象**       | 客戶端物件     | 客戶端物件         | 連線池（不是客戶端） |
| **模組層級變數**         | `s3_client`    | `_sqs_client`      | `REDIS_POOL`         |
| **import 時**            | 建立客戶端物件 | 只宣告 None        | 建立連線池物件       |
| **取得函數**             | 不需要函數     | `get_sqs_client()` | `get_redis_client()` |
| **每次呼叫建立新物件？** | 否             | 否                 | 是（客戶端很輕量）   |
| **連線管理**             | boto3 內部處理 | boto3 內部處理     | 連線池管理           |

#### 為什麼設計不同？

| 工具      | 使用頻率           | 連線特性     | 設計選擇                         |
| --------- | ------------------ | ------------ | -------------------------------- |
| **S3**    | 較低（上傳檔案）   | HTTP 短連線  | Eager：核心功能，一定會用        |
| **SQS**   | 較低（發送訊息）   | HTTP 短連線  | Lazy：有 fallback，可能不用      |
| **Redis** | 很高（每次查快取） | TCP 持久連線 | 連線池：高頻操作需要重複使用連線 |

#### 流程比較圖

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           三種工具的建立時機比較                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  【S3 - Eager Singleton】                                                       │
│                                                                                 │
│  import s3_utils                                                                │
│       └── s3_client = boto3.client("s3", ...) ← 建立客戶端物件                  │
│                                                                                 │
│  s3_client.put_object(...)                                                      │
│       └── 建立網路連線 ← 這時才連線                                             │
│                                                                                 │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                 │
│  【SQS - Lazy Singleton】                                                       │
│                                                                                 │
│  import sqs_utils                                                               │
│       └── _sqs_client = None ← 只宣告，什麼都沒建立                             │
│                                                                                 │
│  第一次 get_sqs_client()                                                        │
│       └── _sqs_client = boto3.client("sqs", ...) ← 建立客戶端物件               │
│                                                                                 │
│  第二次 get_sqs_client()                                                        │
│       └── return _sqs_client ← 直接回傳之前的                                   │
│                                                                                 │
│  sqs.send_message(...)                                                          │
│       └── 建立網路連線 ← 這時才連線                                             │
│                                                                                 │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                 │
│  【Redis - 連線池模式】                                                          │
│                                                                                 │
│  import redis_utils                                                             │
│       └── REDIS_POOL = redis.ConnectionPool(...) ← 建立連線池（空的）           │
│                                                                                 │
│  get_redis_client()                                                             │
│       └── redis.Redis(connection_pool=REDIS_POOL) ← 建立客戶端（每次都新的）    │
│                                                                                 │
│  redis_client.get("key")                                                        │
│       ├── 池是空的 → 建立連線 → 使用 → 歸還                                     │
│       └── 池中有連線 → 取出 → 使用 → 歸還（不建立新連線）                       │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### API 中使用 Redis 的完整流程（以 /api/top_games 為例）

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        /api/top_games 完整流程                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  請求進來：GET /api/top_games                                                   │
│       │                                                                         │
│       ▼                                                                         │
│  ┌─────────────────────────────────────────────┐                                │
│  │  1. 嘗試從 Redis 讀取快取                    │                                │
│  │                                             │                                │
│  │  redis_client = get_redis_client()          │ ← 建立客戶端物件              │
│  │  cached_data = redis_client.get(cache_key)  │ ← 這時才用到連線              │
│  │                                             │                                │
│  │  連線池的動作：                              │                                │
│  │  - 有閒置連線 → 取出使用                     │                                │
│  │  - 沒有連線 → 建立新連線                     │                                │
│  │  - 操作完成 → 歸還到池中                     │                                │
│  └─────────────────────────────────────────────┘                                │
│       │                                                                         │
│       ├── 有快取（HIT）                                                         │
│       │   └── return json.loads(cached_data)                                    │
│       │       直接回傳，結束！                                                   │
│       │                                                                         │
│       └── 沒快取（MISS）或 Redis 錯誤                                           │
│           │                                                                     │
│           ▼                                                                     │
│  ┌─────────────────────────────────────────────┐                                │
│  │  2. 查詢資料庫                               │                                │
│  │                                             │                                │
│  │  top_games = get_top_games()                │                                │
│  └─────────────────────────────────────────────┘                                │
│           │                                                                     │
│           ▼                                                                     │
│  ┌─────────────────────────────────────────────┐                                │
│  │  3. 寫入 Redis 快取                          │                                │
│  │                                             │                                │
│  │  redis_client = get_redis_client()          │ ← 再取一次（保險）             │
│  │  redis_client.setex(cache_key, 86400, data) │ ← 寫入 + 設定 TTL              │
│  │                                             │                                │
│  │  連線池的動作：                              │                                │
│  │  - 可能使用同一條連線，也可能是不同條        │                                │
│  │  - 操作完成 → 歸還到池中                     │                                │
│  └─────────────────────────────────────────────┘                                │
│           │                                                                     │
│           ▼                                                                     │
│  return top_games                                                               │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 錯誤處理策略

| Redis 操作      | 失敗時的處理           | 原因                       |
| --------------- | ---------------------- | -------------------------- |
| GET（讀快取）   | 降級查資料庫，不 raise | 快取是輔助功能，不影響核心 |
| SETEX（寫快取） | 只印 log，不 raise     | 不影響 API 回傳結果        |

```python
# 讀快取失敗：降級到資料庫
try:
    cached_data = redis_client.get(cache_key)
except Exception as e:
    logger.warning(f"Redis GET error: {e}")
    # 不 raise，繼續往下查資料庫

# 寫快取失敗：只印 log
try:
    redis_client.setex(cache_key, 86400, payload)
except Exception as e:
    logger.warning(f"Redis SETEX error: {e}")
    # 不 raise，直接 return 資料庫結果
```

---

### 常見問題

#### Q1：為什麼要用連線池？

**答**：

- 建立 TCP 連線需要時間（三次握手）
- 如果每次操作都建立新連線，效能很差
- 連線池讓連線可以重複使用，省去建立連線的時間

#### Q2：max_connections=10 是什麼意思？

**答**：

- 是**上限**，不是初始數量
- 池中的連線是**按需求建立**的
- 第一次只建立 1 條，同時需要更多時才建立更多
- 達到上限後，新請求要等待其他連線釋放

#### Q3：連線什麼時候關閉？

**答**：

- 使用完**不會**關閉，會歸還到池中
- 連線保持 TCP 連線狀態，等待下次使用
- 只有應用程式結束時，連線才會關閉

#### Q4：redis_utils 是 Singleton 嗎？

**答**：

- **連線池是 Singleton**（模組層級變數 `REDIS_POOL`）
- **客戶端物件不是 Singleton**（每次呼叫都建立新的）
- 客戶端物件很輕量（只是 Python 物件），所以每次建立新的沒關係
- 真正昂貴的是網路連線，由連線池管理重複使用

#### Q5：和 S3、SQS 的 Singleton 有什麼不同？

**答**：

- S3/SQS：**客戶端物件**是 Singleton
- Redis：**連線池**是 Singleton，客戶端物件不是
- 原因：Redis 操作頻率高，需要連線池管理 TCP 持久連線
- S3/SQS 是 HTTP 短連線，boto3 內部已有連線池機制

#### Q6：decode_responses=True 是做什麼的？

**答**：

- Redis 預設回傳 `bytes`（例如 `b'hello'`）
- 設定後自動解碼為 `str`（例如 `'hello'`）
- 好處：不用每次手動 `.decode("utf-8")`，可以直接用 `json.loads()`

---

### 為什麼 Redis 需要連線池，而 S3/SQS 不用？

#### 服務協定設計決定連線特性

| 服務      | 協定                                | 連線特性      | 連線池         |
| --------- | ----------------------------------- | ------------- | -------------- |
| **Redis** | Redis Protocol（RESP），跑在 TCP 上 | 持久連線      | 需要自己管理   |
| **S3**    | HTTP/HTTPS（RESTful API）           | 請求-回應模式 | boto3 內部管理 |
| **SQS**   | HTTP/HTTPS（RESTful API）           | 請求-回應模式 | boto3 內部管理 |

#### Redis：TCP 持久連線

```
TCP 連線建立（三次握手）
    │
    ├── GET key1      → 回應
    ├── SET key2 val  → 回應
    ├── GET key3      → 回應
    ├── ...（可以一直用下去）
    │
TCP 連線關閉（只有明確關閉時）
```

**特點**：

- 連線建立後保持存活，一個連線執行多個命令
- 適合高頻操作（每秒可能幾百次查詢）
- 需要我們自己建立連線池來管理連線

#### S3/SQS：HTTP 請求-回應模式

```
請求 1：PUT /bucket/file.jpg
    └── 建立連線 → 發送請求 → 收到回應 → 連線可能關閉或復用

請求 2：GET /bucket/file.jpg
    └── 建立連線 → 發送請求 → 收到回應 → 連線可能關閉或復用
```

**特點**：

- HTTP/1.1 有 Keep-Alive 機制
- boto3 內部已經管理連線池
- 我們不需要自己處理，直接用客戶端物件即可

#### 簡單比喻

| 類型                         | 比喻                                         |
| ---------------------------- | -------------------------------------------- |
| **Redis（TCP 持久連線）**    | 打電話：撥通後可以一直講，講完再掛           |
| **S3/SQS（HTTP 請求-回應）** | 寄信：每次寄一封，收到回信，下次再寄新的一封 |

#### 結論

| 問題                         | 答案                                     |
| ---------------------------- | ---------------------------------------- |
| 誰決定連線類型？             | 服務本身的協定設計，不是我們選擇         |
| Redis 為什麼要自己建連線池？ | 它是 TCP 持久連線，redis-py 沒有內建管理 |
| S3/SQS 為什麼不用自己建？    | 它們是 HTTP API，boto3 內部已經處理好了  |

---

### 連線歸還時機：每次操作完成就立即歸還

#### 常見誤解

```
✗ 錯誤理解：同一個 API 的多次操作共用同一條連線
✓ 正確理解：每次操作完成後立即歸還，下次操作重新從池中取
```

#### 實際流程

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    /api/top_games 中的連線使用                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  redis_client = get_redis_client()        ← 建立客戶端物件（還沒取連線）         │
│                                                                                 │
│  cached_data = redis_client.get(cache_key)                                      │
│       │                                                                         │
│       ├── 從池中取出連線 #1                                                     │
│       ├── 執行 GET                                                              │
│       └── 歸還連線 #1 到池中              ← 這裡就歸還了！                       │
│                                                                                 │
│  # ... 查資料庫（可能花 50ms）...                                               │
│  # 這段時間連線 #1 是閒置的，其他請求可以用                                      │
│                                                                                 │
│  redis_client.setex(cache_key, 86400, payload)                                  │
│       │                                                                         │
│       ├── 從池中取出連線（可能是 #1，也可能是其他條）                           │
│       ├── 執行 SETEX                                                            │
│       └── 歸還連線到池中                                                        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### 為什麼這樣設計？

| 設計方式                              | 優點                                             | 缺點                                 |
| ------------------------------------- | ------------------------------------------------ | ------------------------------------ |
| **每次操作就歸還**（redis-py 的做法） | 連線不會被單一請求長時間佔用，高併發時連線可共享 | 每次操作都有「取出/歸還」的小開銷    |
| 整個 API 佔用同一條                   | 減少取出/歸還次數                                | 連線被長時間佔用，高併發時可能不夠用 |

**關鍵理解**：「取出/歸還」只是從池中拿物件，**不是建立網路連線**，開銷非常小。

#### 如果想要多個操作共用同一條連線？

使用 **Pipeline**：

```python
# 一般做法：每個操作各自取連線、歸還
redis_client.get("key1")    # 取 → 執行 → 歸還
redis_client.get("key2")    # 取 → 執行 → 歸還
redis_client.get("key3")    # 取 → 執行 → 歸還

# Pipeline：多個操作共用一條連線，一次執行
pipe = redis_client.pipeline()
pipe.get("key1")
pipe.get("key2")
pipe.get("key3")
results = pipe.execute()    # 一次取連線 → 執行全部 → 歸還
```

**Pipeline 好處**：減少網路往返次數（3 次變 1 次）、共用同一條連線。

#### 總結

| 問題                        | 答案                                      |
| --------------------------- | ----------------------------------------- |
| 每次操作完就歸還嗎？        | **是的**，立即歸還                        |
| 同一個 API 用同一條連線嗎？ | **不一定**，可能相同也可能不同            |
| 這樣會影響效能嗎？          | **不會**，取出/歸還只是操作池中物件，很快 |
| 想要共用連線怎麼做？        | 使用 Pipeline                             |

---

## 專案重構問題

### 拆分 Router 層與 Service 層

**現況：**

- Router 和 Service 未分開, 全部寫在 Routes 資料夾中
- 導致 Router 層無法專責處理 HTTP 請求與轉發，而是同時還要處理應由 Service 層處理的商業邏輯

**TODO：**

- [ ] 重構 - 將 Router 層和 Service 層分開

---
