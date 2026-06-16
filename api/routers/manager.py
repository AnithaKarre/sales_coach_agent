"""
Phase 6 — Manager APIs
GET /api/v1/manager/area-summary       → Area-level KPI summary (pure SQL)
GET /api/v1/manager/team-performance   → DSP performance stats (pure SQL)
GET /api/v1/manager/dsp/{id}           → Specific DSP portfolio details
"""

from fastapi import APIRouter, Depends, HTTPException
from api.database import get_db
from api.dependencies import require_role

router = APIRouter(prefix="/api/v1/manager", tags=["Manager"])


# ── GET /manager/area-summary ─────────────────────────────────
@router.get("/area-summary")
async def area_summary(
    user: dict = Depends(require_role("Manager", "Admin")),
    conn=Depends(get_db),
):
    """
    Area-level summary for the Manager's region.
    Pure SQL via v_area_summary view. No AI.
    """
    cur = conn.cursor()
    uid = user["user_id"]
    role = user["role"]

    if role == "Admin":
        # Admin sees all areas
        cur.execute("SELECT * FROM v_area_summary ORDER BY region, area")
    else:
        # Manager sees their region's areas
        cur.execute(
            """
            SELECT vas.*
            FROM v_area_summary vas
            WHERE vas.region = (SELECT region FROM users WHERE id = %s)
            ORDER BY vas.area
            """,
            (uid,),
        )

    rows = cur.fetchall()

    # Aggregate totals
    total_merchants = sum(r["total_merchants"] or 0 for r in rows)
    total_completed = sum(r["actions_completed"] or 0 for r in rows)
    total_pending = sum(r["actions_pending"] or 0 for r in rows)
    total_in_progress = sum(r["actions_in_progress"] or 0 for r in rows)
    total_actions = total_completed + total_pending + total_in_progress
    completion_rate = round(total_completed / total_actions * 100, 1) if total_actions > 0 else 0

    high_priority_count = 0
    cur2 = conn.cursor()
    if role == "Admin":
        cur2.execute(
            "SELECT COUNT(*) AS cnt FROM daily_scores WHERE score_date = (SELECT MAX(score_date) FROM daily_scores) AND priority_score >= 70"
        )
    else:
        cur2.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM daily_scores ds
            JOIN merchants m ON m.id = ds.merchant_id
            WHERE ds.score_date = (SELECT MAX(score_date) FROM daily_scores)
              AND ds.priority_score >= 70
              AND m.region = (SELECT region FROM users WHERE id = %s)
            """,
            (uid,),
        )
    hp_row = cur2.fetchone()
    high_priority_count = hp_row["cnt"] if hp_row else 0

    # Visits by area (count visit_history grouped by area)
    cur3 = conn.cursor()
    if role == "Admin":
        cur3.execute(
            """
            SELECT m.area, COUNT(v.id) AS visits
            FROM visit_history v
            JOIN merchants m ON m.id = v.merchant_id
            WHERE v.visit_date >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY m.area
            ORDER BY m.area
            """
        )
    else:
        cur3.execute(
            """
            SELECT m.area, COUNT(v.id) AS visits
            FROM visit_history v
            JOIN merchants m ON m.id = v.merchant_id
            WHERE v.visit_date >= CURRENT_DATE - INTERVAL '7 days'
              AND m.region = (SELECT region FROM users WHERE id = %s)
            GROUP BY m.area
            ORDER BY m.area
            """,
            (uid,),
        )
    visit_rows = cur3.fetchall()
    # Build visits_by_area with a target of 10 per area per week
    visits_by_area = [
        {
            "area": vr["area"] or "Unknown",
            "visits": vr["visits"] or 0,
            "target": 10,
        }
        for vr in visit_rows
    ]

    return {
        "completion_rate": completion_rate,
        "total_merchants": total_merchants,
        "high_priority": high_priority_count,
        "visits_by_area": visits_by_area,
        "areas": [
            {
                "region": r["region"],
                "area": r["area"],
                "total_merchants": r["total_merchants"],
                "total_dsps": r["total_dsps"],
                "avg_priority_score": float(r["avg_priority_score"]) if r["avg_priority_score"] else None,
                "actions_completed": r["actions_completed"],
                "actions_pending": r["actions_pending"],
                "actions_in_progress": r["actions_in_progress"],
                "completion_rate": float(r["completion_rate"]) if r["completion_rate"] else 0,
            }
            for r in rows
        ],
    }


# ── GET /manager/team ─────────────────────────────────────────
@router.get("/team")
async def team_performance(
    user: dict = Depends(require_role("Manager", "Admin")),
    conn=Depends(get_db),
):
    """DSP-level performance statistics for the Manager's team.

    Pure SQL via v_dsp_performance view.
    """
    cur = conn.cursor()
    uid = user["user_id"]
    role = user["role"]

    if role == "Admin":
        cur.execute("SELECT * FROM v_dsp_performance ORDER BY completion_rate DESC NULLS LAST")
    else:
        cur.execute(
            """
            SELECT vdp.*
            FROM v_dsp_performance vdp
            WHERE vdp.dsp_id IN (
                SELECT id FROM users WHERE manager_id = %s
            )
            ORDER BY vdp.completion_rate DESC NULLS LAST
            """,
            (uid,),
        )

    rows = cur.fetchall()
    return [
        {
            "name": r["dsp_name"],
            "region": r["region"],
            "area": r["area"],
            "merchants": r["merchant_count"],
            "avg_score": round(float(r["avg_portfolio_score"]), 1) if r["avg_portfolio_score"] else None,
            "completed": r["actions_completed"],
            "open": r["actions_open"],
            "completion_rate": f"{round(float(r['completion_rate']), 1)}%" if r["completion_rate"] else "0%",
        }
        for r in rows
    ]


