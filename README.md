# SalesCoach AI — MVP Backend

AI-powered field-sales decision support for GCash's merchant distribution network.
The backend exposes **independent per-agent endpoints** (no orchestration layer) so
the frontend can call each AI capability separately.

> **LLM provider:** Groq (`llama-3.3-70b-versatile`) via its OpenAI-compatible API.

---

## 1. Architecture

```
┌──────────────┐      HTTP/JSON       ┌───────────────────────────┐
│   Frontend   │ ───────────────────▶ │   FastAPI  (api/main.py)  │
└──────────────┘                      │                           │
                                      │  • Chat Agent endpoint    │
                                      │  • Merchant Insight       │
                                      │    Agent endpoints        │
                                      └─────────────┬─────────────┘
                                                    │ Semantic Kernel
                                                    │ (ChatCompletionAgent + Groq)
                                                    ▼
                                      ┌───────────────────────────┐
                                      │  Merchant DB MCP Server    │
                                      │  (agent_plugin_verse/...)  │
                                      │  RBAC-scoped DB tools      │
                                      └─────────────┬─────────────┘
                                                    │ psycopg2
                                                    ▼
                                          ┌──────────────────┐
                                          │   PostgreSQL     │
                                          └──────────────────┘
```

### Agents (2)

| Agent | Folder | Responsibility |
|---|---|---|
| **Merchant Insight Agent** | `agent_verse/merchant_insight_agent/` | Fetch & summarize a merchant's `profile`, `score`, `recommendation`, or a full `brief` (mode-driven). Consolidates the former Profile/Scoring/Recommendation/Brief agents. |
| **Chat Agent** | `agent_verse/chat_agent/` | Open-ended "Ask SalesCoach" Q&A grounded on authorized merchant data, with guardrails. |

### MCP tools (RBAC-scoped)

All tools require `user_id` + `user_role` and filter rows by the caller's scope
(DSP → own merchants, Manager → team, Admin → all):

`get_merchant_details`, `get_merchant_score`, `get_merchant_recommendations`,
`get_merchant_visit_history`, `update_action`, `search_data`, `get_audit`.

---

## 2. Prerequisites

- Python 3.11+ (tested on 3.13)
- A reachable PostgreSQL database (the seed script targets Neon)
- A Groq API key — https://console.groq.com/keys
- Network access to `api.groq.com` (corporate proxies may block it)

---

## 3. Setup

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # PowerShell
# If activation is blocked by execution policy, either run:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
# or call the interpreter directly: .\.venv\Scripts\python.exe ...

# 2. Install dependencies
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Configure environment
Copy-Item .env.example .env
#   then edit .env and set GROQ_API_KEY and DATABASE_URL
```

### Configuration files

- **`.env`** — secrets & runtime config (see `.env.example`).
- **`config/llm_config.json`** — LLM provider settings (Groq model + base URL).
- **`config/plugin_config.json`** — MCP server SSE URL (`http://localhost:8000/sse`).

---

## 4. Seed the database (first run only)

```powershell
.\.venv\Scripts\python.exe db\setup_and_seed.py
```

This creates all tables and populates realistic synthetic data
(users, merchants, signals, daily scores, recommendations, visit history).

**Test Credentials generated:**
- **Admin**: `admin@gcash.com` / `admin123`
- **Manager**: `maria.santos@gcash.com` / `manager123`
- **DSP**: `miguel.delacruz@gcash.com` / `dsp123`

---

## 5. Run

Open **two** terminals (both with the venv).

**Terminal 1 — MCP DB server (port 9002):**
```powershell
.\.venv\Scripts\python.exe -m agent_plugin_verse.db_plugin.server
```

**Terminal 2 — API server (port 8080):**
```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8080
```

Interactive API docs: **http://localhost:8080/docs**

---

## 6. API Reference

Base URL: `http://localhost:8080`

| Method | Endpoint | Agent / Mode | Body / Query |
|---|---|---|---|
| GET  | `/health` | — | — |
| POST | `/api/v1/chat` | Chat Agent | `{ "message", "user_id?", "user_role?" }` |
| POST | `/api/v1/merchants/insight` | Insight (any mode) | `{ "merchant_name", "mode", "user_id?", "user_role?" }` |
| GET  | `/api/v1/merchants/{name}/profile` | Insight · profile | `?user_id=&user_role=` |
| GET  | `/api/v1/merchants/{name}/score` | Insight · score | `?user_id=&user_role=` |
| GET  | `/api/v1/merchants/{name}/recommendation` | Insight · recommendation | `?user_id=&user_role=` |
| GET  | `/api/v1/merchants/{name}/brief` | Insight · brief | `?user_id=&user_role=` |

If `user_id` / `user_role` are omitted, a seeded demo DSP is used (see `DEFAULT_USER`
in `api/main.py`).

### Example requests

```powershell
# Health
curl http://localhost:8080/health

# Pre-visit brief (GET)
curl "http://localhost:8080/api/v1/merchants/LJ's%20Bakery/brief"

# Insight with explicit mode + user context (POST)
curl -X POST http://localhost:8080/api/v1/merchants/insight `
  -H "Content-Type: application/json" `
  -d '{ "merchant_name": "LJ''s Bakery", "mode": "score", "user_role": "DSP", "user_id": "294bc771-4a09-4cae-8958-2edc6f4b484d" }'

# Ask SalesCoach (POST)
curl -X POST http://localhost:8080/api/v1/chat `
  -H "Content-Type: application/json" `
  -d '{ "message": "Which of my merchants need attention most right now?" }'
```

### Response shape

```json
// /api/v1/merchants/{name}/brief
{ "agent": "merchant_insight", "mode": "brief", "merchant": "LJ's Bakery", "answer": "..." }

// /api/v1/chat
{ "agent": "chat", "answer": "..." }
```

---

## 7. Project Structure

```
api/
  main.py                     # FastAPI app — independent per-agent endpoints
agent_verse/
  chat_agent/                 # Ask SalesCoach agent
  merchant_insight_agent/     # Profile/Score/Recommendation/Brief (mode-driven)
agent_plugin_verse/
  db_plugin/server.py         # Merchant DB MCP server (RBAC-scoped tools)
ai_model/
  agent_llm_factory.py        # Builds the Groq ChatCompletion service
config/
  llm_config.json             # LLM provider config (Groq)
  plugin_config.json          # MCP SSE URL
  credential_manager.py       # Reads env vars
db/
  setup_and_seed.py           # Schema + synthetic data
utils/                        # Logger, metrics
```

---

## 8. Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` on LLM calls | Corporate TLS proxy. `truststore` is auto-injected in `agent_llm_factory.py` to use the OS cert store. Ensure `truststore` is installed. |
| LLM returns HTML / `'str' object has no attribute 'usage'` | The network is intercepting `api.groq.com` (e.g. redirect to a sign-in page). Run on a network with direct Groq access. |
| `db_plugin.sse_server_url not configured` | Start the MCP server (Terminal 1) and check `config/plugin_config.json`. |
| `DATABASE_URL ... not set` | Set `DATABASE_URL` in `.env`. |
| Activation blocked in PowerShell | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, or call `.\.venv\Scripts\python.exe` directly. |

---

## 9. Security Notes

- All MCP tools enforce row-level RBAC by `user_id` / `user_role`.
- Do **not** commit `.env` (already in `.gitignore`).
- The demo `DATABASE_URL` fallback in the MCP server and seed script is for local
  demos only — replace and rotate before any shared/production use.
