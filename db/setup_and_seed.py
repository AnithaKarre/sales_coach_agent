"""
SalesCoach AI  Database Setup & Seed Script
=============================================
This script connects to your PostgreSQL database (Neon cloud),
creates all tables, and populates them with realistic synthetic data.

Usage:
    1. Set your DATABASE_URL below (or as environment variable)
    2. Run: py db/setup_and_seed.py

Requirements:
    pip install psycopg2-binary
"""

import os
import uuid
import random
import hashlib
import json
from datetime import datetime, date, timedelta

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    print("Installing psycopg2-binary...")
    os.system("py -m pip install psycopg2-binary")
    import psycopg2
    from psycopg2.extras import execute_values

# ============================================================
# CONFIG  Paste your Neon connection string here
# ============================================================
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_iErpGOuI70XN@ep-damp-darkness-aqzim7gn-pooler.c-8.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

# ============================================================
# REALISTIC DATA TEMPLATES
# ============================================================
REGIONS = ["NCR", "Central Luzon", "CALABARZON", "Western Visayas", "Central Visayas"]

AREAS = {
    "NCR": ["Quezon City", "Manila", "Makati", "Pasig", "Taguig"],
    "Central Luzon": ["Pampanga", "Bulacan", "Tarlac", "Nueva Ecija", "Zambales"],
    "CALABARZON": ["Cavite", "Laguna", "Batangas", "Rizal", "Quezon"],
    "Western Visayas": ["Iloilo", "Bacolod", "Antique", "Capiz", "Aklan"],
    "Central Visayas": ["Cebu City", "Mandaue", "Lapu-Lapu", "Bohol", "Siquijor"],
}

MERCHANT_PREFIXES = [
    "Sari-Sari", "Mini Mart", "General Merchandise", "Variety Store",
    "Grocery", "Convenience", "Mobile Hub", "Tech Shop", "E-Load Center",
    "Pharmacy", "Hardware", "Bakery", "Eatery", "Water Station", "Laundry"
]

MERCHANT_NAMES = [
    "Maria's", "Juan's", "Ate Nene's", "Kuya Boy's", "Aling Rosa's",
    "Mang Pedro's", "Nanay Cora's", "Tatay Ben's", "Tita Joy's", "Lola Fe's",
    "Don Carlos", "Star", "Golden", "Lucky", "Happy", "Sunshine", "Rainbow",
    "Diamond", "Crystal", "Pearl", "Metro", "City", "Town", "Village", "Prime",
    "KJ's", "RJ's", "DJ's", "AJ's", "MJ's", "CJ's", "BJ's", "LJ's",
]

CATEGORIES = [
    "Sari-Sari Store", "Convenience Store", "Pharmacy", "Hardware",
    "Mobile & Accessories", "General Merchandise", "Food & Beverage",
    "Water Refilling", "Laundry Shop", "Electronics"
]

STREET_NAMES = [
    "Rizal St.", "Mabini Ave.", "Bonifacio Blvd.", "Aguinaldo Highway",
    "Quezon Ave.", "Osmena Blvd.", "Del Pilar St.", "Luna St.",
    "Burgos St.", "Roxas Blvd.", "Commonwealth Ave.", "EDSA",
    "Marcos Highway", "Ortigas Ave.", "Shaw Blvd.", "Aurora Blvd."
]

RECOMMENDATION_TEMPLATES = [
    "Visit merchant within 24 hours  transaction volume has dropped {drop}% over the past week. Investigate root cause and discuss recovery plan.",
    "Schedule a visit to discuss campaign enrollment. Merchant is currently inactive in all campaigns despite being a {tier} tier outlet.",
    "Follow up on {complaints} unresolved complaints. Merchant satisfaction is at risk and may impact retention.",
    "Merchant has not been visited in {days} days. Conduct a routine check-in to maintain relationship and assess current needs.",
    "Discuss wallet top-up promotion. Current wallet balance is low at {balance}, which may be limiting transaction capacity.",
    "Recommend product expansion  merchant currently has only {products} active products. Cross-sell GCash services.",
    "Urgent: Transaction decline of {drop}% combined with {complaints} complaints. Prioritize this outlet for immediate visit.",
    "Re-engage merchant on GCash campaign. Campaign status is 'Pending' for over 2 weeks with no activation.",
    "Congratulate merchant on strong performance and discuss growth opportunities. Transaction volume is up {growth}%.",
    "Assess merchant readiness for tier upgrade  consistent transaction growth over the past 30 days."
]


def hash_password(password: str) -> str:
    """Simple hash for demo  in production use bcrypt."""
    return hashlib.sha256(password.encode()).hexdigest()


def create_tables(conn):
    """Create all SalesCoach tables directly in the database."""
    print("\n Creating tables...")

    cur = conn.cursor()

    # Enable extensions
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    print("   OK pgvector extension enabled")

    # Drop existing tables (clean slate for POC)
    cur.execute("""
        DROP TABLE IF EXISTS merchant_embeddings CASCADE;
        DROP TABLE IF EXISTS chat_sessions CASCADE;
        DROP TABLE IF EXISTS audit_logs CASCADE;
        DROP TABLE IF EXISTS visit_history CASCADE;
        DROP TABLE IF EXISTS recommendations CASCADE;
        DROP TABLE IF EXISTS daily_scores CASCADE;
        DROP TABLE IF EXISTS merchant_signals CASCADE;
        DROP TABLE IF EXISTS merchants CASCADE;
        DROP TABLE IF EXISTS users CASCADE;
    """)
    print("     Cleaned up existing tables")

    # USERS
    cur.execute("""
        CREATE TABLE users (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email           VARCHAR(255) UNIQUE NOT NULL,
            password_hash   VARCHAR(255) NOT NULL,
            full_name       VARCHAR(255) NOT NULL,
            role            VARCHAR(20) NOT NULL CHECK (role IN ('DSP', 'Manager', 'Admin')),
            region          VARCHAR(100),
            area            VARCHAR(100),
            manager_id      UUID REFERENCES users(id),
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX idx_users_role ON users(role);
        CREATE INDEX idx_users_manager ON users(manager_id);
    """)
    print("   OK users table created")

    # MERCHANTS
    cur.execute("""
        CREATE TABLE merchants (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_name   VARCHAR(255) NOT NULL,
            region          VARCHAR(100) NOT NULL,
            area            VARCHAR(100),
            tier            VARCHAR(20) CHECK (tier IN ('Gold', 'Silver', 'Bronze', 'New')),
            category        VARCHAR(100),
            contact_number  VARCHAR(20),
            address         TEXT,
            latitude        DECIMAL(10,7),
            longitude       DECIMAL(10,7),
            assigned_dsp_id UUID REFERENCES users(id) NOT NULL,
            is_active       BOOLEAN DEFAULT TRUE,
            onboarding_date DATE,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX idx_merchants_dsp ON merchants(assigned_dsp_id);
        CREATE INDEX idx_merchants_region ON merchants(region, area);
        CREATE INDEX idx_merchants_tier ON merchants(tier);
    """)
    print("   OK merchants table created")

    # MERCHANT SIGNALS
    cur.execute("""
        CREATE TABLE merchant_signals (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_id         UUID REFERENCES merchants(id) NOT NULL,
            signal_date         DATE NOT NULL,
            transaction_volume  INTEGER,
            transaction_trend   DECIMAL(5,2),
            days_since_visit    INTEGER,
            complaint_count     INTEGER DEFAULT 0,
            campaign_status     VARCHAR(20) CHECK (campaign_status IN ('Active','Inactive','Pending','None')),
            wallet_balance      DECIMAL(12,2),
            active_products     INTEGER,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(merchant_id, signal_date)
        );
        CREATE INDEX idx_signals_merchant_date ON merchant_signals(merchant_id, signal_date DESC);
    """)
    print("   OK merchant_signals table created")

    # DAILY SCORES
    cur.execute("""
        CREATE TABLE daily_scores (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_id     UUID REFERENCES merchants(id) NOT NULL,
            score_date      DATE NOT NULL,
            priority_score  DECIMAL(5,2) NOT NULL,
            rank            INTEGER,
            score_breakdown JSONB,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(merchant_id, score_date)
        );
        CREATE INDEX idx_scores_date_rank ON daily_scores(score_date, rank);
    """)
    print("   OK daily_scores table created")

    # RECOMMENDATIONS
    cur.execute("""
        CREATE TABLE recommendations (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_id         UUID REFERENCES merchants(id) NOT NULL,
            recommended_action  TEXT NOT NULL,
            action_explanation  TEXT,
            confidence_score    DECIMAL(3,2),
            status              VARCHAR(20) DEFAULT 'New'
                                CHECK (status IN ('New','In Progress','Done','Deferred')),
            status_updated_at   TIMESTAMPTZ,
            status_updated_by   UUID REFERENCES users(id),
            recommendation_date DATE DEFAULT CURRENT_DATE,
            created_at          TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX idx_rec_merchant ON recommendations(merchant_id, recommendation_date DESC);
        CREATE INDEX idx_rec_status ON recommendations(status);
    """)
    print("   OK recommendations table created")

    # VISIT HISTORY
    cur.execute("""
        CREATE TABLE visit_history (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_id     UUID REFERENCES merchants(id) NOT NULL,
            dsp_id          UUID REFERENCES users(id) NOT NULL,
            visit_date      DATE NOT NULL,
            visit_notes     TEXT,
            outcome         VARCHAR(50),
            duration_mins   INTEGER,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX idx_visits_merchant ON visit_history(merchant_id, visit_date DESC);
        CREATE INDEX idx_visits_dsp ON visit_history(dsp_id, visit_date DESC);
    """)
    print("   OK visit_history table created")

    # AUDIT LOGS
    cur.execute("""
        CREATE TABLE audit_logs (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID REFERENCES users(id),
            action      VARCHAR(100) NOT NULL,
            resource    VARCHAR(100),
            resource_id UUID,
            details     JSONB,
            ip_address  INET,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX idx_audit_user ON audit_logs(user_id, created_at DESC);
        CREATE INDEX idx_audit_action ON audit_logs(action, created_at DESC);
    """)
    print("   OK audit_logs table created")

    # CHAT SESSIONS
    cur.execute("""
        CREATE TABLE chat_sessions (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID REFERENCES users(id) NOT NULL,
            title       VARCHAR(255),
            messages    JSONB DEFAULT '[]',
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX idx_chat_user ON chat_sessions(user_id, updated_at DESC);
    """)
    print("   OK chat_sessions table created")

    # MERCHANT EMBEDDINGS (pgvector)
    cur.execute("""
        CREATE TABLE merchant_embeddings (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_id     UUID REFERENCES merchants(id) NOT NULL,
            content_type    VARCHAR(50),
            content_text    TEXT NOT NULL,
            embedding       vector(1536),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX idx_embed_merchant ON merchant_embeddings(merchant_id);
    """)
    print("   OK merchant_embeddings table created")

    # ANALYTICAL VIEWS
    cur.execute("""
        CREATE OR REPLACE VIEW v_area_summary AS
        SELECT
            m.region,
            m.area,
            COUNT(DISTINCT m.id)                                    AS total_merchants,
            COUNT(DISTINCT m.assigned_dsp_id)                       AS total_dsps,
            ROUND(AVG(ds.priority_score), 2)                        AS avg_priority_score,
            COUNT(CASE WHEN r.status = 'Done' THEN 1 END)          AS actions_completed,
            COUNT(CASE WHEN r.status = 'New' THEN 1 END)           AS actions_pending,
            COUNT(CASE WHEN r.status = 'In Progress' THEN 1 END)   AS actions_in_progress,
            ROUND(
                COUNT(CASE WHEN r.status = 'Done' THEN 1 END)::DECIMAL
                / NULLIF(COUNT(r.id), 0) * 100, 1
            )                                                       AS completion_rate
        FROM merchants m
        LEFT JOIN daily_scores ds ON ds.merchant_id = m.id AND ds.score_date = CURRENT_DATE
        LEFT JOIN recommendations r ON r.merchant_id = m.id AND r.recommendation_date = CURRENT_DATE
        WHERE m.is_active = TRUE
        GROUP BY m.region, m.area;
    """)

    cur.execute("""
        CREATE OR REPLACE VIEW v_dsp_performance AS
        SELECT
            u.id AS dsp_id,
            u.full_name AS dsp_name,
            u.region,
            u.area,
            COUNT(DISTINCT m.id)                                    AS merchant_count,
            ROUND(AVG(ds.priority_score), 2)                        AS avg_portfolio_score,
            COUNT(CASE WHEN r.status = 'Done' THEN 1 END)          AS actions_completed,
            COUNT(CASE WHEN r.status IN ('New','In Progress') THEN 1 END) AS actions_open,
            ROUND(
                COUNT(CASE WHEN r.status = 'Done' THEN 1 END)::DECIMAL
                / NULLIF(COUNT(r.id), 0) * 100, 1
            )                                                       AS completion_rate
        FROM users u
        JOIN merchants m ON m.assigned_dsp_id = u.id AND m.is_active = TRUE
        LEFT JOIN daily_scores ds ON ds.merchant_id = m.id AND ds.score_date = CURRENT_DATE
        LEFT JOIN recommendations r ON r.merchant_id = m.id AND r.recommendation_date = CURRENT_DATE
        WHERE u.role = 'DSP' AND u.is_active = TRUE
        GROUP BY u.id, u.full_name, u.region, u.area;
    """)
    print("   OK analytical views created")

    conn.commit()
    print("\nOK All 9 tables + 2 views created successfully!\n")


def generate_phone():
    """Generate a Philippine mobile number."""
    return f"+639{random.randint(100000000, 999999999)}"


def generate_address(area, region):
    """Generate a realistic Philippine address."""
    num = random.randint(1, 999)
    street = random.choice(STREET_NAMES)
    return f"{num} {street}, Brgy. {random.randint(1, 50)}, {area}, {region}"


def seed_data(conn):
    """Populate all tables with realistic synthetic data."""
    cur = conn.cursor()
    today = date.today()

    print(" Seeding data...\n")

    #  1. CREATE USERS 
    print("    Creating users...")

    # Admin
    admin_id = str(uuid.uuid4())
    cur.execute("""
        INSERT INTO users (id, email, password_hash, full_name, role, region)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (admin_id, "admin@gcash.com", hash_password("admin123"),
          "System Admin", "Admin", "NCR"))

    # Managers (1 per region)
    manager_ids = {}
    manager_data = [
        ("Maria Santos", "NCR"),
        ("Jose Cruz", "Central Luzon"),
        ("Ana Reyes", "CALABARZON"),
        ("Carlo Mendoza", "Western Visayas"),
        ("Sofia Garcia", "Central Visayas"),
    ]
    for name, region in manager_data:
        mid = str(uuid.uuid4())
        manager_ids[region] = mid
        email = name.lower().replace(" ", ".") + "@gcash.com"
        cur.execute("""
            INSERT INTO users (id, email, password_hash, full_name, role, region)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (mid, email, hash_password("manager123"), name, "Manager", region))

    # DSPs (4 per region = 20 total)
    dsp_ids = {}  # {region: [dsp_id, ...]}
    dsp_first_names = [
        "Miguel", "Paolo", "Rafael", "Gabriel", "Luis",
        "Carmen", "Elena", "Rosa", "Teresa", "Lucia",
        "Diego", "Marco", "Antonio", "Felipe", "Andres",
        "Isabella", "Valentina", "Camila", "Daniela", "Mariana",
    ]
    dsp_last_names = [
        "Dela Cruz", "Santos", "Reyes", "Ramos", "Gonzales",
        "Bautista", "Villanueva", "Fernandez", "Lopez", "Torres",
        "Aquino", "Castillo", "Rivera", "Flores", "Mendoza",
        "Navarro", "Diaz", "Morales", "Santiago", "Pascual",
    ]

    dsp_idx = 0
    for region in REGIONS:
        dsp_ids[region] = []
        areas = AREAS[region]
        for i in range(4):
            did = str(uuid.uuid4())
            dsp_ids[region].append(did)
            fname = dsp_first_names[dsp_idx % len(dsp_first_names)]
            lname = dsp_last_names[dsp_idx % len(dsp_last_names)]
            full_name = f"{fname} {lname}"
            email = f"{fname.lower()}.{lname.lower().replace(' ', '')}@gcash.com"
            area = areas[i % len(areas)]
            cur.execute("""
                INSERT INTO users (id, email, password_hash, full_name, role, region, area, manager_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (did, email, hash_password("dsp123"), full_name, "DSP",
                  region, area, manager_ids[region]))
            dsp_idx += 1

    total_users = 1 + len(manager_ids) + sum(len(v) for v in dsp_ids.values())
    print(f"   OK {total_users} users created (1 Admin, {len(manager_ids)} Managers, {total_users - 1 - len(manager_ids)} DSPs)")

    #  2. CREATE MERCHANTS 
    print("    Creating merchants...")

    merchant_ids = []  # [(merchant_id, dsp_id, region, area, tier)]
    merchant_count = 0

    for region in REGIONS:
        for dsp_id in dsp_ids[region]:
            # Each DSP has 20-30 merchants
            num_merchants = random.randint(20, 30)
            for _ in range(num_merchants):
                mid = str(uuid.uuid4())
                area = random.choice(AREAS[region])
                prefix = random.choice(MERCHANT_PREFIXES)
                name = random.choice(MERCHANT_NAMES)
                merchant_name = f"{name} {prefix}"
                tier = random.choices(
                    ["Gold", "Silver", "Bronze", "New"],
                    weights=[10, 25, 40, 25]
                )[0]
                category = random.choice(CATEGORIES)
                onboard_days = random.randint(30, 730)
                lat = round(random.uniform(7.0, 18.5), 7)
                lng = round(random.uniform(120.0, 127.0), 7)

                cur.execute("""
                    INSERT INTO merchants (id, merchant_name, region, area, tier, category,
                                          contact_number, address, latitude, longitude,
                                          assigned_dsp_id, onboarding_date)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (mid, merchant_name, region, area, tier, category,
                      generate_phone(), generate_address(area, region),
                      lat, lng, dsp_id,
                      today - timedelta(days=onboard_days)))

                merchant_ids.append((mid, dsp_id, region, area, tier))
                merchant_count += 1

    print(f"   OK {merchant_count} merchants created")

    #  3. MERCHANT SIGNALS (last 7 days) 
    print("    Generating merchant signals (7 days)...")

    signal_count = 0
    for day_offset in range(7):
        signal_date = today - timedelta(days=day_offset)
        for mid, dsp_id, region, area, tier in merchant_ids:
            # Generate realistic signal patterns
            base_vol = {"Gold": 150, "Silver": 80, "Bronze": 40, "New": 15}[tier]
            transaction_volume = max(0, base_vol + random.randint(-30, 30))

            # Some merchants have declining trends (makes interesting data)
            if random.random() < 0.25:
                transaction_trend = round(random.uniform(-50, -5), 2)  # declining
            elif random.random() < 0.6:
                transaction_trend = round(random.uniform(-5, 5), 2)    # stable
            else:
                transaction_trend = round(random.uniform(5, 30), 2)    # growing

            days_since_visit = random.choices(
                [random.randint(0, 3), random.randint(4, 14), random.randint(15, 45)],
                weights=[40, 35, 25]
            )[0]

            complaint_count = random.choices(
                [0, 1, 2, random.randint(3, 7)],
                weights=[60, 20, 12, 8]
            )[0]

            campaign_status = random.choices(
                ["Active", "Inactive", "Pending", "None"],
                weights=[30, 25, 15, 30]
            )[0]

            wallet_balance = round(random.uniform(100, 50000), 2)
            active_products = random.randint(1, 8)

            cur.execute("""
                INSERT INTO merchant_signals
                    (merchant_id, signal_date, transaction_volume, transaction_trend,
                     days_since_visit, complaint_count, campaign_status,
                     wallet_balance, active_products)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (merchant_id, signal_date) DO NOTHING
            """, (mid, signal_date, transaction_volume, transaction_trend,
                  days_since_visit, complaint_count, campaign_status,
                  wallet_balance, active_products))
            signal_count += 1

    print(f"   OK {signal_count} signal records created")

    #  4. COMPUTE DAILY SCORES (today) 
    print("    Computing priority scores...")

    score_data = []
    for mid, dsp_id, region, area, tier in merchant_ids:
        # Fetch today's signals
        cur.execute("""
            SELECT transaction_trend, days_since_visit, complaint_count
            FROM merchant_signals
            WHERE merchant_id = %s AND signal_date = %s
        """, (mid, today))
        row = cur.fetchone()
        if not row:
            continue

        trend, days_visit, complaints = row

        # Scoring formula from our BRD
        tier_scores = {"Gold": 100, "Silver": 70, "Bronze": 40, "New": 20}
        s_transaction = min(abs(float(trend or 0)), 100)       # 0-100
        s_recency = min((days_visit or 0) / 30 * 100, 100)    # 0-100
        s_tier = tier_scores.get(tier, 20)                      # 0-100
        s_complaint = min((complaints or 0) / 5 * 100, 100)    # 0-100

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

    # Sort by score descending and assign ranks
    score_data.sort(key=lambda x: x[2], reverse=True)

    for rank, (mid, sdate, score, breakdown) in enumerate(score_data, 1):
        cur.execute("""
            INSERT INTO daily_scores (merchant_id, score_date, priority_score, rank, score_breakdown)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (merchant_id, score_date) DO NOTHING
        """, (mid, sdate, score, rank, breakdown))

    print(f"   OK {len(score_data)} priority scores computed & ranked")

    #  5. RECOMMENDATIONS (today) 
    print("    Generating recommendations...")

    rec_count = 0
    statuses = ["New", "New", "New", "In Progress", "Done", "Deferred"]
    for mid, dsp_id, region, area, tier in merchant_ids:
        cur.execute("""
            SELECT transaction_trend, days_since_visit, complaint_count,
                   campaign_status, wallet_balance, active_products
            FROM merchant_signals
            WHERE merchant_id = %s AND signal_date = %s
        """, (mid, today))
        row = cur.fetchone()
        if not row:
            continue

        trend, days_visit, complaints, camp_status, balance, products = row

        # Pick a recommendation based on the dominant signal
        template = random.choice(RECOMMENDATION_TEMPLATES)
        action = template.format(
            drop=abs(int(trend or 10)),
            tier=tier,
            complaints=complaints or 0,
            days=days_visit or 0,
            balance=int(balance or 0),
            products=products or 1,
            growth=abs(int(trend or 5)),
        )

        explanation = f"Based on {tier} tier merchant with "
        reasons = []
        if trend and trend < -10:
            reasons.append(f"{abs(trend):.0f}% transaction decline")
        if days_visit and days_visit > 14:
            reasons.append(f"{days_visit} days since last visit")
        if complaints and complaints > 0:
            reasons.append(f"{complaints} active complaint(s)")
        if camp_status == "Inactive":
            reasons.append("inactive campaign status")
        if not reasons:
            reasons.append("routine check-in due")
        explanation += ", ".join(reasons) + "."

        status = random.choice(statuses)
        confidence = round(random.uniform(0.65, 0.98), 2)

        cur.execute("""
            INSERT INTO recommendations
                (merchant_id, recommended_action, action_explanation,
                 confidence_score, status, recommendation_date,
                 status_updated_by, status_updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (mid, action, explanation, confidence, status, today,
              dsp_id if status != "New" else None,
              datetime.now() if status != "New" else None))
        rec_count += 1

    print(f"   OK {rec_count} recommendations created")

    #  6. VISIT HISTORY (last 60 days) 
    print("    Generating visit history...")

    visit_count = 0
    visit_outcomes = ["Successful", "Partially Successful", "Follow-up Needed",
                      "Merchant Unavailable", "Completed"]
    visit_notes_templates = [
        "Discussed transaction recovery plan. Merchant agreed to increase promotions.",
        "Merchant receptive to campaign enrollment. Will activate by end of week.",
        "Resolved complaint regarding delayed settlement. Merchant satisfied.",
        "Routine check-in. All KPIs within normal range.",
        "Merchant was closed during visit. Will revisit tomorrow.",
        "Delivered training on new GCash features. Merchant eager to adopt.",
        "Discussed tier upgrade requirements. Merchant needs 20% more transactions.",
        "Addressed connectivity issues affecting QR payments. Escalated to tech support.",
        "Merchant requested additional marketing materials. Order placed.",
        "Reviewed monthly performance metrics with merchant owner.",
    ]

    for mid, dsp_id, region, area, tier in merchant_ids:
        # 2-6 visits per merchant over last 60 days
        num_visits = random.randint(2, 6)
        for _ in range(num_visits):
            visit_date = today - timedelta(days=random.randint(1, 60))
            cur.execute("""
                INSERT INTO visit_history (merchant_id, dsp_id, visit_date,
                                           visit_notes, outcome, duration_mins)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (mid, dsp_id, visit_date,
                  random.choice(visit_notes_templates),
                  random.choice(visit_outcomes),
                  random.randint(10, 60)))
            visit_count += 1

    print(f"   OK {visit_count} visit records created")

    #  7. AUDIT LOGS (sample) 
    print("    Generating audit logs...")

    audit_actions = [
        ("LOGIN", "auth", None),
        ("VIEW_DASHBOARD", "dashboard", None),
        ("VIEW_MERCHANT", "merchant", None),
        ("UPDATE_ACTION_STATUS", "recommendation", None),
        ("GENERATE_BRIEF", "merchant", None),
        ("CHAT_MESSAGE", "chat", None),
        ("EXPORT_DATA", "report", None),
    ]

    all_user_ids = [admin_id] + list(manager_ids.values())
    for region_dsps in dsp_ids.values():
        all_user_ids.extend(region_dsps)

    audit_count = 0
    for _ in range(200):
        user_id = random.choice(all_user_ids)
        action, resource, _ = random.choice(audit_actions)
        log_time = datetime.now() - timedelta(
            days=random.randint(0, 30),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59)
        )
        cur.execute("""
            INSERT INTO audit_logs (user_id, action, resource, details, ip_address, created_at)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (user_id, action, resource,
              json.dumps({"timestamp": log_time.isoformat()}),
              f"192.168.{random.randint(1,255)}.{random.randint(1,255)}",
              log_time))
        audit_count += 1

    print(f"   OK {audit_count} audit log entries created")

    conn.commit()

    #  SUMMARY 
    print("\n" + "=" * 60)
    print(" DATABASE SETUP COMPLETE!")
    print("=" * 60)
    print(f"""
     Data Summary:
    
    Users:              {total_users}
      - Admin:          1
      - Managers:       {len(manager_ids)}
      - DSPs:           {total_users - 1 - len(manager_ids)}
    Merchants:          {merchant_count}
    Signal Records:     {signal_count}
    Priority Scores:    {len(score_data)}
    Recommendations:    {rec_count}
    Visit Records:      {visit_count}
    Audit Logs:         {audit_count}
    

     Login Credentials (for testing):
    
    Admin:    admin@gcash.com       / admin123
    Manager:  maria.santos@gcash.com / manager123
    DSP:      miguel.delacruz@gcash.com / dsp123
    
    """)


def verify_data(conn):
    """Run quick checks to confirm data is correct."""
    cur = conn.cursor()

    print(" Verifying data...\n")

    checks = [
        ("Users by role", "SELECT role, COUNT(*) FROM users GROUP BY role ORDER BY role"),
        ("Merchants by tier", "SELECT tier, COUNT(*) FROM merchants GROUP BY tier ORDER BY tier"),
        ("Merchants by region", "SELECT region, COUNT(*) FROM merchants GROUP BY region ORDER BY region"),
        ("Signals (today)", "SELECT COUNT(*) FROM merchant_signals WHERE signal_date = CURRENT_DATE"),
        ("Top 5 Priority Merchants", """
            SELECT m.merchant_name, m.tier, ds.priority_score, ds.rank
            FROM daily_scores ds
            JOIN merchants m ON m.id = ds.merchant_id
            WHERE ds.score_date = CURRENT_DATE
            ORDER BY ds.rank
            LIMIT 5
        """),
        ("Recommendation status distribution", """
            SELECT status, COUNT(*) FROM recommendations
            WHERE recommendation_date = CURRENT_DATE
            GROUP BY status ORDER BY status
        """),
        ("Area Summary (view)", "SELECT * FROM v_area_summary LIMIT 5"),
    ]

    for label, query in checks:
        print(f"    {label}:")
        cur.execute(query)
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        for row in rows:
            formatted = ", ".join(f"{c}={v}" for c, v in zip(cols, row))
            print(f"      {formatted}")
        print()


def main():
    print("=" * 60)
    print("  SalesCoach AI  Database Setup & Seed")
    print("=" * 60)

    if "your_user" in DATABASE_URL or "your_pass" in DATABASE_URL:
        print("\nWARNING  ERROR: Please set your DATABASE_URL!")
        print("   Edit this file and replace the DATABASE_URL with your Neon connection string.")
        print("   Or set it as environment variable:")
        print('   set DATABASE_URL="postgresql://user:pass@host/db?sslmode=require"')
        return

    print(f"\n Connecting to database...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        print("   OK Connected successfully!")
    except Exception as e:
        print(f"\nFAIL Connection failed: {e}")
        print("\n   Please check your DATABASE_URL and try again.")
        return

    try:
        create_tables(conn)
        seed_data(conn)
        verify_data(conn)
    except Exception as e:
        conn.rollback()
        print(f"\nFAIL Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()
        print(" Connection closed.")


if __name__ == "__main__":
    main()
