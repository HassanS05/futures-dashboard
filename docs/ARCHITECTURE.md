# HR5 Invest — Architecture

## Overview

HR5 Invest is split into two decoupled tiers so each can scale and deploy
independently, and so a future native/mobile client could reuse the same API.

```
┌────────────────────┐     REST + WebSocket      ┌──────────────────────┐
│   Next.js frontend │  ───────────────────────► │   FastAPI backend    │
│  (design system,   │                           │  (services + AI)     │
│   realtime hooks)  │ ◄───────────────────────  │                      │
└────────────────────┘        live ticks         └──────────┬───────────┘
                                                              │
                                          ┌───────────────────┼───────────────────┐
                                          ▼                   ▼                   ▼
                                    FMP market data     AI providers        SQLite store
                                    (quotes, news,    (Claude / OpenAI /   (positions,
                                     calendar, …)        Gemini)            transactions)
```

## Backend (FastAPI)

### Layers
- **`api/`** — thin HTTP/WS controllers. No business logic.
- **`services/`** — domain logic, pure where possible:
  - `fmp.py` — single outbound client (retries + TTL cache + graceful fallback).
  - `market.py` — normalises FMP payloads into our `Quote` schema.
  - `portfolio.py` — combines positions + live quotes → valuation, P&L, allocation.
  - `analytics.py` — pure NumPy quant functions (Sharpe, vol, drawdown, VaR, corr).
  - `futures.py` — faithful port of the original PnL calculator.
  - `db.py` — SQLite persistence (no secrets stored).
- **`ai/`** — `providers.py` (uniform adapter per LLM), `router.py` (task→model
  selection with fallback), `agents.py` (5 specialised system prompts + live
  data enrichment).
- **`core/`** — `cache.py`, `security.py`, `logging.py`.

### Multi-model AI routing
`router.py` maps a *task type* to an ordered provider preference and picks the
first one configured:

| Task | Preference |
|---|---|
| research / analysis / report | Claude → OpenAI → Gemini |
| summary | Gemini → OpenAI → Claude |
| explanation | Gemini → Claude → OpenAI |

Each agent declares its task type, so the right model is chosen automatically.
A request can force a provider/model via `model_override` (`"openai:gpt-4o"`).

### Realtime
`api/ws.py` accepts a subscription frame (`{"symbols": [...]}`) and pushes
quote + portfolio frames every few seconds. Because quotes flow through the
cached FMP layer, many connected clients don't multiply upstream calls. The
frontend layers React Query polling on top as a resilience fallback.

## Frontend (Next.js App Router)

- **Design system** lives in `tailwind.config.ts` (color tokens, shadows,
  gradients, keyframes) + `globals.css` (glass utilities, ambient glows).
- **`lib/`** — typed `api.ts` client, `ws.ts` reconnecting WebSocket hook,
  `providers.tsx` (React Query), `format.ts`.
- **`components/`** — `ui/` primitives, `layout/` shell, `dashboard/` widgets.
- API calls use relative `/api/*` paths, rewritten to the backend by
  `next.config.js`, so the same code works in dev and prod.

## Security model
- Seed phrases / private keys are **never** accepted (`core/security.reject_seed_phrase`).
- All secrets via env; optional Fernet encryption for any sensitive at-rest value.
- The platform is read-only advisory — no order execution or fund movement.
