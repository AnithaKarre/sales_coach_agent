import os
import random
import json
from datetime import date
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

def run_reprofiling():
    print("=" * 60)
    print("  SalesCoach AI  Daily Reprofiling Script")
    print("=" * 60)
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        print(" Connected to database successfully!")
    except Exception as e:
        print(f" Connection failed: {e}")
        return

    today = date.today()
    print(f" Generating new signals and scores for {today}...")

    # Fetch all active merchants
    cur.execute("SELECT id, tier FROM merchants WHERE is_active = TRUE")
    merchants = cur.fetchall()

    if not merchants:
        print(" No active merchants found!")
        return

    signal_count = 0
    score_data = []

    for mid, tier in merchants:
        # Fetch their latest signal to base the new one on
        cur.execute("""
            SELECT transaction_volume, transaction_trend, days_since_visit, 
                   complaint_count, campaign_status, wallet_balance, active_products
            FROM merchant_signals
            WHERE merchant_id = %s
            ORDER BY signal_date DESC
            LIMIT 1
        """, (mid,))
        last_signal = cur.fetchone()

        if last_signal:
            vol, trend, days_visit, complaints, camp, wallet, prods = last_signal
            
            # Simulate daily changes
            # 1. Transaction volume fluctuates by +/- 15%
            fluctuation = random.uniform(-0.15, 0.15)
            new_vol = max(0, int(vol * (1 + fluctuation)))
            
            # 2. Trend changes slightly
            new_trend = round(float(trend) + random.uniform(-5.0, 5.0), 2)
            
            # 3. Days since visit increments by 1 (unless they were visited today, but we'll just increment for simplicity)
            new_days_visit = (days_visit or 0) + 1
            
            # 4. Complaints might get resolved (drop to 0) or slightly increase
            if complaints > 0 and random.random() < 0.3:
                new_complaints = max(0, complaints - 1)
            elif random.random() < 0.05:
                new_complaints = (complaints or 0) + 1
            else:
                new_complaints = complaints
                
            new_wallet = max(0, round(float(wallet) + random.uniform(-500, 500), 2))
        else:
            # Fallback if no signals exist
            new_vol = random.randint(10, 200)
            new_trend = round(random.uniform(-10, 20), 2)
            new_days_visit = random.randint(1, 30)
            new_complaints = random.choices([0, 1, 2], weights=[80, 15, 5])[0]
            camp = "None"
            new_wallet = round(random.uniform(100, 5000), 2)
            prods = random.randint(1, 5)

        # Upsert new signals for today (ON CONFLICT DO UPDATE so it can be re-run on the same day for testing)
        cur.execute("""
            INSERT INTO merchant_signals 
                (merchant_id, signal_date, transaction_volume, transaction_trend,
                 days_since_visit, complaint_count, campaign_status,
                 wallet_balance, active_products)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (merchant_id, signal_date) 
            DO UPDATE SET 
                transaction_volume = EXCLUDED.transaction_volume,
                transaction_trend = EXCLUDED.transaction_trend,
                days_since_visit = EXCLUDED.days_since_visit,
                complaint_count = EXCLUDED.complaint_count,
                wallet_balance = EXCLUDED.wallet_balance
        """, (mid, today, new_vol, new_trend, new_days_visit, new_complaints, camp, new_wallet, prods))
        signal_count += 1

        # Calculate new priority score
        tier_scores = {"Gold": 100, "Silver": 70, "Bronze": 40, "New": 20}
        s_transaction = min(abs(float(new_trend or 0)), 100)       # 0-100
        s_recency = min((new_days_visit or 0) / 30 * 100, 100)     # 0-100
        s_tier = tier_scores.get(tier, 20)                         # 0-100
        s_complaint = min((new_complaints or 0) / 5 * 100, 100)    # 0-100

        priority_score = round(
            0.40 * s_transaction +
            0.30 * s_recency +
            0.20 * s_tier +
            0.10 * s_complaint,
            2
        )

        breakdown = {
            "transaction": round(0.40 * s_transaction, 1),
            "recency": round(0.30 * s_recency, 1),
            "tier": round(0.20 * s_tier, 1),
            "complaints": round(0.10 * s_complaint, 1),
        }

        score_data.append((mid, today, priority_score, json.dumps(breakdown)))

    # Sort by score descending to assign ranks
    score_data.sort(key=lambda x: x[2], reverse=True)

    # Upsert scores for today
    for rank, (mid, sdate, score, breakdown) in enumerate(score_data, 1):
        cur.execute("""
            INSERT INTO daily_scores (merchant_id, score_date, priority_score, rank, score_breakdown)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (merchant_id, score_date) 
            DO UPDATE SET
                priority_score = EXCLUDED.priority_score,
                rank = EXCLUDED.rank,
                score_breakdown = EXCLUDED.score_breakdown
        """, (mid, sdate, score, rank, breakdown))

    print(f" OK Generated {signal_count} new signal records for {today}")
    print(f" OK Computed and ranked {len(score_data)} priority scores for {today}")
    print("\n DONE! The frontend will now reflect these updated scores and dynamically generate new AI briefs.")

if __name__ == "__main__":
    run_reprofiling()
