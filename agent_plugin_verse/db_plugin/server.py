"""
Merchant DB MCP Server
Exposes semantic, ready merchant database tools.

Security model:
- Every tool requires a user context (user_id + user_role) and enforces
  row-level access scope BEFORE returning any data. This MCP layer is the
  single data-access enforcement point for RBAC.
- The database connection string is loaded from the DATABASE_URL environment
  variable, with a hardcoded demo fallback (replace before production).
"""

import os
import psycopg2
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

NAME = "Merchant DB MCP"
HOST = "0.0.0.0"
PORT = 9002

mcp = FastMCP(NAME, host=HOST, port=PORT)

VALID_ROLES = ("DSP", "Manager", "Admin")


class MerchantDBPlugin:
    """Merchant DB MCP tools for fetching profile data with RBAC scoping."""

    # -----------------------
    # Internal helpers
    # -----------------------
    @staticmethod
    def _get_connection():
        # NOTE: Demo convenience — hardcoded fallback so the server runs without
        # requiring DATABASE_URL to be set. Do NOT keep this for production.
        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql://neondb_owner:npg_iErpGOuI70XN@ep-damp-darkness-aqzim7gn-pooler.c-8.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
        )
        return psycopg2.connect(db_url)

    @staticmethod
    def _scope_clause(user_id: str, user_role: str):
        """
        Returns (sql_fragment, params) that restricts merchant rows to the
        caller's authorized scope. The fragment is ANDed against a query that
        already references the merchants table aliased as `m`.

        - DSP: only merchants assigned to them.
        - Manager: merchants assigned to their team (direct reports) or themselves.
        - Admin: no restriction.
        """
        role = (user_role or "").strip()
        if role not in VALID_ROLES:
            raise PermissionError(f"Invalid or missing role: {user_role!r}")

        if role == "Admin":
            return "TRUE", []
        if role == "Manager":
            return (
                "m.assigned_dsp_id IN "
                "(SELECT id FROM users WHERE manager_id = %s OR id = %s)",
                [user_id, user_id],
            )
        # DSP
        return "m.assigned_dsp_id = %s", [user_id]

    # -----------------------
    # MCP TOOLS
    # -----------------------
    @staticmethod
    @mcp.tool()
    def get_merchant_details(merchant_name: str, user_id: str, user_role: str) -> str:
        """Fetches the profile details of a merchant by name, scoped to the caller's access. Requires user_id and user_role (DSP, Manager, or Admin)."""
        clean_name = merchant_name.strip('\'" ')
        try:
            scope_sql, scope_params = MerchantDBPlugin._scope_clause(user_id, user_role)
            conn = MerchantDBPlugin._get_connection()
            cur = conn.cursor()
            cur.execute(
                f"SELECT id, merchant_name, region, area, tier, category, contact_number, address "
                f"FROM merchants m WHERE merchant_name ILIKE %s AND {scope_sql} LIMIT 1",
                [f"%{clean_name}%", *scope_params],
            )
            row = cur.fetchone()
            conn.close()

            if row:
                return str({
                    "id": str(row[0]),
                    "merchant_name": row[1],
                    "region": row[2],
                    "area": row[3],
                    "tier": row[4],
                    "category": row[5],
                    "contact_number": row[6],
                    "address": row[7]
                })
            else:
                return '{"error": "Merchant not found or access denied"}'
        except PermissionError as e:
            return str({"error": str(e)})
        except Exception as e:
            return str({"error": str(e)})

    @staticmethod
    @mcp.tool()
    def get_merchant_score(merchant_name: str, user_id: str, user_role: str) -> str:
        """Fetches the daily priority score, rank, and signals of a merchant by name, scoped to the caller's access. Requires user_id and user_role."""
        clean_name = merchant_name.strip('\'" ')
        try:
            scope_sql, scope_params = MerchantDBPlugin._scope_clause(user_id, user_role)
            conn = MerchantDBPlugin._get_connection()
            cur = conn.cursor()
            cur.execute(
                f'''
                SELECT m.merchant_name, ds.priority_score, ds.rank, ds.score_breakdown, ms.transaction_trend, ms.complaint_count
                FROM merchants m
                LEFT JOIN daily_scores ds ON m.id = ds.merchant_id AND ds.score_date = CURRENT_DATE
                LEFT JOIN merchant_signals ms ON m.id = ms.merchant_id AND ms.signal_date = CURRENT_DATE
                WHERE m.merchant_name ILIKE %s AND {scope_sql} LIMIT 1
                ''',
                [f"%{clean_name}%", *scope_params],
            )
            row = cur.fetchone()
            conn.close()

            if row:
                return str({
                    "merchant_name": row[0],
                    "priority_score": float(row[1]) if row[1] is not None else None,
                    "rank": row[2],
                    "score_breakdown": row[3],
                    "transaction_trend": float(row[4]) if row[4] is not None else None,
                    "complaint_count": row[5]
                })
            else:
                return '{"error": "Merchant score not found for today or access denied"}'
        except PermissionError as e:
            return str({"error": str(e)})
        except Exception as e:
            return str({"error": str(e)})

    @staticmethod
    @mcp.tool()
    def get_merchant_recommendations(merchant_name: str, user_id: str, user_role: str) -> str:
        """Fetches the AI-generated recommended actions for a merchant by name, scoped to the caller's access. Requires user_id and user_role."""
        clean_name = merchant_name.strip('\'" ')
        try:
            scope_sql, scope_params = MerchantDBPlugin._scope_clause(user_id, user_role)
            conn = MerchantDBPlugin._get_connection()
            cur = conn.cursor()
            cur.execute(
                f'''
                SELECT r.recommended_action, r.action_explanation, r.status, r.confidence_score
                FROM merchants m
                JOIN recommendations r ON m.id = r.merchant_id
                WHERE m.merchant_name ILIKE %s AND r.recommendation_date = CURRENT_DATE AND {scope_sql}
                ORDER BY r.confidence_score DESC
                ''',
                [f"%{clean_name}%", *scope_params],
            )
            rows = cur.fetchall()
            conn.close()

            if rows:
                recs = []
                for row in rows:
                    recs.append({
                        "action": row[0],
                        "explanation": row[1],
                        "status": row[2],
                        "confidence_score": float(row[3]) if row[3] else None
                    })
                return str({"merchant_name": merchant_name, "recommendations": recs})
            else:
                return '{"error": "No recommendations found for this merchant today or access denied"}'
        except PermissionError as e:
            return str({"error": str(e)})
        except Exception as e:
            return str({"error": str(e)})

    @staticmethod
    @mcp.tool()
    def get_merchant_visit_history(merchant_name: str, user_id: str, user_role: str) -> str:
        """Fetches the past visit history for a merchant by name, scoped to the caller's access. Requires user_id and user_role."""
        clean_name = merchant_name.strip('\'" ')
        try:
            scope_sql, scope_params = MerchantDBPlugin._scope_clause(user_id, user_role)
            conn = MerchantDBPlugin._get_connection()
            cur = conn.cursor()
            cur.execute(
                f'''
                SELECT v.visit_date, v.visit_notes, v.outcome, u.full_name
                FROM merchants m
                JOIN visit_history v ON m.id = v.merchant_id
                JOIN users u ON v.dsp_id = u.id
                WHERE m.merchant_name ILIKE %s AND {scope_sql}
                ORDER BY v.visit_date DESC
                LIMIT 5
                ''',
                [f"%{clean_name}%", *scope_params],
            )
            rows = cur.fetchall()
            conn.close()

            if rows:
                visits = []
                for row in rows:
                    visits.append({
                        "date": str(row[0]),
                        "notes": row[1],
                        "outcome": row[2],
                        "visited_by": row[3]
                    })
                return str({"merchant_name": merchant_name, "recent_visits": visits})
            else:
                return '{"error": "No visit history found for this merchant or access denied"}'
        except PermissionError as e:
            return str({"error": str(e)})
        except Exception as e:
            return str({"error": str(e)})

    @staticmethod
    @mcp.tool()
    def update_action(recommendation_id: str, status: str, user_id: str, user_role: str) -> str:
        """Updates the status of a recommendation/action (New, In Progress, Done, Deferred). Only the assigned DSP may update; scoped to the caller's access. Requires user_id and user_role."""
        valid_status = ("New", "In Progress", "Done", "Deferred")
        try:
            if status not in valid_status:
                return str({"error": f"Invalid status. Must be one of {valid_status}"})

            if user_role != "DSP":
                return str({"error": "Forbidden: Only DSPs can update recommendation statuses according to the permission matrix."})

            scope_sql = "m.assigned_dsp_id = %s"
            scope_params = [user_id]
            conn = MerchantDBPlugin._get_connection()
            cur = conn.cursor()
            cur.execute(
                f'''
                UPDATE recommendations r
                SET status = %s, status_updated_at = NOW(), status_updated_by = %s
                FROM merchants m
                WHERE r.id = %s AND r.merchant_id = m.id AND {scope_sql}
                RETURNING r.id
                ''',
                [status, user_id, recommendation_id, *scope_params],
            )
            updated = cur.fetchone()
            conn.commit()
            conn.close()

            if updated:
                return str({"recommendation_id": recommendation_id, "status": status, "result": "updated"})
            else:
                return '{"error": "Recommendation not found or access denied"}'
        except PermissionError as e:
            return str({"error": str(e)})
        except Exception as e:
            return str({"error": str(e)})

    @staticmethod
    @mcp.tool()
    def search_data(query: str, user_id: str, user_role: str) -> str:
        """Searches merchants within the caller's authorized scope by name, region, area, or category. Use for broad or comparative questions. Requires user_id and user_role."""
        try:
            scope_sql, scope_params = MerchantDBPlugin._scope_clause(user_id, user_role)
            conn = MerchantDBPlugin._get_connection()
            cur = conn.cursor()
            like = f"%{query}%"
            cur.execute(
                f'''
                SELECT m.merchant_name, m.region, m.area, m.tier, m.category,
                       ds.priority_score, ds.rank
                FROM merchants m
                LEFT JOIN daily_scores ds ON m.id = ds.merchant_id AND ds.score_date = CURRENT_DATE
                WHERE {scope_sql}
                  AND (m.merchant_name ILIKE %s OR m.region ILIKE %s OR m.area ILIKE %s OR m.category ILIKE %s)
                ORDER BY ds.priority_score DESC NULLS LAST
                LIMIT 20
                ''',
                [*scope_params, like, like, like, like],
            )
            rows = cur.fetchall()
            conn.close()

            results = []
            for row in rows:
                results.append({
                    "merchant_name": row[0],
                    "region": row[1],
                    "area": row[2],
                    "tier": row[3],
                    "category": row[4],
                    "priority_score": float(row[5]) if row[5] is not None else None,
                    "rank": row[6],
                })
            return str({"query": query, "matches": results})
        except PermissionError as e:
            return str({"error": str(e)})
        except Exception as e:
            return str({"error": str(e)})

    @staticmethod
    @mcp.tool()
    def get_audit(user_role: str, action_filter: str = "", limit: int = 50) -> str:
        """Queries audit logs. Admin-only. Optionally filter by action substring."""
        try:
            if (user_role or "").strip() != "Admin":
                raise PermissionError("Audit logs are restricted to Admin users")

            safe_limit = max(1, min(int(limit), 200))
            conn = MerchantDBPlugin._get_connection()
            cur = conn.cursor()
            if action_filter:
                cur.execute(
                    '''
                    SELECT a.action, a.resource, a.resource_id, a.details, a.created_at, u.full_name
                    FROM audit_logs a
                    LEFT JOIN users u ON a.user_id = u.id
                    WHERE a.action ILIKE %s
                    ORDER BY a.created_at DESC
                    LIMIT %s
                    ''',
                    [f"%{action_filter}%", safe_limit],
                )
            else:
                cur.execute(
                    '''
                    SELECT a.action, a.resource, a.resource_id, a.details, a.created_at, u.full_name
                    FROM audit_logs a
                    LEFT JOIN users u ON a.user_id = u.id
                    ORDER BY a.created_at DESC
                    LIMIT %s
                    ''',
                    [safe_limit],
                )
            rows = cur.fetchall()
            conn.close()

            logs = []
            for row in rows:
                logs.append({
                    "action": row[0],
                    "resource": row[1],
                    "resource_id": str(row[2]) if row[2] is not None else None,
                    "details": row[3],
                    "created_at": str(row[4]),
                    "user": row[5],
                })
            return str({"audit_logs": logs})
        except PermissionError as e:
            return str({"error": str(e)})
        except Exception as e:
            return str({"error": str(e)})

    # -----------------------
    # Server runner
    # -----------------------
    def run(self, transport="sse"):
        print(f"🚀 {NAME} running at http://{HOST}:{PORT}/mcp")
        mcp.run(transport=transport)


if __name__ == "__main__":
    server = MerchantDBPlugin()
    server.run()
