# 從真實 recommendation_events 算各臂 CTR；永久排除內部/測試流量（append-only + 下游過濾）
from config.database import get_connection

# 「內部 / QA / demo 帳號」:固定給 treatment + 一律排除在實驗分析之外 (不參與隨機分流)(內部帳號：固定走個人化且排除於實驗分析之外)
from services.recommender import INTERNAL_MEMBER_IDS


def ctr_report():
    placeholders = ",".join(["%s"] * len(INTERNAL_MEMBER_IDS))
    query = f"""
        SELECT variant,
               SUM(event_type = 'impression') AS impressions,
               SUM(event_type = 'click')      AS clicks
        FROM recommendation_events
        WHERE member_id NOT IN ({placeholders})
        GROUP BY variant
    """
    with get_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, tuple(INTERNAL_MEMBER_IDS))
            rows = cursor.fetchall()
    for r in rows:
        imp, clk = int(r["impressions"]), int(r["clicks"] or 0)
        ctr = clk / imp if imp else 0
        print(f"{r['variant']:12s} 曝光 {imp}、點擊 {clk}、CTR={ctr:.3f}")
    return rows

if __name__ == "__main__":
    ctr_report()