# HR5 Invest — Roadmap

This session delivered **Phase 1**: a real, runnable full-stack foundation.
Below is what's wired now and the phased plan to reach the full vision.

## ✅ Phase 1 — Foundation (this session)

- Monorepo: `backend/` (FastAPI) + `frontend/` (Next.js) + preserved `legacy/`.
- Premium dark design system (tokens, glassmorphism, micro-animations).
- Dashboard: portfolio value, P&L, allocation donut, watchlist, sector heatmap,
  positions table, AI briefing.
- Real market data via FMP (quotes, movers, sectors, news, calendar).
- Portfolio engine (SQLite) — valuation, P&L, allocation.
- Analytics engine — Sharpe, volatility, max drawdown, VaR, correlation matrix.
- Multi-model AI copilot — 5 agents (Portfolio, DCA, Research, Market, Journal)
  with Claude/OpenAI/Gemini routing.
- Realtime — WebSocket streaming + smart polling.
- Futures calculator ported from the original tool.
- Security baseline — seed-phrase rejection, env secrets, Fernet helper.

## 🔜 Phase 2 — Data depth & connectors

- **History service**: store daily portfolio snapshots → real W/M/Y/YTD
  performance and an equity curve (currently only the day move is live).
- **Read-only exchange connectors**: CEX (Binance/Coinbase via API key, read
  scope only) and DEX wallets (public address → on-chain balances). Encrypted
  at rest; never seeds.
- **Broker import**: CSV/statement import for positions & transactions.
- **DCA AI** backed by real cost-basis history.
- **Alerts**: price/threshold alerts pushed over the existing WebSocket.

## 🔜 Phase 3 — Intelligence & scale

- Streaming AI responses (token-by-token) in the copilot.
- On-chain data providers for Crypto Research AI (TVL, holders, activity).
- Redis-backed cache + pub/sub for multi-instance realtime.
- Auth (multi-user) + Postgres migration.
- Backtesting & scenario simulation for strategies.
- Trading Journal AI with automated trade tagging and discipline scoring.

## 🔜 Phase 4 — Polish & production

- E2E + unit test suites (analytics already pure/testable).
- Observability (structured logs, metrics, error tracking).
- Deployment: backend (Fly/Render), frontend (Vercel), managed Postgres/Redis.
- Mobile-optimised PWA.
