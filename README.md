# HR5 Invest

> Premium personal investment copilot — crypto, stocks, ETFs, DEX, CEX and brokers in one AI-powered command center.

HR5 Invest is a full-stack platform: a **FastAPI** backend (real market data,
portfolio engine, quantitative analytics, multi-model AI copilot, WebSocket
streaming) and a **Next.js** frontend with a premium dark design system.

It grew out of a single-file Streamlit futures PnL tool (preserved in
[`legacy/`](legacy/), and ported to the **Trading** page).

---

## Architecture

```
hr5-invest/
├── backend/                 # FastAPI — the engine
│   └── app/
│       ├── config.py        # type-safe env config (no hard-coded secrets)
│       ├── core/            # cache (TTL), security (seed-phrase guard, Fernet), logging
│       ├── models/          # Pydantic schemas (API contracts)
│       ├── services/        # fmp, market, portfolio, analytics, futures, db (SQLite)
│       ├── ai/              # providers (Claude/OpenAI/Gemini), router, 5 agents
│       └── api/             # REST routes + WebSocket stream
├── frontend/                # Next.js 15 (App Router) + Tailwind + framer-motion
│   ├── app/                 # dashboard, portfolio, markets, trading, analytics, copilot
│   ├── components/          # ui/, layout/, dashboard/
│   └── lib/                 # api client, ws hook, formatting, react-query
├── legacy/                  # original Streamlit prototype (kept intact)
└── docs/                    # ARCHITECTURE.md, ROADMAP.md
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the deep dive and
[`docs/ROADMAP.md`](docs/ROADMAP.md) for what's wired today vs. the phased plan.

---

## Quick start

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then fill in FMP_API_KEY + at least one AI key
uvicorn app.main:app --reload --port 8000
```

API docs: <http://localhost:8000/docs>

### 2. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

App: <http://localhost:3000>

---

## What's real today

| Pillar | Status |
|---|---|
| Premium dark design system | ✅ Tailwind tokens, glassmorphism, framer-motion |
| Dashboard (value, P&L, allocation, watchlist, heatmap, positions) | ✅ live via FMP |
| Real-time updates | ✅ WebSocket stream + smart polling |
| Portfolio engine (valuation, P&L, allocation) | ✅ SQLite-backed |
| Analytics (Sharpe, vol, drawdown, VaR, correlations) | ✅ |
| AI copilot — 5 agents, multi-model routing | ✅ (needs an API key) |
| Futures calculator | ✅ ported from legacy |
| DEX/CEX/broker live sync | 🔜 read-only connectors (Phase 2) |
| Historical performance (W/M/Y) | 🔜 history service (Phase 2) |

## Security

- **Never** stores seed phrases or private keys — the API actively rejects them.
- Secrets live in env vars only; sensitive at-rest values use Fernet encryption.
- Read-only by design: the copilot advises, it never moves funds.
