# recsys_offline/ab_test.py
# Step 5：模擬 A/B（真實流量不足 → 反事實模擬）。對照=純人氣、實驗=個人化，比較 CTR。
# 誠實前提：這是模擬，結果是「使用者更愛點命中其偏好的推薦」這個點擊傾向模型的後果 (把 Step 3 量到的相關性優勢轉成 CTR 結論)。
# 有真實流量(且樣本量夠大)時，改用 ctr_report.py 的真實數據。

import math
import random
from datetime import date
from recsys_offline.snapshot_loader import load_snapshot
from services.recommender import recommend, assign_variant, VARIANTS

# recommend: 推薦函數 (線上、離線都用這個)
# assign_variant: 分流函數 (線上真實使用，用 member_id 雜湊)
# VARIANTS: 兩臂參數的字典 (eg. {"personalized": 完整參數, "popularity": 個人權重歸零})

# ── 點擊傾向模型（明確假設，可辯護）──
BASE_CTR = 0.03           # 基線點擊率：即使推薦與偏好完全無關，也有 3% 機率隨手點（模擬世界的背景雜訊，取值落在推薦/廣告類產品常見基線區間）
RELEVANCE_LIFT = 0.15     # 行為假設：推薦命中使用者真實偏好時，點擊率增加量: 點擊率加 15 個百分點(0.03→0.18)，是整個模型唯一的行為假設:相關性驅動點擊。抽成頂層常數、寫在輸出第一行,誠實可調。把這個假設做成參數,結論敘述永遠是『在此假設下』。改它會改效應大小與所需樣本,但分流、檢定、檢定力這套方法不隨假設變——方法才是這支腳本交付的東西
VISITS_PER_USER = 4       # 流量假設：模擬實驗期間每位使用者平均到訪次數（代表實驗長度/累積流量）。控制模擬累積多少曝光,等同「實驗跑多久」。調大它,樣本變多、檢定更容易顯著。
SEED = 7                  # 固定亂數種子：讓模擬「可重現」。任何人重跑都能得到一模一樣的 82/118、z=2.96。


# 之後算 p 值時，要查「超過 |z| 的機率」(右側)：先用 _phi(x)算出左側安全區 0.975，再用 1-_phi(abs(z))算出右側值 超過 |z| 的機率)
def _phi(x):             
    """
    標準常態分布的累積分布函數 (CDF)。
    功能：計算標準常態隨機變數 ≤ x 的「左側累積機率」（即曲線下方的左側總面積）
    範例:  Φ(1.96)≈0.975: _phi(1.96) ≈ 0.975 (代表有 97.5% 的機率數值會小於等於 1.96)。
    
    備註：
    1. 本函式回傳的是「累積機率」而非 p 值，後續需透過 `2 * (1 - _phi(|z|))` 翻轉算得雙尾 p 值。
    2. 效果等同 scipy.stats.norm.cdf(x)，利用數學恆等式與內建 math.erf 實作，達成零第三方庫依賴。

    注意：
    _phi 本身只算「≤ x 的左側機率」，但之後算 p 值時要查的是「超過 |z| 的外側機率」。因此後續代碼會用 1 - _phi(abs(z)) 來翻轉求得外側尾巴。
    """
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))



def simulate():
    # 載入凍結快照(events / games / favorites / meta)
    snap = load_snapshot() 
    
    # 可重現性:「今天」讀快照凍結的參考日、不用 date.today()
    # 設計差異: evaluate 的基準是切分點 T(回到過去驗證,要留一段歷史當答案);這裡直接用 today,因為 A/B 模擬的情境是「現在上線做實驗、模擬未來的點擊」,不需要留答案窗。時間軸設定不同,因為回答的問題不同
    today = date.fromisoformat(snap.meta["reference_date"])
    
    # 取「事件表」的短別名
    ev = snap.events

    # 建立獨立的亂數產生器物件(不用全域 random)。這個 rng 專屬本次模擬,不被任何外部程式碼污染
    # 可重現性，與 synthetic_data 同一手法
    rng = random.Random(SEED)

    # 用 dict 列出「每一場比賽 (game_id): 對應的歷史交易次數」
    tc = ev[ev["event_type"] == "trade"]["game_id"].value_counts().to_dict()

    # 候選賽事: 未來的所有賽事 (今天之後的所有賽事)，因為推薦要推的是「還沒打的比賽」
    future = snap.games[snap.games["game_date"] > today]

    # 得出: 將未來所有的比賽一場一場拿出來，重新包裝成推薦系統演算法看得懂的公用格式。 同時利用剛算好的 tc 字典，去查出每場比賽的歷史交易次數（熱門度）
    # eg.     
    # [{
    #     "game_id": 101,
    #     "game_date": "2026-07-20",       # 格式為字串或日期物件
    #     "start_time": "18:30:00",
    #     "team_home": "中信兄弟",
    #     "team_away": "統一獅",
    #     "stadium": "台中洲際棒球場",
    #     "ticket_count": 0,               # 固定初始化為 0 分
    #     "trade_count": 145               # 查表得知：這場比賽 (認 games_id)歷史交易次數是 145 次
    # }, ...]

    games = [{"game_id": r.game_id, "game_date": r.game_date, "start_time": r.start_time,
              "team_home": r.team_home, "team_away": r.team_away, "stadium": r.stadium,
              "ticket_count": 0, "trade_count": int(tc.get(r.game_id, 0))}
             for r in future.itertuples()]
    
    # 冷啟動補位池: 個人化湊不滿 5 場時從這裡補。
    # sorted 回傳新 list，key=lambda 指定按人氣排;reverse=True 降冪;[:15] 取前 15
    hot = sorted(games, key=lambda g: g["trade_count"], reverse=True)[:15]

    
    # 使用者真實偏好 = 喜愛球隊 ∪ 互動過的球隊: 此使用者的「真實偏好球隊集合」= 明確設定的喜愛球隊 聯集 他行為碰過的所有球隊(主客都算)
    # 上帝視角 (prefs,決定點擊)
    # 上帝視角: 模擬世界的 ground truth,只拿來決定「他會不會點」。注意: 它用了這個使用者的全部行為、不切時間，因為prefs函數扮演「這人心裡真正喜歡什麼」，絕不餵給推薦工具
    def prefs(uid):  
        e = ev[ev["member_id"] == uid]
        return set(snap.favorites[uid]) | set(e["team_home"]) | set(e["team_away"])
    
    # 取出「使用者真實行為事件」，per-user 個人化的資料來源
    # 模型視角 (own,餵給推薦工具)
    # 若把 prefs 餵給模型,就是把答案洩漏給被測者,模擬就作弊了。這是模擬設計的核心紀律,對應離線評估的防洩漏思維
    def own(uid):
        e = ev[ev["member_id"] == uid]
        tr = e[e["event_type"] == "trade"][["team_home", "team_away", "created_at"]].to_dict("records")
        rs = e[e["event_type"] == "reservation"][["team_home", "team_away", "created_at"]].to_dict("records")
        return tr, rs

    # 計數器初始化
    # 兩臂各自的實驗結果累積器: 雙元素 list: [0] 位放曝光數、[1] 位放點擊數 (用 list 而非 tuple 因為要原地 += 1(tuple 不可變))
    counts = {"personalized": [0, 0], "popularity": [0, 0]}   # [曝光, 點擊]

    # 各臂人數計數
    # 跟 counts 分開記,因為「人數」和「曝光數」是不同單位。 (應用: SRM 重點是「分流單位是人,健康檢查要看人數」)
    split = {"personalized": 0, "popularity": 0}

    # 迭代 dict 預設走 key: 遍歷全部 200 位會員 id
    # 所有人都進實驗,不像 evaluate 篩 cohort: 因為 A/B 模擬的是真實上線情境:上線後每個到訪者都會被分流、看到推薦,包括零行為的人(走冷啟動)。評估篩人、實驗不篩人,所以刻意設計「兩者的母體不同」
    for uid in snap.favorites:
        # 呼叫線上真實分流函式: 對 uid 雜湊,回傳 "personalized" 或 "popularity"。同一人永遠同臂(穩定雜湊),分流可重現。(assign_variant 用 hash 不用 random 的原因: (1) 穩定:同一人每次到訪都在同一臂,不會這次個人化、下次純人氣(體驗一致、資料不污染);(2) 無狀態:不用存「誰在哪組」的表,uid 進來現算就好;(3) 可重現:任何人重算同一 uid 得到同一臂)
        # 然後把該臂人數 +1
        v = assign_variant(uid); split[v] += 1

        # 解包拿到這個使用者自己的交易與預約(模型視角輸入)
        tr, rs = own(uid)

        # 用他被分到那一臂的參數產生推薦。VARIANTS[v]——個人化臂拿完整計分參數,純人氣臂拿個人權重歸零版。同一個 recommend、換參數變兩臂——與 evaluate 同一手法,保證兩臂唯一差異就是「有無個人化」,對照乾淨。
        recs = recommend(snap.favorites[uid], tr, rs, games, hot, today, VARIANTS[v])

        # 取他的真實偏好集合(上帝視角)，供下面判斷點不點
        p = prefs(uid)
        # 推薦 recs 在迴圈外算好: 4 次到訪看到同一份推薦，合理 (短期內推薦不變) 也省計算
        for _ in range(VISITS_PER_USER):                       
            for g in recs:
                # 內層迴圈:每次到訪看到 5 張卡,每張卡 = 一次曝光,該臂曝光數 +1。所以每人貢獻 5×4=20 次曝光
                counts[v][0] += 1
                # 這張卡的主或客隊,有沒有命中他的真實偏好 -> 布林值。(這是「相關性」的操作型定義)
                relevant = (g["team_home"] in p) or (g["team_away"] in p)

                # P(點擊) = 基線 (BASE_CTR) + 加成 (RELEVANCE_LIFT) * 相關 
                # 點擊機率: 不相關的話就是 0.03、相關的話就是 0.18 (0.03+0.15)，min 防機率 > 1(目前參數用不到,是防未來調大參數的護欄)
                click_p = min(1.0, BASE_CTR + RELEVANCE_LIFT * (1 if relevant else 0))
                # rng.random() 回傳 [0,1) 均勻亂數;小於 click_p 的機率恰為 click_p
                # 一次伯努利試驗(Bernoulli trial): 以機率 click_p 擲骰子決定點或不點，點了就「該臂點擊數 +1」。整個模擬 = 4000 次伯努利試驗的集合(200人×20曝光)，就是後面 z 檢定所假設的資料生成形式
                if rng.random() < click_p:
                    counts[v][1] += 1

    # list 解包。統計慣例: n=試驗數(曝光)、k=成功數(點擊);A=對照、B=實驗
    # 實跑值:nA=2360, kA=362;nB=1640, kB=310
    nA, kA = counts["popularity"]      
    nB, kB = counts["personalized"]
    # 各臂 CTR = 樣本比例 p̂
    # 0.153 vs 0.189    
    ctrA, ctrB = kA / nA, kB / nB

    # 合併比例(pooled proportion): 把兩臂資料合起來算一個共同 CTR(≈0.168)
    # pooled = (實驗組點擊 + 對照組點擊) / (實驗組曝光 + 對照組曝光)
    # 原因: 假設檢定從「虛無假設 H₀:「兩臂 CTR 其實相同」」出發。既然 H₀ 說是同一個值，對它的最佳估計就是合併兩臂資料。「檢定量永遠在 H₀ 的世界裡計算」是假設檢定的邏輯根基
    pooled = (kA + kB) / (nA + nB)

    # 功能:H₀ 下的標準誤(standard error)——「若兩臂真的沒差,兩個 CTR 之差純因抽樣而波動的典型幅度」。
    # 公式來源:比例的變異數是 p(1-p)/n;兩獨立比例之差的變異數是相加:p(1-p)/nA + p(1-p)/nB = p(1-p)(1/nA+1/nB);H₀ 下 p 用 pooled 代入;開根號成標準誤。
    se = math.sqrt(pooled * (1 - pooled) * (1 / nA + 1 / nB))

    # z 統計量 = 訊噪比: 觀察到的差(訊號)是隨機波動幅度(雜訊)的幾倍。
    # z 在算「訊號除以 H₀ 下的雜訊」
    # 分母用 pooled: 因為標準誤是在 H₀(兩組相同)的世界算的,兩組既然相同就該合併估計
    # z=2.96:差距是雜訊水準的近 3 倍,在「沒差的世界」極罕見
    z = (ctrB - ctrA) / se

    # _phi(abs(z)) = 標準常態 ≤ |z| 的機率;1 - ... = 超過 |z| 的單尾機率;2 * = 雙尾(事前不預設方向——個人化也可能更差,兩個方向的極端都算)
    # p 值的精確定義: 若兩臂其實沒差,觀察到至少這麼極端的差距的機率 (p≈0.003 = 千分之三 → 太罕見 → 拒絕 H₀ → 顯著)
    pval = 2 * (1 - _phi(abs(z)))

    # 第二個標準誤——這次不用 pooled,各臂用各自的觀察比例(unpooled)
    # 為什麼有兩個 SE: 因為活在不同世界。檢定在 H₀(兩組相同)的世界問「差距多罕見」→ pooled;信賴區間在估計真實差距的範圍,沒有「兩組相同」的前提(真差距可能不為 0)→ 各用各的。
    # 小結 (作法): pooled 屬於檢定,unpooled 屬於估計
    se_diff = math.sqrt(ctrA * (1 - ctrA) / nA + ctrB * (1 - ctrB) / nB)

    # tuple 同時賦值上下界
    # 功能:95% 信賴區間 = 點估計 ± 1.96×SE(1.96 是標準常態雙尾 95% 臨界值)。結果 [+0.012, +0.060]
    # 真實 CTR 提升合理落在 +1.2 到 +6.0 個百分點。區間不含 0 ⇔ 與顯著結論一致;且 CI 比 p 多給「差多少」的範圍 -> 報告時 CI 比 p 更有資訊量
    lo, hi = (ctrB - ctrA) - 1.96 * se_diff, (ctrB - ctrA) + 1.96 * se_diff

    # 功能:雙比例檢定的每臂所需樣本量公式 n = (z_{α/2}+z_β)²·[pA(1-pA)+pB(1-pB)] / (pB-pA)²
    # 算出每臂約 1749 次曝光: 具體門檻，明確了解「流量不足」(真實流量才三百多)
    need = (1.96 + 0.84) ** 2 * (ctrA * (1 - ctrA) + ctrB * (1 - ctrB)) / (ctrB - ctrA) ** 2

    # 先印假設: 看結果前先看前提
    print(f"假設: 基線CTR={BASE_CTR}、命中偏好加成={RELEVANCE_LIFT}、每人{VISITS_PER_USER}次到訪、seed={SEED}")
    # 印人數分流(82/118)
    print(f"分流：個人化 {split['personalized']} 人 / 純人氣 {split['popularity']} 人")
    # 呈現比例時，必呈現「分子」與「分母」，0.15 是 15/100 或 1500/10000，可信度差很多
    print(f"對照(純人氣) : 曝光 {nA}、點擊 {kA}、CTR={ctrA:.3f}")
    print(f"實驗(個人化) : 曝光 {nB}、點擊 {kB}、CTR={ctrB:.3f}")
    
    # 顯示正號或負號，表示「差值方向」很關鍵
    # 同時呈現「絕對效應」與「相對效應」。相對效應（如 +23.2%）在大盤基線較低時容易產生過度放大的視覺偏誤；絕對效應（如 +3.6%）則能直接反映對全站點擊總量的實際貢獻，利於商務效益評估（ROI）。兩者並陳以提供決策者全面的評估維度。
    print(f"絕對提升 {ctrB - ctrA:+.3f}（相對 {(ctrB - ctrA) / ctrA * 100:+.1f}%)| 差異95%CI [{lo:+.3f}, {hi:+.3f}]")
    # .2e: 科學記號法，例如：3.03e-03，p 很小時比一串零好讀
    print(f"雙比例 z 檢定: z={z:.2f}、雙尾 p={pval:.2e} → {'顯著' if pval < 0.05 else '不顯著'}(α=0.05)")
    # math.ceil: 無條件進位。樣本數不能有小數,且寧多勿少(向下取會讓 power 略低於 80%)
    print(f"檢定力：偵測此效應(80% power, α=0.05)需每臂約 {math.ceil(need)} 次曝光")

# CLI 腳本標準收尾
# 直接執行才跑模擬; 被 import 時不會跑
if __name__ == "__main__":
    simulate()




# 計算兩組獨立比例的 z 檢定後，利用誤差函數（Error Function, erf）與標準常態 CDF 的數學恆等式，直接用 Python math 模組手寫出 φ(x) 函數來推算雙尾 p 值，這樣做可以讓腳本在任何不支援第三方庫的純 Python 環境下都能順利執行。

# z 檢定假設每次曝光是獨立的伯努利試驗,但你的模擬裡同一人貢獻 20 次曝光,且他的 prefs 固定 → 同一人的點擊彼此相關。這是「觀測值叢聚(clustering)」:有效樣本量小於表面曝光數 → SE 被低估 → p 值偏樂觀。
# 真實實驗上，會以使用者為分析單位(對每人 CTR 做檢定)或用修正的標準誤。這跟 SRM 看用戶數、macro 每人一票是同一個原則:分析單位對齊隨機化單位