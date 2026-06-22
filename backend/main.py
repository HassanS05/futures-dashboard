"""
HR5 Invest — Institutional Investment Desk
FastAPI + SQLite — Production Grade
"""
import os, json, time, asyncio, hashlib, secrets, sqlite3, io, csv, hmac, math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Depends, status, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import jwt, JWTError
from passlib.context import CryptContext
from loguru import logger

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

try:
    import anthropic as anthropic_sdk
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    import google.generativeai as genai_sdk
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

# ══════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = DATA_DIR / "hr5invest.db"

DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

def load_env():
    env_file = BASE_DIR / ".env"
    env = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ENV = load_env()
SECRET_KEY = ENV.get("SECRET_KEY", "hr5invest-prod-secret-2024")
ANTHROPIC_API_KEY = ENV.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = ENV.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = ENV.get("GOOGLE_API_KEY", "") or ENV.get("GEMINI_API_KEY", "")
DEFAULT_AI_PROVIDER = ENV.get("DEFAULT_AI_PROVIDER", "anthropic")
COINGECKO_API_KEY = ENV.get("COINGECKO_API_KEY", "")
COINMARKETCAP_API_KEY = ENV.get("COINMARKETCAP_API_KEY", "") or ENV.get("CMC_API_KEY", "")

# --- Chiffrement local des clés API CEX (dérivé de SECRET_KEY) ---
import base64
def _fernet():
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
    return Fernet(key)
def enc_secret(text: str) -> str:
    if not text:
        return ""
    try:
        return _fernet().encrypt(text.encode()).decode()
    except Exception as e:
        logger.error(f"enc_secret error: {e}")
        return ""
def dec_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception as e:
        logger.error(f"dec_secret error: {e}")
        return ""

# Per-provider models (overridable via .env)
ANTHROPIC_MODEL = ENV.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
OPENAI_MODEL = ENV.get("OPENAI_MODEL", "gpt-4o")
GEMINI_MODEL = ENV.get("GEMINI_MODEL", "gemini-1.5-pro")

# Multi-model routing: each task maps to an ordered provider preference.
# The router picks the first *configured & available* provider in the list.
#   research/analysis/report -> Claude (deep reasoning)
#   summary/explanation      -> Gemini (fast & cheap), then OpenAI
AI_TASK_ROUTING = {
    "research":    ["anthropic", "openai", "gemini"],
    "analysis":    ["anthropic", "openai", "gemini"],
    "report":      ["anthropic", "openai", "gemini"],
    "chat":        ["anthropic", "openai", "gemini"],
    "summary":     ["gemini", "openai", "anthropic"],
    "explanation": ["gemini", "anthropic", "openai"],
    "default":     [DEFAULT_AI_PROVIDER, "anthropic", "openai", "gemini"],
}

def _provider_available(name: str) -> bool:
    if name == "anthropic":
        return bool(ANTHROPIC_API_KEY and HAS_ANTHROPIC)
    if name == "openai":
        return bool(OPENAI_API_KEY and HAS_OPENAI)
    if name == "gemini":
        return bool(GEMINI_API_KEY and HAS_GEMINI)
    return False

def _resolve_provider(task: str = "default", override: str = "") -> str:
    """Return the name of the best available provider for a task, or ''."""
    if override and _provider_available(override):
        return override
    for name in AI_TASK_ROUTING.get(task, AI_TASK_ROUTING["default"]):
        if _provider_available(name):
            return name
    return ""

def ai_enabled() -> bool:
    return any(_provider_available(p) for p in ("anthropic", "openai", "gemini"))

async def _complete_one(provider: str, prompt: str, system: str, max_tokens: int) -> str:
    if provider == "anthropic":
        client = anthropic_sdk.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        kwargs = {"model": ANTHROPIC_MODEL, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        msg = await client.messages.create(**kwargs)
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if provider == "openai":
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL, messages=msgs, max_tokens=max_tokens)
        return resp.choices[0].message.content or ""
    # gemini
    genai_sdk.configure(api_key=GEMINI_API_KEY)
    gm = genai_sdk.GenerativeModel(GEMINI_MODEL, system_instruction=system or None)
    resp = await gm.generate_content_async(prompt)
    return resp.text or ""

async def ai_complete(prompt: str, *, system: str = "", max_tokens: int = 2000,
                      task: str = "default", override: str = "") -> str:
    """Unified non-streaming completion across Claude / OpenAI / Gemini, with
    automatic fallback: tries each configured provider in task order and returns
    the first non-empty answer. Raises RuntimeError only if all fail/empty."""
    if override and _provider_available(override):
        return await _complete_one(override, prompt, system, max_tokens)
    order = [p for p in dict.fromkeys(AI_TASK_ROUTING.get(task, AI_TASK_ROUTING["default"]))
             if _provider_available(p)]
    if not order:
        raise RuntimeError("Aucun provider IA configuré (ANTHROPIC/OPENAI/GOOGLE).")
    last_err = None
    for provider in order:
        try:
            out = await asyncio.wait_for(
                _complete_one(provider, prompt, system, max_tokens), timeout=35)
            if out and out.strip():
                return out
            logger.warning(f"ai_complete: {provider} a renvoyé vide, fallback…")
        except asyncio.TimeoutError:
            last_err = f"{provider}: délai dépassé"
            logger.warning(f"ai_complete: {provider} timeout, fallback…")
        except Exception as e:
            last_err = e
            logger.warning(f"ai_complete: {provider} a échoué ({e}); fallback…")
    raise RuntimeError(f"Tous les providers IA ont échoué/vide: {last_err}")

logger.add(LOGS_DIR / "hr5invest.log", rotation="10 MB", retention="7 days", level="INFO")

# ══════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════
def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

# Columns that may be missing on databases created with an older schema.
# Added in place via ALTER TABLE so existing data is preserved (CREATE TABLE
# IF NOT EXISTS never migrates an already-existing table).
_SCHEMA_MIGRATIONS = {
    "users": [("full_name", "TEXT DEFAULT ''"), ("is_active", "INTEGER DEFAULT 1"),
              ("is_admin", "INTEGER DEFAULT 0"), ("subscription", "TEXT DEFAULT 'free'"),
              ("settings", "TEXT DEFAULT '{}'")],
    "portfolios": [("description", "TEXT DEFAULT ''"), ("currency", "TEXT DEFAULT 'USD'"),
                   ("benchmark", "TEXT DEFAULT 'BTC'"), ("is_default", "INTEGER DEFAULT 0")],
    "portfolio_positions": [("asset_type", "TEXT DEFAULT 'crypto'"), ("name", "TEXT DEFAULT ''"),
                   ("quantity", "REAL DEFAULT 0"), ("avg_cost", "REAL DEFAULT 0"),
                   ("current_price", "REAL DEFAULT 0"), ("sector", "TEXT DEFAULT ''"),
                   ("notes", "TEXT DEFAULT ''")],
    "transactions": [("asset_type", "TEXT DEFAULT 'crypto'"), ("fees", "REAL DEFAULT 0"),
                   ("total", "REAL DEFAULT 0"), ("exchange", "TEXT DEFAULT ''"),
                   ("notes", "TEXT DEFAULT ''")],
    "watchlist": [("asset_type", "TEXT DEFAULT 'crypto'"), ("name", "TEXT DEFAULT ''"),
                   ("target_price", "REAL"), ("stop_loss", "REAL"), ("notes", "TEXT DEFAULT ''")],
    "alerts": [("threshold", "REAL"), ("message", "TEXT DEFAULT ''"), ("is_active", "INTEGER DEFAULT 1")],
    "ai_analyses": [("asset_type", "TEXT DEFAULT 'crypto'"), ("analysis", "TEXT DEFAULT '{}'")],
    "simulation_accounts": [("initial_capital", "REAL DEFAULT 10000"),
                   ("current_capital", "REAL DEFAULT 10000"), ("currency", "TEXT DEFAULT 'USD'")],
    "simulation_trades": [("fees", "REAL DEFAULT 0"), ("total", "REAL DEFAULT 0"),
                   ("pnl", "REAL DEFAULT 0")],
    "dca_plans": [("asset_type", "TEXT DEFAULT 'crypto'"), ("amount_per_period", "REAL DEFAULT 0"),
                   ("frequency", "TEXT DEFAULT 'monthly'"), ("total_budget", "REAL DEFAULT 0"),
                   ("start_date", "TEXT"), ("end_date", "TEXT"), ("is_active", "INTEGER DEFAULT 1"),
                   ("notes", "TEXT DEFAULT ''")],
}

def _migrate_schema(conn):
    for table, cols in _SCHEMA_MIGRATIONS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table will be created fresh by the schema script
        for col, coldef in cols:
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coldef}")
                    logger.info(f"🔧 Migration : colonne ajoutée {table}.{col}")
                except Exception as e:
                    logger.warning(f"Migration {table}.{col} échouée : {e}")
    conn.commit()

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            full_name TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            is_admin INTEGER DEFAULT 0,
            subscription TEXT DEFAULT 'free',
            created_at TEXT DEFAULT (datetime('now')),
            settings TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            currency TEXT DEFAULT 'USD',
            benchmark TEXT DEFAULT 'BTC',
            is_default INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS portfolio_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            asset_type TEXT DEFAULT 'crypto',
            name TEXT DEFAULT '',
            quantity REAL DEFAULT 0,
            avg_cost REAL DEFAULT 0,
            current_price REAL DEFAULT 0,
            sector TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            added_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (portfolio_id) REFERENCES portfolios(id)
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            asset_type TEXT DEFAULT 'crypto',
            tx_type TEXT NOT NULL,
            quantity REAL DEFAULT 0,
            price REAL DEFAULT 0,
            fees REAL DEFAULT 0,
            total REAL DEFAULT 0,
            exchange TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            tx_date TEXT DEFAULT (datetime('now')),
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (portfolio_id) REFERENCES portfolios(id)
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            asset_type TEXT DEFAULT 'crypto',
            name TEXT DEFAULT '',
            target_price REAL,
            stop_loss REAL,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, symbol),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            threshold REAL,
            message TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            triggered_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS ai_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            asset_type TEXT DEFAULT 'crypto',
            analysis TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS cex_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            exchange TEXT NOT NULL,
            label TEXT DEFAULT '',
            api_key_enc TEXT NOT NULL,
            api_secret_enc TEXT NOT NULL,
            api_password_enc TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            last_sync TEXT,
            UNIQUE(user_id, exchange),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS simulation_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            initial_capital REAL DEFAULT 10000,
            current_capital REAL DEFAULT 10000,
            currency TEXT DEFAULT 'USD',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS simulation_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            quantity REAL DEFAULT 0,
            avg_cost REAL DEFAULT 0,
            FOREIGN KEY (account_id) REFERENCES simulation_accounts(id)
        );

        CREATE TABLE IF NOT EXISTS simulation_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL DEFAULT 0,
            price REAL DEFAULT 0,
            fees REAL DEFAULT 0,
            total REAL DEFAULT 0,
            pnl REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (account_id) REFERENCES simulation_accounts(id)
        );

        CREATE TABLE IF NOT EXISTS dca_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            asset_type TEXT DEFAULT 'crypto',
            amount_per_period REAL DEFAULT 0,
            frequency TEXT DEFAULT 'monthly',
            total_budget REAL DEFAULT 0,
            start_date TEXT,
            end_date TEXT,
            is_active INTEGER DEFAULT 1,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            details TEXT DEFAULT '',
            ip TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)

    # Performance indexes
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_portfolios_user ON portfolios(user_id);
        CREATE INDEX IF NOT EXISTS idx_positions_portfolio ON portfolio_positions(portfolio_id);
        CREATE INDEX IF NOT EXISTS idx_positions_symbol ON portfolio_positions(symbol);
        CREATE INDEX IF NOT EXISTS idx_transactions_portfolio ON transactions(portfolio_id);
        CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(tx_date DESC);
        CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id);
        CREATE INDEX IF NOT EXISTS idx_ai_analyses_user ON ai_analyses(user_id);
        CREATE INDEX IF NOT EXISTS idx_dca_plans_user ON dca_plans(user_id);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id);
    """)

    # Heal any column drift from older database files before seeding.
    _migrate_schema(conn)

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    admin_hash = pwd.hash("Admin1234!")
    demo_hash = pwd.hash("Demo1234!")

    conn.execute("""INSERT OR IGNORE INTO users (email, username, hashed_password, full_name, is_admin, subscription)
        VALUES ('admin@hr5invest.com', 'admin', ?, 'Administrateur HR5', 1, 'institutional')""", (admin_hash,))
    conn.execute("""INSERT OR IGNORE INTO users (email, username, hashed_password, full_name, subscription)
        VALUES ('demo@hr5invest.com', 'demo', ?, 'Compte Démo', 'pro')""", (demo_hash,))

    conn.commit()

    # Créer portefeuilles par défaut
    for uid, name in [(1, "Portefeuille Principal Admin"), (2, "Portefeuille Démo")]:
        exists = conn.execute("SELECT id FROM portfolios WHERE user_id=? AND is_default=1", (uid,)).fetchone()
        if not exists:
            conn.execute("INSERT INTO portfolios (user_id, name, is_default) VALUES (?,?,1)", (uid, name))

    # Demo positions removed — users import their real wallets

    conn.commit()
    conn.close()
    logger.info("✅ Base de données initialisée")

# ══════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

def create_token(data: dict, expires_minutes: int = 60 * 24 * 7) -> str:
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    return jwt.encode({**data, "exp": expire}, SECRET_KEY, algorithm="HS256")

def verify_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        return None

def get_user_by_email(email: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(user_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Non authentifié")
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "Token invalide")
    user = get_user_by_id(int(payload.get("sub")))
    if not user or not user["is_active"]:
        raise HTTPException(401, "Compte introuvable ou désactivé")
    return user

# ══════════════════════════════════════════════════════════════
#  MARKET DATA CACHE
# ══════════════════════════════════════════════════════════════
_cache: dict = {}
_CG_COOLDOWN_UNTIL: float = 0.0   # anti-429 : on n'appelle plus CoinGecko markets avant cette heure

COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "ADA": "cardano", "AVAX": "avalanche-2", "DOT": "polkadot",
    "MATIC": "matic-network", "LINK": "chainlink", "UNI": "uniswap", "DOGE": "dogecoin",
    "SHIB": "shiba-inu", "LTC": "litecoin", "BCH": "bitcoin-cash", "ATOM": "cosmos",
    "FTM": "fantom", "NEAR": "near", "OP": "optimism", "ARB": "arbitrum",
    "SUI": "sui", "APT": "aptos", "INJ": "injective-protocol", "SEI": "sei-network",
    "TIA": "celestia", "STRK": "starknet", "JTO": "jito-governance-token",
    "WIF": "dogwifcoin", "PEPE": "pepe", "BONK": "bonk", "RENDER": "render-token",
    "FET": "fetch-ai", "AGIX": "singularitynet", "OCEAN": "ocean-protocol",
    "GRT": "the-graph", "AAVE": "aave", "CRV": "curve-dao-token", "MKR": "maker",
    "LDO": "lido-dao", "RPL": "rocket-pool", "PENDLE": "pendle",
    "HNT": "helium", "MOBILE": "helium-mobile", "IOTX": "iotex",
    "AXS": "axie-infinity", "SAND": "the-sandbox", "MANA": "decentraland",
    "IMX": "immutable-x", "GALA": "gala", "PIXEL": "pixels",
    "ONDO": "ondo-finance", "CFG": "centrifuge", "POLYX": "polymesh-network",
    # Base chain tokens
    "TOSHI": "toshi", "MOCHI": "mochi-the-cat-coin", "AERO": "aerodrome-finance",
    "BRETT": "brett", "DEGEN": "degen-base", "CBETH": "coinbase-wrapped-staked-eth",
    "SATO": "sato", "RUSSELL": "russell-2000-base", "BOOMER": "boomer-2",
    "HIGHER": "higher", "NORMIE": "normie", "BALD": "bald", "DOGINME": "doginme",
    # Solana tokens
    "TINYWORLD": "tiny-world-game", "TRALALERC": "tralalero-tralala",
    "POPCAT": "popcat", "BOME": "book-of-meme", "MYRO": "myro", "SLERF": "slerf",
    "JUP": "jupiter-exchange-solana", "PYTH": "pyth-network",
    "PONKE": "ponke", "MICHI": "michi", "PNUT": "pnut",
    "GOAT": "goatseus-maximus", "AI16Z": "ai16z", "FARTCOIN": "fartcoin",
    "ZEREBRO": "zerebro", "MOODENG": "moodeng", "TURBO": "turbo",
    # Ethereum / multi-chain memecoins
    "FLOKI": "floki", "MOG": "mog-coin", "NEIRO": "neiro-ethereum",
    "BABYDOGE": "baby-doge-coin", "ACT": "act-i-the-ai-prophecy",
    # DeFi / L2 / RWA
    "ENA": "ethena", "EIGEN": "eigenlayer", "W": "wormhole",
    "ZK": "zksync", "DYM": "dymension", "BLAST": "blast",
    # BTC derivatives
    "WBTC": "wrapped-bitcoin",
    # Stablecoins
    "USDT": "tether", "USDC": "usd-coin", "DAI": "dai", "FRAX": "frax",
    "BUSD": "binance-usd", "TUSD": "true-usd", "PYUSD": "paypal-usd",
    "USDS": "usds", "FDUSD": "first-digital-usd", "USDE": "ethena-usde",
}

# Tokens that should NEVER get a price (unknown/unverified memes — avoid false enrichment)
PRICE_BLACKLIST = {
    "ABTC", "ROCKET", "WEIRDO", "EP1", "CLANKS", "COBI", "WGC",
    "MARCOPOLO", "DLM", "WRENG", "ARUSSELL", "EVAINU", "BLACK MAMBA",
}

async def fetch_cmc_quotes(symbols: List[str]) -> dict:
    """Prix via CoinMarketCap (repli pour les actifs absents de CoinGecko/Yahoo,
    ex. RWA tokenisés comme SPACEX). Clé lue dans .env (COINMARKETCAP_API_KEY).
    Renvoie {SYMBOL: {price, change_24h, market_cap, volume_24h}}."""
    if not symbols or not COINMARKETCAP_API_KEY:
        return {}
    # Alias quand le symbole du portefeuille diffère du ticker CMC (RWA / xStocks).
    CMC_ALIAS = {"SPACEX": "SPCX", "SPCXX": "SPCX", "SPCXXX": "SPCX"}
    syms = sorted({s.upper() for s in symbols})
    query_to_orig = {CMC_ALIAS.get(s, s): s for s in syms}
    cache_key = "cmc_" + "_".join(syms)
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 120:
        return _cache[cache_key]["data"]
    out = {}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(
                "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest",
                params={"symbol": ",".join(query_to_orig.keys()), "convert": "USD"},
                headers={"X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY,
                         "Accept": "application/json"})
            payload = r.json().get("data", {}) or {}
        for qsym, orig in query_to_orig.items():
            sym = orig
            entry = payload.get(qsym)
            if isinstance(entry, list):
                entry = entry[0] if entry else None
            if not entry:
                continue
            q = (entry.get("quote") or {}).get("USD") or {}
            if q.get("price") is not None:
                out[sym] = {
                    "price": q.get("price") or 0,
                    "change_24h": q.get("percent_change_24h") or 0,
                    "market_cap": q.get("market_cap") or 0,
                    "volume_24h": q.get("volume_24h") or 0,
                }
        _cache[cache_key] = {"data": out, "ts": time.time()}
    except Exception as e:
        logger.warning(f"CoinMarketCap quotes error: {e}")
    return out


async def fetch_crypto_prices(symbols: List[str]) -> dict:
    if not symbols:
        return {}
    # Filter out blacklisted/unknown tokens
    symbols = [s for s in symbols if s.upper() not in PRICE_BLACKLIST]
    if not symbols:
        return {}
    cache_key = "prices_" + "_".join(sorted(s.upper() for s in symbols))
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 30:
        return _cache[cache_key]["data"]

    # IDs CoinGecko connus, en tolérant les variantes d'exchange (ETH2.S->ETH, XBT->BTC…)
    sym_to_id = {}
    for s in symbols:
        su = s.upper()
        key = su if su in COINGECKO_IDS else _normalize_cex_symbol(su)
        if key in COINGECKO_IDS:
            sym_to_id[su] = COINGECKO_IDS[key]
    ids = list(set(sym_to_id.values()))
    try:
        headers = {}
        if COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ",".join(ids), "vs_currencies": "usd",
                        "include_24hr_change": "true", "include_market_cap": "true",
                        "include_24hr_vol": "true"},
                headers=headers
            )
            data = r.json()
        result = {}
        for sym in symbols:
            cg_id = sym_to_id.get(sym.upper())
            if cg_id and cg_id in data:
                d = data[cg_id]
                result[sym.upper()] = {
                    "price": d.get("usd", 0),
                    "change_24h": d.get("usd_24h_change", 0),
                    "market_cap": d.get("usd_market_cap", 0),
                    "volume_24h": d.get("usd_24h_vol", 0),
                }
        # ── Repli : symboles non mappés (ex. HYPE) -> liste des top coins ──
        unresolved = [s.upper() for s in symbols if s.upper() not in result]
        if unresolved:
            try:
                top = await fetch_top_coins(250)
                by_sym = {}
                for c in top:
                    if isinstance(c, dict):
                        by_sym.setdefault((c.get("symbol") or "").upper(), c)
                for s in unresolved:
                    c = by_sym.get(s) or by_sym.get(_normalize_cex_symbol(s))
                    if c and c.get("current_price"):
                        result[s] = {
                            "price": c.get("current_price", 0),
                            "change_24h": c.get("price_change_percentage_24h", 0),
                            "market_cap": c.get("market_cap", 0),
                            "volume_24h": c.get("total_volume", 0),
                        }
            except Exception as e:
                logger.warning(f"price fallback error: {e}")
        # ── Repli final CoinMarketCap (RWA tokenisés type SPACEX, etc.) ──
        still = [s.upper() for s in symbols if s.upper() not in result]
        if still and COINMARKETCAP_API_KEY:
            cmc = await fetch_cmc_quotes(still)
            for s, d in cmc.items():
                result[s] = d
        _cache[cache_key] = {"data": result, "ts": time.time()}
        return result
    except Exception as e:
        logger.error(f"CoinGecko price error: {e}")
        # stale-while-error : on renvoie le dernier prix connu pour ce set de symboles
        return _cache.get(cache_key, {}).get("data", {})

async def fetch_top_coins(limit: int = 50) -> List[dict]:
    """Mutualisé : UN seul appel markets (base 250) sert toutes les limites (15/50/60/100/250).
    Cache 90 s + stale-while-error + cooldown global anti-429 (respecte Retry-After).
    """
    global _CG_COOLDOWN_UNTIL
    base_key = "top_coins_base"
    cached = _cache.get(base_key)
    fresh = cached and (time.time() - cached["ts"] < 90)
    if not fresh and time.time() >= _CG_COOLDOWN_UNTIL:
        try:
            headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(
                    "https://api.coingecko.com/api/v3/coins/markets",
                    params={"vs_currency": "usd", "order": "market_cap_desc",
                            "per_page": 250, "page": 1,
                            "sparkline": "false", "price_change_percentage": "1h,24h,7d"},
                    headers=headers
                )
            if r.status_code == 429:
                ra = r.headers.get("retry-after", "")
                wait = int(ra) if ra.isdigit() else 60
                _CG_COOLDOWN_UNTIL = time.time() + wait
                logger.warning(f"CoinGecko 429 (markets) — cooldown {wait}s, on sert le cache")
            else:
                data = r.json()
                if isinstance(data, list):
                    _cache[base_key] = {"data": [c for c in data if isinstance(c, dict)],
                                        "ts": time.time()}
                else:
                    _CG_COOLDOWN_UNTIL = time.time() + 60
                    logger.warning(f"top_coins non-list -> cooldown 60s: {str(data)[:100]}")
        except Exception as e:
            _CG_COOLDOWN_UNTIL = time.time() + 30
            logger.error(f"CoinGecko markets error: {e} -> cooldown 30s")
    base = _cache.get(base_key, {}).get("data", [])
    return base[:limit]

async def fetch_fear_greed() -> dict:
    cache_key = "fear_greed"
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 300:
        return _cache[cache_key]["data"]
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get("https://api.alternative.me/fng/?limit=1")
            d = r.json()["data"][0]
        result = {"value": int(d["value"]), "label": d["value_classification"]}
        _cache[cache_key] = {"data": result, "ts": time.time()}
        return result
    except Exception as e:
        logger.warning(f"fear_greed error: {e}")
        return _cache.get(cache_key, {}).get("data", {"value": 50, "label": "Neutral"})

async def fetch_etf_data(symbols: List[str]) -> dict:
    cache_key = "etf_" + "_".join(sorted(symbols))
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 300:
        return _cache[cache_key]["data"]
    if not HAS_YFINANCE:
        return {}

    def _sync_fetch() -> dict:
        # yfinance est SYNCHRONE et bloquant : exécuté dans un thread pour ne
        # pas geler la boucle asyncio (sinon toute l'app se fige).
        result = {}
        import yfinance as yf
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                t = tickers.tickers.get(sym)
                if not t:
                    continue
                hist = t.history(period="5d")
                if hist.empty:
                    continue
                last = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
                change = ((last - prev) / prev * 100) if prev else 0
                ytd_hist = t.history(period="ytd")
                ytd = 0
                if not ytd_hist.empty and len(ytd_hist) > 1:
                    first = float(ytd_hist["Close"].iloc[0])
                    ytd = ((last - first) / first * 100) if first else 0
                result[sym] = {
                    "price": round(last, 2),
                    "change_1d": round(change, 2),
                    "ytd": round(ytd, 2),
                    "volume": int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0,
                }
            except Exception as e:
                logger.warning(f"yfinance {sym}: {e}")
        return result

    try:
        # Timeout global : si Yahoo est lent/rate-limité, on rend la main vite.
        result = await asyncio.wait_for(asyncio.to_thread(_sync_fetch), timeout=12)
        if result:
            _cache[cache_key] = {"data": result, "ts": time.time()}
        return result
    except asyncio.TimeoutError:
        logger.warning("yfinance ETF: timeout — on renvoie sans prix (la liste s'affiche quand même)")
        return _cache.get(cache_key, {}).get("data", {})
    except Exception as e:
        logger.error(f"yfinance batch error: {e}")
        return {}

async def fetch_ohlcv(symbol: str, asset_type: str = "crypto", period: str = "30d") -> List[dict]:
    cache_key = f"ohlcv_{symbol}_{asset_type}_{period}"
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 300:
        return _cache[cache_key]["data"]

    try:
        if asset_type in ("etf", "stock") and HAS_YFINANCE:
            import yfinance as yf
            period_map = {"7d": "7d", "30d": "1mo", "90d": "3mo", "365d": "1y", "1d": "1d"}
            yf_period = period_map.get(period, "1mo")
            interval = "1h" if period == "1d" else "1d"
            hist = yf.Ticker(symbol).history(period=yf_period, interval=interval)
            result = []
            for idx, row in hist.iterrows():
                result.append({
                    "time": int(idx.timestamp()),
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row.get("Volume", 0)),
                })
        else:
            days_map = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365}
            days = days_map.get(period, 30)
            cg_id = COINGECKO_IDS.get(symbol.upper(), symbol.lower())
            headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(
                    f"https://api.coingecko.com/api/v3/coins/{cg_id}/ohlc",
                    params={"vs_currency": "usd", "days": days},
                    headers=headers
                )
                raw = r.json()
            result = []
            if isinstance(raw, list):
                for item in raw:
                    result.append({
                        "time": item[0] // 1000,
                        "open": item[1], "high": item[2],
                        "low": item[3], "close": item[4], "volume": 0
                    })
        _cache[cache_key] = {"data": result, "ts": time.time()}
        return result
    except Exception as e:
        logger.error(f"OHLCV error {symbol}: {e}")
        return []

async def fetch_global_metrics() -> dict:
    cache_key = "global_metrics"
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 120:
        return _cache[cache_key]["data"]
    try:
        headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.coingecko.com/api/v3/global", headers=headers)
            raw = r.json().get("data", {})
        result = {
            "total_market_cap": raw.get("total_market_cap", {}).get("usd", 0),
            "total_volume_24h": raw.get("total_volume", {}).get("usd", 0),
            "btc_dominance": raw.get("market_cap_percentage", {}).get("btc", 0),
            "eth_dominance": raw.get("market_cap_percentage", {}).get("eth", 0),
            "active_coins": raw.get("active_cryptocurrencies", 0),
            "market_cap_change_24h": raw.get("market_cap_change_percentage_24h_usd", 0),
        }
        _cache[cache_key] = {"data": result, "ts": time.time()}
        return result
    except Exception as e:
        logger.error(f"Global metrics error: {e}")
        # stale-while-error : dernière valeur connue plutôt que vide
        return _cache.get(cache_key, {}).get("data", {})

# ══════════════════════════════════════════════════════════════
#  AI ENGINE
# ══════════════════════════════════════════════════════════════
async def build_market_context(symbol: str, asset_type: str) -> dict:
    """Fetch real market data to enrich AI analysis."""
    ctx = {}
    try:
        if asset_type in ("crypto", "memecoin"):
            prices = await fetch_crypto_prices([symbol])
            p = prices.get(symbol.upper(), {})
            ctx["price"] = p.get("price", 0)
            ctx["change_24h"] = p.get("change_24h", 0)
            ctx["market_cap"] = p.get("market_cap", 0)
            ctx["volume_24h"] = p.get("volume_24h", 0)
            ohlcv = await fetch_ohlcv(symbol, asset_type, "30d")
            if ohlcv and len(ohlcv) >= 7:
                closes = [c["close"] for c in ohlcv]
                ctx["price_7d_ago"] = closes[-7] if len(closes) >= 7 else closes[0]
                ctx["price_30d_ago"] = closes[0]
                ctx["change_7d"] = ((closes[-1] - closes[-7]) / closes[-7] * 100) if len(closes) >= 7 else 0
                ctx["change_30d"] = ((closes[-1] - closes[0]) / closes[0] * 100) if closes[0] else 0
                high30 = max(c["high"] for c in ohlcv)
                low30 = min(c["low"] for c in ohlcv)
                ctx["high_30d"] = high30
                ctx["low_30d"] = low30
                ctx["range_position"] = ((closes[-1] - low30) / (high30 - low30) * 100) if (high30 - low30) > 0 else 50
        elif asset_type in ("etf", "stock"):
            etf_data = await fetch_etf_data([symbol])
            d = etf_data.get(symbol, {})
            ctx["price"] = d.get("price", 0)
            ctx["change_1d"] = d.get("change_1d", 0)
            ctx["ytd"] = d.get("ytd", 0)
    except Exception as e:
        logger.warning(f"build_market_context error: {e}")
    return ctx

def _repair_truncated_json(t: str) -> str:
    """Close strings/brackets left open by a truncated model response."""
    import re
    out, stack = [], []
    in_str = escaped = False
    for ch in t:
        if in_str:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack:
                stack.pop()
        out.append(ch)
    if in_str:
        out.append('"')
    s = "".join(out).rstrip().rstrip(",")
    # Drop a dangling key that has no value yet (e.g. ... , "foo": )
    s = re.sub(r',\s*"[^"]*"\s*:?\s*$', "", s)
    s = re.sub(r'\{\s*"[^"]*"\s*:?\s*$', "{", s)
    while stack:
        s += stack.pop()
    return s

def _safe_json_loads(text: str) -> dict:
    """Best-effort parse of model-generated JSON.

    Strips markdown fences, isolates the outermost object, removes trailing
    commas / control chars, and repairs truncated output. Raises on total
    failure so callers can fall back."""
    import re
    t = (text or "").strip()
    if "```" in t:
        for part in t.split("```"):
            p = part.strip()
            if p.startswith("json"):
                t = p[4:].strip()
                break
            if p.startswith("{"):
                t = p
                break
    start = t.find("{")
    if start >= 0:
        end = t.rfind("}")
        t = t[start:end + 1] if end > start else t[start:]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    t = re.sub(r",\s*([}\]])", r"\1", t)  # trailing commas
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return json.loads(_repair_truncated_json(t))

async def ai_analyze(symbol: str, asset_type: str = "crypto", portfolio_context: str = "") -> dict:
    mkt = await build_market_context(symbol, asset_type)

    price_info = ""
    if mkt:
        if asset_type == "crypto":
            price_info = f"""
Données de marché temps réel :
- Prix actuel : ${mkt.get('price', 0):,.2f}
- Variation 24h : {mkt.get('change_24h', 0):+.2f}%
- Variation 7j : {mkt.get('change_7d', 0):+.2f}%
- Variation 30j : {mkt.get('change_30d', 0):+.2f}%
- Capitalisation : ${mkt.get('market_cap', 0):,.0f}
- Volume 24h : ${mkt.get('volume_24h', 0):,.0f}
- Plus haut 30j : ${mkt.get('high_30d', 0):,.2f}
- Plus bas 30j : ${mkt.get('low_30d', 0):,.2f}
- Position dans range 30j : {mkt.get('range_position', 50):.0f}%
"""
        elif asset_type in ("etf", "stock"):
            price_info = f"""
Données de marché temps réel :
- Prix actuel : ${mkt.get('price', 0):,.2f}
- Variation journalière : {mkt.get('change_1d', 0):+.2f}%
- Performance YTD : {mkt.get('ytd', 0):+.2f}%
"""

    prompt = f"""Tu es un analyste financier institutionnel senior chez HR5 Invest, niveau Goldman Sachs ou BlackRock.

Produis une analyse professionnelle et complète de l'actif suivant :

Actif : {symbol.upper()} ({asset_type})
{price_info}
{f'Contexte portefeuille client : {portfolio_context}' if portfolio_context else ''}

Retourne UNIQUEMENT un objet JSON valide, sans texte avant ou après, sans markdown :

{{
  "symbol": "{symbol.upper()}",
  "name": "Nom complet de l'actif",
  "asset_type": "{asset_type}",
  "recommendation": "Acheter|Accumuler|Conserver|Attendre|Réduire|Prendre profits|Sortir",
  "conviction": "Forte|Modérée|Faible",
  "score_global": 0,
  "scores": {{
    "qualite_fondamentale": 0,
    "risque_marche": 0,
    "potentiel_croissance": 0,
    "momentum_technique": 0,
    "adoption_ecosysteme": 0
  }},
  "resume_executif": "2-3 phrases résumant la thèse d'investissement",
  "analyse_fondamentale": "Analyse détaillée des fondamentaux, utilité, équipe, tokenomics/financials",
  "analyse_technique": "Niveaux clés, tendances, supports/résistances, indicateurs",
  "catalyseurs": ["catalyseur 1", "catalyseur 2", "catalyseur 3"],
  "risques_principaux": ["risque 1", "risque 2", "risque 3"],
  "horizon_recommande": "Court terme (1-3 mois)|Moyen terme (3-12 mois)|Long terme (1-3 ans)",
  "strategie_entree": "Description précise des niveaux d'entrée recommandés",
  "gestion_position": {{
    "stop_loss_suggere": 0.0,
    "target_1": 0.0,
    "target_2": 0.0,
    "target_3": 0.0,
    "taille_position_max_pct": 0
  }},
  "prise_de_profits": [
    {{"niveau_pct": 25, "action": "Prendre 15% de la position"}},
    {{"niveau_pct": 50, "action": "Prendre 15% supplémentaire"}},
    {{"niveau_pct": 100, "action": "Prendre 20% supplémentaire"}},
    {{"niveau_pct": 200, "action": "Prendre 25% supplémentaire"}}
  ],
  "comparaison_secteur": "Positionnement vs concurrents directs",
  "narrative_macro": "Impact du contexte macro sur cet actif",
  "score_esg": 0,
  "liquidite": "Haute|Moyenne|Faible",
  "correlation_btc": "Haute|Moyenne|Faible|Negative"
}}

IMPORTANT: Toutes les valeurs textuelles doivent être sur une seule ligne (pas de retour à la ligne dans les strings JSON). Retourne UNIQUEMENT le JSON, rien d'autre."""

    try:
        if not ai_enabled():
            return {"error": "Configurez ANTHROPIC_API_KEY dans le fichier .env"}
        # Deep fundamental analysis -> "analysis" task (Claude first).
        text = await ai_complete(prompt, max_tokens=8000, task="analysis")

        try:
            result = _safe_json_loads(text)
            result["donnees_marche"] = mkt  # Add market data from our own fetch
            return result
        except Exception as e:
            logger.error(f"AI JSON parse error for {symbol}: {e}")
            return _fallback_analysis(symbol, asset_type, mkt)
    except Exception as e:
        logger.error(f"AI analyze error for {symbol}: {e}")
        return _fallback_analysis(symbol, asset_type, mkt, str(e))

def _fallback_analysis(symbol, asset_type, mkt, error=""):
    p = mkt.get("price", 0)
    return {
        "symbol": symbol.upper(), "name": symbol.upper(), "asset_type": asset_type,
        "recommendation": "Conserver", "conviction": "Faible", "score_global": 50,
        "scores": {"qualite_fondamentale": 50, "risque_marche": 50, "potentiel_croissance": 50,
                   "momentum_technique": 50, "adoption_ecosysteme": 50},
        "resume_executif": f"Analyse indisponible temporairement. {error[:80] if error else ''}",
        "analyse_fondamentale": "Configurez une clé API IA dans .env pour obtenir des analyses complètes.",
        "analyse_technique": "Données de marché disponibles dans les métriques.",
        "catalyseurs": [], "risques_principaux": [],
        "horizon_recommande": "Moyen terme (3-12 mois)",
        "strategie_entree": "Analyse manuelle requise",
        "gestion_position": {"stop_loss_suggere": p * 0.85, "target_1": p * 1.25,
                             "target_2": p * 1.5, "target_3": p * 2.0, "taille_position_max_pct": 5},
        "prise_de_profits": [
            {"niveau_pct": 25, "action": "Prendre 15%"},
            {"niveau_pct": 50, "action": "Prendre 15%"},
            {"niveau_pct": 100, "action": "Prendre 20%"},
        ],
        "comparaison_secteur": "", "narrative_macro": "",
        "score_esg": 50, "liquidite": "Moyenne", "correlation_btc": "Haute",
        "donnees_marche": mkt
    }

async def ai_stream_chat(messages: list, context: str = "", portfolio_data: dict = None) -> AsyncGenerator[str, None]:
    portfolio_str = ""
    if portfolio_data and portfolio_data.get("positions"):
        positions = portfolio_data["positions"]
        total = portfolio_data.get("total_value", 0)
        portfolio_str = f"\nPortefeuille client (valeur totale: ${total:,.2f}):\n"
        for pos in positions[:15]:
            portfolio_str += f"- {pos['symbol']}: {pos['quantity']} unités, valeur ${pos.get('value', 0):,.2f}, PnL {pos.get('pnl_pct', 0):+.1f}%\n"

    system = f"""Tu es l'analyste IA senior d'HR5 Invest, une plateforme d'investissement institutionnelle premium.

Ton rôle : conseiller financier expert niveau banque privée, spécialisé en :
- Crypto (BTC, ETH, DeFi, L1/L2, gaming, IA, DePIN, RWA)
- ETF (actions, obligations, sectoriels, thématiques, crypto ETF)
- Stratégies d'investissement (DCA, swing, long terme, arbitrage)
- Gestion de risque et allocation de portefeuille
- Analyse on-chain et fondamentale

Règles de communication :
- Réponds en français, ton professionnel mais accessible
- Sois précis, chiffré, actionnable
- Utilise des tableaux markdown quand pertinent
- Fournis des niveaux de prix concrets quand tu analyses un actif
- Mentionne toujours les risques
- Ne donne pas de conseils financiers génériques — sois spécifique et expert
{portfolio_str}
Date : {datetime.now().strftime('%d/%m/%Y %H:%M')}
{f'Contexte additionnel : {context}' if context else ''}"""

    async def _complete_msgs(provider: str) -> str:
        """Full (non-streaming) completion for one provider — easier to bound
        with a timeout so a hanging model can't freeze the chat forever."""
        if provider == "anthropic":
            client = anthropic_sdk.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            msg = await client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=3000, system=system, messages=messages)
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        if provider == "openai":
            client = AsyncOpenAI(api_key=OPENAI_API_KEY)
            resp = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "system", "content": system}] + messages, max_tokens=3000)
            return resp.choices[0].message.content or ""
        # gemini
        genai_sdk.configure(api_key=GEMINI_API_KEY)
        gm = genai_sdk.GenerativeModel(GEMINI_MODEL, system_instruction=system or None)
        history = [{"role": "model" if m["role"] == "assistant" else "user",
                    "parts": [m["content"]]} for m in messages]
        resp = await gm.generate_content_async(history)
        return resp.text or ""

    order = [p for p in dict.fromkeys(AI_TASK_ROUTING.get("chat", AI_TASK_ROUTING["default"]))
             if _provider_available(p)]
    if not order:
        yield f"data: {json.dumps({'content': 'Configurez une clé IA (ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY) dans le fichier .env'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    last_err = None
    for provider in order:
        try:
            # Timeout strict : un modèle qui ne répond pas en 30s -> on bascule.
            text = await asyncio.wait_for(_complete_msgs(provider), timeout=30)
            if text and text.strip():
                # Émission en petits morceaux pour garder l'effet "live".
                for i in range(0, len(text), 48):
                    yield f"data: {json.dumps({'content': text[i:i+48]})}\n\n"
                    await asyncio.sleep(0)
                yield "data: [DONE]\n\n"
                return
            logger.warning(f"AI chat: {provider} a renvoyé une réponse vide, fallback…")
        except asyncio.TimeoutError:
            last_err = f"{provider}: délai dépassé (30s)"
            logger.warning(f"AI chat: {provider} timeout 30s, fallback…")
        except Exception as e:
            last_err = e
            logger.warning(f"AI chat: provider {provider} a échoué ({e}); fallback…")
    yield f"data: {json.dumps({'content': 'Erreur IA : ' + (str(last_err) if last_err else 'aucune réponse des modèles. Vérifie tes clés/quotas dans .env.')})}\n\n"
    yield "data: [DONE]\n\n"

async def generate_dca_plan(symbol: str, capital: float, horizon_months: int, risk: str) -> dict:
    prompt = f"""Tu es un analyste DCA institutionnel. Génère un plan DCA optimal.

Actif : {symbol}
Capital disponible : ${capital:,.2f}
Horizon : {horizon_months} mois
Tolérance au risque : {risk}

Retourne UNIQUEMENT un JSON :
{{
  "symbol": "{symbol}",
  "resume": "Résumé du plan en 2 phrases",
  "montant_par_periode": 0,
  "frequence": "hebdomadaire|bi-mensuel|mensuel",
  "nb_achats": 0,
  "allocation_initiale_pct": 0,
  "reserve_correction_pct": 0,
  "strategie": "Description de la stratégie",
  "calendrier": [
    {{"mois": 1, "action": "Acheter X% du budget", "montant": 0, "condition": "Si prix < X$"}},
    {{"mois": 2, "action": "...", "montant": 0, "condition": "..."}}
  ],
  "conseils_avances": ["conseil 1", "conseil 2", "conseil 3"],
  "scenario_bull": "Résultat estimé si marché haussier",
  "scenario_bear": "Résultat estimé si marché baissier",
  "stop_dca": "Condition d'arret du DCA"
}}

IMPORTANT: Toutes les valeurs texte sur une seule ligne. Retourne UNIQUEMENT le JSON."""
    try:
        if not ai_enabled():
            return {"error": "Provider IA non configuré"}
        text = await ai_complete(prompt, max_tokens=4000, task="analysis")
        return _safe_json_loads(text)
    except Exception as e:
        logger.error(f"DCA plan error: {e}")
        return {"error": str(e)}

def _fallback_portfolio_analysis(enriched: dict, error: str = "") -> dict:
    """Deterministic, rule-based portfolio analysis — always returns something,
    even with no AI key or on AI failure."""
    positions = enriched.get("positions", []) or []
    tv = enriched.get("total_value", 0) or 0
    tpnl_pct = enriched.get("total_pnl_pct", 0) or 0
    ranked = sorted(positions, key=lambda p: p.get("allocation_pct", 0) or 0, reverse=True)
    top = ranked[0] if ranked else None
    top_alloc = (top.get("allocation_pct", 0) or 0) if top else 0
    if top_alloc >= 60:
        risk = "Très élevé"
    elif top_alloc >= 40:
        risk = "Élevé"
    elif top_alloc >= 25:
        risk = "Modéré"
    else:
        risk = "Faible"

    forts, faibles, recos, verdicts = [], [], [], []
    if len(positions) >= 8:
        forts.append(f"Portefeuille réparti sur {len(positions)} positions.")
    else:
        faibles.append(f"Faible diversification : seulement {len(positions)} position(s).")
    if top and top_alloc >= 40:
        faibles.append(f"Forte concentration : {top['symbol']} pèse {top_alloc:.0f}% du portefeuille.")
        recos.append({"priorite": "Haute", "action": f"Alléger {top['symbol']}",
                      "symbol": top["symbol"],
                      "raison": f"{top_alloc:.0f}% sur un seul actif — risque de concentration trop élevé."})
    winners = [p for p in positions if (p.get("pnl_pct") or 0) > 0]
    losers = [p for p in positions if (p.get("pnl_pct") or 0) < 0]
    if winners:
        forts.append(f"{len(winners)} position(s) en plus-value.")
    for p in sorted(losers, key=lambda x: x.get("pnl_pct", 0) or 0)[:3]:
        recos.append({"priorite": "Moyenne",
                      "action": f"Réévaluer {p['symbol']} (perte {(p.get('pnl_pct') or 0):.0f}%)",
                      "symbol": p["symbol"],
                      "raison": "Position perdante : couper la perte ou renforcer selon la conviction."})
    micro = [p for p in positions if 0 < (p.get("value") or 0) < max(1.0, tv * 0.01)]
    if len(micro) >= 3:
        faibles.append(f"{len(micro)} 'poussières' (positions < 1% chacune) qui alourdissent le suivi.")

    for p in ranked:
        a = p.get("allocation_pct", 0) or 0
        pnl = p.get("pnl_pct") or 0
        if a >= 40:
            verdict = "Alléger"
        elif pnl <= -60:
            verdict = "Vendre"
        elif pnl >= 30:
            verdict = "Conserver"
        else:
            verdict = "Conserver"
        verdicts.append({"symbol": p["symbol"], "allocation_pct": round(a, 1),
                         "pnl_pct": round(pnl, 1), "verdict": verdict,
                         "commentaire": f"{a:.0f}% du portef. · PnL {pnl:+.0f}%"})

    note = 50
    if risk in ("Très élevé", "Élevé"):
        note -= 15
    if len(positions) >= 8:
        note += 10
    note += 10 if tpnl_pct > 0 else (-5 if tpnl_pct < 0 else 0)
    note = max(10, min(90, note))

    return {
        "synthese": (f"Portefeuille de ${tv:,.2f} réparti sur {len(positions)} position(s), "
                     f"PnL global {tpnl_pct:+.1f}%. Risque {risk.lower()} "
                     f"(plus grosse ligne : {top_alloc:.0f}%)."
                     + (f" [Analyse simplifiée — IA indisponible : {error[:60]}]" if error else "")),
        "note_globale": note,
        "niveau_risque": risk,
        "diversification": f"{len(positions)} position(s), concentration maximale {top_alloc:.0f}%.",
        "points_forts": forts or ["Aucun point fort marquant détecté."],
        "points_faibles": faibles or ["Aucune faiblesse majeure détectée."],
        "recommandations": recos or [{"priorite": "Basse", "action": "Conserver l'allocation actuelle",
                                      "symbol": "", "raison": "Aucune action urgente détectée."}],
        "positions": verdicts,
        "allocation_cible": "Viser 8 à 12 lignes, chacune < 25%, et nettoyer les poussières.",
        "_source": "fallback",
    }

async def ai_analyze_portfolio(enriched: dict) -> dict:
    """Full-portfolio AI analysis returning structured JSON. Falls back to a
    deterministic analysis if the AI is unavailable or fails."""
    positions = enriched.get("positions", []) or []
    tv = enriched.get("total_value", 0) or 0
    tpnl_pct = enriched.get("total_pnl_pct", 0) or 0

    if not ai_enabled():
        return _fallback_portfolio_analysis(enriched, "clé API non configurée")

    lines = []
    for p in sorted(positions, key=lambda x: x.get("allocation_pct", 0) or 0, reverse=True):
        lines.append(
            f"- {p['symbol']} ({p.get('asset_type','crypto')}): {(p.get('allocation_pct') or 0):.1f}% du portef., "
            f"valeur ${(p.get('value') or 0):,.2f}, PnL {(p.get('pnl_pct') or 0):+.1f}%, "
            f"qté {p.get('quantity',0)}, prix moyen ${p.get('avg_cost',0)}, prix actuel ${p.get('current_price',0)}")
    block = "\n".join(lines) if lines else "(aucune position)"

    prompt = f"""Tu es l'analyste senior d'HR5 Invest, bureau d'investissement institutionnel.
Analyse le portefeuille client ci-dessous et fournis des recommandations concrètes et actionnables.

Valeur totale : ${tv:,.2f}
PnL global : {tpnl_pct:+.1f}%
Nombre de positions : {len(positions)}

Positions :
{block}

Retourne UNIQUEMENT un objet JSON valide, sans texte ni markdown autour :
{{
  "synthese": "3-4 phrases sur l'état global, l'exposition et le profil de risque",
  "note_globale": 0,
  "niveau_risque": "Faible|Modéré|Élevé|Très élevé",
  "diversification": "évaluation de la diversification et de la concentration",
  "points_forts": ["point fort 1", "point fort 2"],
  "points_faibles": ["point faible 1", "point faible 2"],
  "recommandations": [
    {{"priorite": "Haute|Moyenne|Basse", "action": "action concrète à faire", "symbol": "SYMBOLE concerné ou vide", "raison": "justification courte"}}
  ],
  "positions": [
    {{"symbol": "SYMBOLE", "allocation_pct": 0, "pnl_pct": 0, "verdict": "Conserver|Renforcer|Alléger|Vendre", "commentaire": "avis en une phrase"}}
  ],
  "allocation_cible": "recommandation d'allocation cible idéale"
}}

Couvre TOUTES les positions dans le tableau "positions". Réponds en français.
IMPORTANT : toutes les valeurs texte sur une seule ligne. Retourne UNIQUEMENT le JSON."""

    try:
        text = await ai_complete(prompt, max_tokens=8000, task="analysis")
        result = _safe_json_loads(text)
        result["_source"] = "ai"
        return result
    except Exception as e:
        logger.error(f"Portfolio analysis error: {e}")
        return _fallback_portfolio_analysis(enriched, str(e))

# ══════════════════════════════════════════════════════════════
#  PYDANTIC MODELS
# ══════════════════════════════════════════════════════════════
class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str
    full_name: str = ""

class LoginRequest(BaseModel):
    email: str
    password: str

class PortfolioCreate(BaseModel):
    name: str
    description: str = ""
    currency: str = "USD"
    benchmark: str = "BTC"

class PositionAdd(BaseModel):
    symbol: str
    asset_type: str = "crypto"
    name: str = ""
    quantity: float
    avg_cost: float
    sector: str = ""
    notes: str = ""

class TransactionAdd(BaseModel):
    portfolio_id: int
    symbol: str
    asset_type: str = "crypto"
    tx_type: str  # buy|sell|transfer_in|transfer_out|stake|unstake
    quantity: float
    price: float
    fees: float = 0
    exchange: str = ""
    notes: str = ""
    tx_date: str = ""

class WatchlistRequest(BaseModel):
    symbol: str
    asset_type: str = "crypto"
    name: str = ""
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    notes: str = ""

class AlertRequest(BaseModel):
    symbol: str
    alert_type: str
    threshold: Optional[float] = None
    message: str = ""

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    context: str = ""
    include_portfolio: bool = False
    portfolio_id: Optional[int] = None

class AnalyzeRequest(BaseModel):
    symbol: str
    asset_type: str = "crypto"
    portfolio_context: str = ""

class DCARequest(BaseModel):
    symbol: str
    capital: float
    horizon_months: int
    risk_level: str = "modéré"

class PortfolioAnalyzeRequest(BaseModel):
    portfolio_id: Optional[int] = None

class SimAccountRequest(BaseModel):
    name: str
    initial_capital: float = 10000
    currency: str = "USD"

class SimTradeRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: float

# ══════════════════════════════════════════════════════════════
#  PORTFOLIO HELPERS
# ══════════════════════════════════════════════════════════════
async def enrich_portfolio(portfolio_id: int, positions_rows: list) -> dict:
    """Add live prices and compute PnL for a portfolio."""
    positions = [dict(r) for r in positions_rows]
    crypto_syms = [p["symbol"] for p in positions if p["asset_type"] == "crypto"]
    etf_syms = [p["symbol"] for p in positions if p["asset_type"] in ("etf", "stock")]
    # Nom toujours présent : on complète depuis le cache marché (CoinGecko)
    name_map = {}
    try:
        for c in (_cache.get("top_coins_base", {}).get("data") or []):
            if isinstance(c, dict) and c.get("symbol"):
                name_map[c["symbol"].upper()] = c.get("name")
    except Exception:
        pass

    crypto_prices, etf_prices = {}, {}
    tasks = []
    if crypto_syms:
        crypto_prices = await fetch_crypto_prices(crypto_syms)
    if etf_syms:
        etf_prices = await fetch_etf_data(etf_syms)
        # Repli CoinMarketCap pour actions/ETF absents de Yahoo (ex. RWA tokenisés : SPACEX)
        missing_etf = [s.upper() for s in etf_syms if s.upper() not in etf_prices]
        if missing_etf and COINMARKETCAP_API_KEY:
            for s, d in (await fetch_cmc_quotes(missing_etf)).items():
                etf_prices[s] = d

    total_value = 0
    total_cost = 0
    for p in positions:
        sym = p["symbol"].upper()
        if not (p.get("name") or "").strip():
            p["name"] = name_map.get(sym) or sym
        if p["asset_type"] == "crypto":
            d = crypto_prices.get(sym, {})
            live_price = d.get("price", 0)
            # Use live price if found; otherwise fall back to stored price (not avg_cost to avoid confusion)
            stored_price = p.get("current_price") or 0
            p["current_price"] = live_price if live_price > 0 else stored_price
            p["change_24h"] = d.get("change_24h", 0)
            p["market_cap"] = d.get("market_cap", 0)
            p["volume_24h"] = d.get("volume_24h", 0)
            p["price_live"] = live_price > 0
        else:
            d = etf_prices.get(sym, {})
            p["current_price"] = d.get("price", p.get("avg_cost") or 0)
            p["change_24h"] = d.get("change_1d", 0)
            p["market_cap"] = 0
            p["volume_24h"] = d.get("volume", 0)
            p["price_live"] = bool(d)

        qty = p["quantity"] or 0
        price = p["current_price"] or 0
        avg = p["avg_cost"] or 0

        p["value"] = round(price * qty, 8)
        cost = round(avg * qty, 8)
        p["cost_basis"] = cost
        pnl = p["value"] - cost
        # Round tiny floating point noise to zero
        if abs(pnl) < 1e-6:
            pnl = 0.0
        p["pnl"] = round(pnl, 4)
        p["pnl_pct"] = round(((p["value"] - cost) / cost * 100), 4) if cost > 0 else 0
        total_value += p["value"]
        total_cost += cost

    # Allocation %
    for p in positions:
        p["allocation_pct"] = (p["value"] / total_value * 100) if total_value else 0

    total_pnl = round(total_value - total_cost, 4)
    if abs(total_pnl) < 1e-4:
        total_pnl = 0.0
    return {
        "positions": positions,
        "total_value": round(total_value, 4),
        "total_cost": round(total_cost, 4),
        "total_pnl": total_pnl,
        "total_pnl_pct": round(((total_value - total_cost) / total_cost * 100), 4) if total_cost > 0 else 0,
        "position_count": len(positions),
    }

def parse_csv_portfolio(content: str) -> List[dict]:
    """Parse CSV exports from Binance/Coinbase/generic."""
    positions = {}
    reader = csv.DictReader(io.StringIO(content))
    headers = [h.lower().strip() for h in (reader.fieldnames or [])]

    sym_col = next((h for h in headers if any(k in h for k in ["symbol","coin","asset","ticker","currency"])), None)
    qty_col = next((h for h in headers if any(k in h for k in ["quantity","amount","qty","holding","balance","total"])), None)
    price_col = next((h for h in headers if any(k in h for k in ["price","cost","avg","average","purchase"])), None)
    type_col = next((h for h in headers if any(k in h for k in ["type","side","operation"])), None)

    for row in reader:
        row_lower = {k.lower().strip(): v for k, v in row.items()}
        sym = (row_lower.get(sym_col) or "").upper().strip()
        if not sym:
            continue
        try:
            qty = float(str(row_lower.get(qty_col) or "0").replace(",", ""))
            price = float(str(row_lower.get(price_col) or "0").replace(",", "").replace("$", ""))
        except:
            continue

        tx_type = str(row_lower.get(type_col, "buy")).lower()
        if "sell" in tx_type or "vente" in tx_type:
            qty = -qty

        if sym not in positions:
            positions[sym] = {"symbol": sym, "total_qty": 0, "total_cost": 0, "count": 0}
        if qty > 0:
            positions[sym]["total_qty"] += qty
            positions[sym]["total_cost"] += qty * price
            positions[sym]["count"] += 1
        else:
            positions[sym]["total_qty"] += qty  # negative = reduce

    result = []
    for sym, d in positions.items():
        if d["total_qty"] > 0:
            avg = (d["total_cost"] / d["total_qty"]) if d["total_qty"] else 0
            result.append({"symbol": sym, "quantity": round(d["total_qty"], 8),
                          "avg_cost": round(avg, 6), "asset_type": "crypto"})
    return result

# ══════════════════════════════════════════════════════════════
#  APP
# ══════════════════════════════════════════════════════════════
async def _cache_refresher():
    """Rafraîchisseur PARTAGÉ : alimente les caches chauds en arrière-plan, hors
    chemin utilisateur. Retry/backoff via le cooldown global (Retry-After respecté
    dans fetch_top_coins). Les requêtes frontend servent toujours le cache.
    """
    await asyncio.sleep(2)  # laisse le serveur démarrer
    while True:
        try:
            await fetch_top_coins(250)      # alimente le cache markets mutualisé
            await fetch_global_metrics()
            await fetch_fear_greed()
        except Exception as e:
            logger.warning(f"cache_refresher: {e}")
        # ~80 s (juste sous le TTL de 90 s) ; on attend la fin du cooldown si 429
        delay = 80
        if time.time() < _CG_COOLDOWN_UNTIL:
            delay = max(80, int(_CG_COOLDOWN_UNTIL - time.time()) + 5)
        await asyncio.sleep(delay)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("🚀 HR5 Invest Institutional Desk — http://localhost:8000")
    _task = asyncio.create_task(_cache_refresher())
    try:
        yield
    finally:
        _task.cancel()

def _json_sanitize(o):
    """Replace NaN/Infinity (e.g. from yfinance on delisted symbols) with None.
    Starlette's JSONResponse uses allow_nan=False and crashes otherwise."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _json_sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_sanitize(v) for v in o]
    return o

class SafeJSONResponse(JSONResponse):
    """Default response class: never let a NaN/Inf break a whole response."""
    def render(self, content) -> bytes:
        return super().render(_json_sanitize(content))

app = FastAPI(title="HR5 Invest Institutional API", version="2.0.0",
              lifespan=lifespan, default_response_class=SafeJSONResponse)

app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    """Force browsers to always refetch the app shell so UI updates land
    without a manual hard-refresh."""
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if "text/html" in ct or request.url.path in ("/", "/index.html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ══════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════════
@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0", "time": datetime.now().isoformat()}

@app.get("/api/v1/debug/price/{symbol}")
async def debug_price(symbol: str):
    """Diagnostic (sans secret) : ce que chaque source renvoie pour un symbole.
    Ex: /api/v1/debug/price/SPACEX"""
    sym = symbol.upper()
    cg = await fetch_crypto_prices([sym])
    yf = await fetch_etf_data([sym])
    cmc = await fetch_cmc_quotes([sym])
    return {
        "symbol": sym,
        "keys_loaded": {
            "coinmarketcap": bool(COINMARKETCAP_API_KEY),
            "coingecko": bool(COINGECKO_API_KEY),
        },
        "coingecko": cg.get(sym),
        "yahoo_finance": yf.get(sym),
        "coinmarketcap": cmc.get(sym),
        "note": "Le prix retenu = CoinGecko/Yahoo, sinon CoinMarketCap.",
    }

@app.get("/api/v1/ai/status")
async def ai_status():
    """Expose configured AI providers and the active task routing."""
    return {
        "enabled": ai_enabled(),
        "providers": {
            "anthropic": {"available": _provider_available("anthropic"), "model": ANTHROPIC_MODEL},
            "openai": {"available": _provider_available("openai"), "model": OPENAI_MODEL},
            "gemini": {"available": _provider_available("gemini"), "model": GEMINI_MODEL},
        },
        "routing": AI_TASK_ROUTING,
    }

@app.post("/api/v1/auth/register")
async def register(req: RegisterRequest):
    conn = get_db()
    if conn.execute("SELECT id FROM users WHERE email=? OR username=?", (req.email, req.username)).fetchone():
        conn.close()
        raise HTTPException(400, "Email ou username déjà utilisé")
    hashed = pwd_context.hash(req.password[:72])
    conn.execute("INSERT INTO users (email, username, hashed_password, full_name) VALUES (?,?,?,?)",
                 (req.email, req.username, hashed, req.full_name))
    conn.commit()
    uid = conn.execute("SELECT id FROM users WHERE email=?", (req.email,)).fetchone()["id"]
    conn.execute("INSERT INTO portfolios (user_id, name, is_default) VALUES (?,?,1)",
                 (uid, f"Portefeuille de {req.full_name or req.username}"))
    conn.commit()
    conn.close()
    return {"access_token": create_token({"sub": str(uid)}), "token_type": "bearer"}

@app.post("/api/v1/auth/login")
async def login(req: LoginRequest):
    user = get_user_by_email(req.email)
    if not user or not pwd_context.verify(req.password[:72], user["hashed_password"]):
        raise HTTPException(401, "Email ou mot de passe incorrect")
    token = create_token({"sub": str(user["id"])})
    return {
        "access_token": token, "token_type": "bearer",
        "user": {"id": user["id"], "email": user["email"], "username": user["username"],
                 "full_name": user["full_name"], "is_admin": bool(user["is_admin"]),
                 "subscription": user["subscription"]}
    }

@app.get("/api/v1/auth/me")
async def me(user=Depends(get_current_user)):
    return {"id": user["id"], "email": user["email"], "username": user["username"],
            "full_name": user["full_name"], "is_admin": bool(user["is_admin"]),
            "subscription": user["subscription"]}

# ══════════════════════════════════════════════════════════════
#  PORTFOLIO ROUTES
# ══════════════════════════════════════════════════════════════
@app.get("/api/v1/portfolios")
async def list_portfolios(user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM portfolios WHERE user_id=? ORDER BY is_default DESC, created_at",
                        (user["id"],)).fetchall()
    conn.close()
    return {"portfolios": [dict(r) for r in rows]}

@app.post("/api/v1/portfolios")
async def create_portfolio(req: PortfolioCreate, user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("INSERT INTO portfolios (user_id, name, description, currency, benchmark) VALUES (?,?,?,?,?)",
                 (user["id"], req.name, req.description, req.currency, req.benchmark))
    conn.commit()
    pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"id": pid, "success": True}

@app.delete("/api/v1/portfolios/{pid}")
async def delete_portfolio(pid: int, user=Depends(get_current_user)):
    conn = get_db()
    p = conn.execute("SELECT * FROM portfolios WHERE id=? AND user_id=?", (pid, user["id"])).fetchone()
    if not p:
        raise HTTPException(404, "Portefeuille introuvable")
    if p["is_default"]:
        raise HTTPException(400, "Impossible de supprimer le portefeuille principal")
    conn.execute("DELETE FROM portfolio_positions WHERE portfolio_id=?", (pid,))
    conn.execute("DELETE FROM portfolios WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/v1/portfolios/{pid}")
async def get_portfolio(pid: int, user=Depends(get_current_user)):
    conn = get_db()
    portfolio = conn.execute("SELECT * FROM portfolios WHERE id=? AND user_id=?",
                             (pid, user["id"])).fetchone()
    if not portfolio:
        raise HTTPException(404, "Portefeuille introuvable")
    positions = conn.execute("SELECT * FROM portfolio_positions WHERE portfolio_id=?", (pid,)).fetchall()
    conn.close()
    enriched = await enrich_portfolio(pid, positions)
    enriched["portfolio"] = dict(portfolio)
    return enriched

@app.get("/api/v1/portfolios/default/summary")
async def default_portfolio(user=Depends(get_current_user)):
    conn = get_db()
    portfolio = conn.execute("SELECT * FROM portfolios WHERE user_id=? AND is_default=1",
                             (user["id"],)).fetchone()
    if not portfolio:
        portfolio = conn.execute("SELECT * FROM portfolios WHERE user_id=? LIMIT 1",
                                 (user["id"],)).fetchone()
    if not portfolio:
        conn.close()
        return {"positions": [], "total_value": 0, "total_cost": 0,
                "total_pnl": 0, "total_pnl_pct": 0, "portfolio": None}
    positions = conn.execute("SELECT * FROM portfolio_positions WHERE portfolio_id=?",
                             (portfolio["id"],)).fetchall()
    conn.close()
    enriched = await enrich_portfolio(portfolio["id"], positions)
    enriched["portfolio"] = dict(portfolio)
    return enriched


@app.get("/api/v1/portfolios/default/equity-curve")
async def default_equity_curve(days: int = 90, user=Depends(get_current_user)):
    """Reconstitue la valeur du portefeuille sur `days` jours à partir de
    l'historique des actifs (best-effort). Les actifs sans historique fiable
    sont comptés à plat à leur valeur actuelle. Résultat caché 15 min."""
    conn = get_db()
    pf = conn.execute("SELECT * FROM portfolios WHERE user_id=? AND is_default=1",
                      (user["id"],)).fetchone() or \
         conn.execute("SELECT * FROM portfolios WHERE user_id=? LIMIT 1", (user["id"],)).fetchone()
    if not pf:
        conn.close()
        return {"points": []}
    rows = conn.execute("SELECT * FROM portfolio_positions WHERE portfolio_id=?",
                        (pf["id"],)).fetchall()
    conn.close()

    ck = f"equity_{pf['id']}_{days}"
    if ck in _cache and time.time() - _cache[ck]["ts"] < 900:
        return _cache[ck]["data"]

    enriched = await enrich_portfolio(pf["id"], rows)
    pos = enriched.get("positions", [])
    hist_series = []   # listes de valeurs (qty*close) alignables
    flat_total = 0.0
    for p in pos:
        qty = p.get("quantity") or 0
        cur_val = p.get("value") or 0
        closes = []
        if p.get("asset_type") == "crypto" and qty > 0:
            try:
                s = await asyncio.wait_for(fetch_close_series(p["symbol"], days), timeout=8)
                closes = [c["close"] for c in s if c.get("close")]
            except Exception:
                closes = []
        if len(closes) >= 10:
            hist_series.append([qty * c for c in closes[-days:]])
        else:
            flat_total += cur_val

    points = []
    if hist_series:
        n = min(len(s) for s in hist_series)
        for i in range(n):
            day_val = sum(s[len(s) - n + i] for s in hist_series) + flat_total
            points.append(round(day_val, 2))
    elif flat_total:
        points = [round(flat_total, 2)]

    out = {"points": points, "days": days,
           "current": round(enriched.get("total_value") or 0, 2)}
    _cache[ck] = {"data": out, "ts": time.time()}
    return out

@app.post("/api/v1/portfolios/{pid}/positions")
async def add_position(pid: int, req: PositionAdd, user=Depends(get_current_user)):
    conn = get_db()
    if not conn.execute("SELECT id FROM portfolios WHERE id=? AND user_id=?", (pid, user["id"])).fetchone():
        conn.close()
        raise HTTPException(403, "Accès refusé")
    conn.execute("""INSERT INTO portfolio_positions
        (portfolio_id, symbol, asset_type, name, quantity, avg_cost, sector, notes)
        VALUES (?,?,?,?,?,?,?,?)""",
        (pid, req.symbol.upper(), req.asset_type, req.name, req.quantity, req.avg_cost, req.sector, req.notes))
    conn.commit()
    conn.close()
    return {"success": True}

@app.put("/api/v1/portfolios/{pid}/positions/{pos_id}")
async def update_position(pid: int, pos_id: int, req: PositionAdd, user=Depends(get_current_user)):
    conn = get_db()
    if not conn.execute("SELECT id FROM portfolios WHERE id=? AND user_id=?", (pid, user["id"])).fetchone():
        conn.close()
        raise HTTPException(403, "Accès refusé")
    conn.execute("""UPDATE portfolio_positions SET symbol=?, asset_type=?, name=?,
        quantity=?, avg_cost=?, sector=?, notes=? WHERE id=? AND portfolio_id=?""",
        (req.symbol.upper(), req.asset_type, req.name, req.quantity, req.avg_cost,
         req.sector, req.notes, pos_id, pid))
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/v1/portfolios/{pid}/positions/{pos_id}")
async def delete_position(pid: int, pos_id: int, user=Depends(get_current_user)):
    conn = get_db()
    if not conn.execute("SELECT id FROM portfolios WHERE id=? AND user_id=?", (pid, user["id"])).fetchone():
        conn.close()
        raise HTTPException(403, "Accès refusé")
    conn.execute("DELETE FROM portfolio_positions WHERE id=? AND portfolio_id=?", (pos_id, pid))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/api/v1/portfolios/{pid}/import-csv")
async def import_csv(pid: int, file: UploadFile = File(...), user=Depends(get_current_user)):
    conn = get_db()
    if not conn.execute("SELECT id FROM portfolios WHERE id=? AND user_id=?", (pid, user["id"])).fetchone():
        conn.close()
        raise HTTPException(403, "Accès refusé")
    content = (await file.read()).decode("utf-8", errors="ignore")
    positions = parse_csv_portfolio(content)
    if not positions:
        conn.close()
        raise HTTPException(400, "Aucune position valide trouvée dans le fichier CSV")
    inserted = 0
    for pos in positions:
        conn.execute("""INSERT INTO portfolio_positions
            (portfolio_id, symbol, asset_type, quantity, avg_cost)
            VALUES (?,?,?,?,?)""",
            (pid, pos["symbol"], pos["asset_type"], pos["quantity"], pos["avg_cost"]))
        inserted += 1
    conn.commit()
    conn.close()
    return {"success": True, "imported": inserted, "positions": positions}

@app.post("/api/v1/transactions")
async def add_transaction(req: TransactionAdd, user=Depends(get_current_user)):
    conn = get_db()
    if not conn.execute("SELECT id FROM portfolios WHERE id=? AND user_id=?",
                        (req.portfolio_id, user["id"])).fetchone():
        conn.close()
        raise HTTPException(403, "Accès refusé")
    total = req.quantity * req.price + req.fees
    tx_date = req.tx_date or datetime.now().isoformat()
    conn.execute("""INSERT INTO transactions
        (portfolio_id, symbol, asset_type, tx_type, quantity, price, fees, total, exchange, notes, tx_date)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (req.portfolio_id, req.symbol.upper(), req.asset_type, req.tx_type,
         req.quantity, req.price, req.fees, total, req.exchange, req.notes, tx_date))

    # Update position
    existing = conn.execute("""SELECT * FROM portfolio_positions
        WHERE portfolio_id=? AND symbol=?""", (req.portfolio_id, req.symbol.upper())).fetchone()

    if req.tx_type in ("buy", "transfer_in", "stake"):
        if existing:
            old_qty = existing["quantity"]
            old_cost = existing["avg_cost"]
            new_qty = old_qty + req.quantity
            new_avg = ((old_qty * old_cost) + (req.quantity * req.price)) / new_qty if new_qty else 0
            conn.execute("UPDATE portfolio_positions SET quantity=?, avg_cost=? WHERE id=?",
                         (new_qty, new_avg, existing["id"]))
        else:
            conn.execute("""INSERT INTO portfolio_positions
                (portfolio_id, symbol, asset_type, quantity, avg_cost) VALUES (?,?,?,?,?)""",
                (req.portfolio_id, req.symbol.upper(), req.asset_type, req.quantity, req.price))
    elif req.tx_type in ("sell", "transfer_out", "unstake") and existing:
        new_qty = max(0, existing["quantity"] - req.quantity)
        if new_qty == 0:
            conn.execute("DELETE FROM portfolio_positions WHERE id=?", (existing["id"],))
        else:
            conn.execute("UPDATE portfolio_positions SET quantity=? WHERE id=?",
                         (new_qty, existing["id"]))

    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/v1/portfolios/{pid}/transactions")
async def get_transactions(pid: int, user=Depends(get_current_user)):
    conn = get_db()
    if not conn.execute("SELECT id FROM portfolios WHERE id=? AND user_id=?", (pid, user["id"])).fetchone():
        conn.close()
        raise HTTPException(403, "Accès refusé")
    rows = conn.execute("""SELECT * FROM transactions WHERE portfolio_id=?
        ORDER BY tx_date DESC LIMIT 200""", (pid,)).fetchall()
    conn.close()
    return {"transactions": [dict(r) for r in rows]}

# ══════════════════════════════════════════════════════════════
#  MARKET ROUTES
# ══════════════════════════════════════════════════════════════
@app.get("/api/v1/market/global")
async def global_metrics():
    return await fetch_global_metrics()

@app.get("/api/v1/market/coins")
async def market_coins(limit: int = 50):
    coins = await fetch_top_coins(limit)
    return {"coins": coins}

@app.get("/api/v1/market/fear-greed")
async def fear_greed():
    return await fetch_fear_greed()

@app.get("/api/v1/market/ohlcv/{symbol}")
async def ohlcv(symbol: str, asset_type: str = "crypto", period: str = "30d"):
    data = await fetch_ohlcv(symbol.upper(), asset_type, period)
    return {"symbol": symbol.upper(), "period": period, "data": data}

@app.get("/api/v1/market/etf")
async def etf_list():
    ETF_UNIVERSE = [
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "category": "US Large Cap", "aum": "560B"},
        {"symbol": "QQQ", "name": "Invesco QQQ Trust (Nasdaq-100)", "category": "Tech/Growth", "aum": "250B"},
        {"symbol": "IBIT", "name": "iShares Bitcoin Trust", "category": "Crypto — BTC", "aum": "40B"},
        {"symbol": "FBTC", "name": "Fidelity Wise Origin Bitcoin Fund", "category": "Crypto — BTC", "aum": "18B"},
        {"symbol": "VGT", "name": "Vanguard Information Technology ETF", "category": "Tech", "aum": "70B"},
        {"symbol": "ARKK", "name": "ARK Innovation ETF", "category": "Disruptive Innovation", "aum": "7B"},
        {"symbol": "SCHD", "name": "Schwab US Dividend Equity ETF", "category": "Dividend", "aum": "60B"},
        {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF", "category": "US Total Market", "aum": "430B"},
        {"symbol": "GLD", "name": "SPDR Gold Shares", "category": "Gold/Commodities", "aum": "65B"},
        {"symbol": "XLK", "name": "Technology Select Sector SPDR", "category": "Tech Sector", "aum": "65B"},
        {"symbol": "SOXX", "name": "iShares Semiconductor ETF", "category": "Semiconductors", "aum": "14B"},
        {"symbol": "BOTZ", "name": "Global X Robotics & AI ETF", "category": "AI/Robotics", "aum": "3B"},
        {"symbol": "ROBO", "name": "Robo Global Robotics & AI ETF", "category": "AI/Robotics", "aum": "1.2B"},
        {"symbol": "VWO", "name": "Vanguard Emerging Markets ETF", "category": "Emerging Markets", "aum": "100B"},
        {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "category": "Long Bonds", "aum": "50B"},
        {"symbol": "HYG", "name": "iShares iBoxx High Yield Corporate Bond ETF", "category": "High Yield", "aum": "15B"},
        {"symbol": "ETHA", "name": "iShares Ethereum Trust ETF", "category": "Crypto — ETH", "aum": "2B"},
        {"symbol": "MSFT", "name": "Microsoft Corp", "category": "Action Tech", "aum": "-"},
        {"symbol": "NVDA", "name": "NVIDIA Corporation", "category": "Action Semi/IA", "aum": "-"},
    ]
    symbols = [e["symbol"] for e in ETF_UNIVERSE]
    live_data = await fetch_etf_data(symbols)
    for etf in ETF_UNIVERSE:
        d = live_data.get(etf["symbol"], {})
        etf["price"] = d.get("price", None)
        etf["change_1d"] = d.get("change_1d", None)
        etf["ytd"] = d.get("ytd", None)
        etf["volume"] = d.get("volume", None)
    return {"etfs": ETF_UNIVERSE}

@app.get("/api/v1/market/memecoins")
async def memecoins_list():
    """Trending memecoins from CoinGecko meme-token category."""
    cache_key = "memecoins"
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 120:
        return {"coins": _cache[cache_key]["data"]}
    try:
        headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "category": "meme-token",
                        "order": "market_cap_desc", "per_page": 30, "page": 1,
                        "sparkline": "false", "price_change_percentage": "1h,24h,7d"},
                headers=headers
            )
            data = r.json()
        if isinstance(data, list):
            data = [c for c in data if isinstance(c, dict)]
            _cache[cache_key] = {"data": data, "ts": time.time()}
            return {"coins": data}
        # rate-limit / réponse inattendue -> stale-while-error
        logger.warning(f"Memecoins non-list -> cache: {str(data)[:100]}")
        return {"coins": _cache.get(cache_key, {}).get("data", [])}
    except Exception as e:
        logger.error(f"Memecoins error: {e}")
        return {"coins": _cache.get(cache_key, {}).get("data", [])}

@app.get("/api/v1/market/ticker")
async def live_ticker():
    """Ticker bar data — top 10 coins."""
    coins = await fetch_top_coins(15)
    return {"tickers": [
        {
            "symbol": c.get("symbol", "").upper(),
            "price": c.get("current_price", 0),
            "change_24h": c.get("price_change_percentage_24h", 0),
        } for c in coins
    ]}

@app.get("/api/v1/market/ipo")
async def ipo_calendar(user=Depends(get_current_user)):
    """Calendrier IPO (Nasdaq, source gratuite sans clé). Cache 1h + stale-while-error."""
    cache_key = "ipo_calendar"
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 3600:
        return _cache[cache_key]["data"]

    import datetime as _dt
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120 Safari/537.36",
          "Accept": "application/json"}
    today = _dt.date.today()
    nxt = (today.replace(day=1) + _dt.timedelta(days=32)).replace(day=1)
    months = [today.strftime("%Y-%m"), nxt.strftime("%Y-%m")]

    def _row(r, date_key):
        return {
            "ticker": (r.get("proposedTickerSymbol") or "").strip(),
            "company": (r.get("companyName") or "").strip(),
            "exchange": (r.get("proposedExchange") or "").strip(),
            "price": (r.get("proposedSharePrice") or "").strip(),
            "shares": (r.get("sharesOffered") or "").strip(),
            "value": (r.get("dollarValueOfSharesOffered") or "").strip(),
            "date": (r.get(date_key) or "").strip(),
            "status": (r.get("dealStatus") or "").strip(),
        }

    priced, upcoming, filed = [], [], []
    try:
        async with httpx.AsyncClient(timeout=15, headers=ua) as client:
            for m in months:
                try:
                    r = await client.get("https://api.nasdaq.com/api/ipo/calendar",
                                         params={"date": m})
                    d = (r.json() or {}).get("data") or {}
                except Exception as e:
                    logger.warning(f"IPO month {m}: {e}"); continue
                if not isinstance(d, dict):
                    continue
                for row in ((d.get("priced") or {}).get("rows") or []):
                    priced.append(_row(row, "pricedDate"))
                for row in ((d.get("upcoming") or {}).get("upcomingTable", {}).get("rows") or []):
                    upcoming.append(_row(row, "expectedPriceDate"))
                for row in ((d.get("filed") or {}).get("rows") or []):
                    filed.append(_row(row, "filedDate"))
        # dédoublonnage par dealID/ticker
        def _dedup(lst):
            seen, out = set(), []
            for x in lst:
                k = (x["ticker"], x["company"], x["date"])
                if k in seen: continue
                seen.add(k); out.append(x)
            return out
        result = {"priced": _dedup(priced), "upcoming": _dedup(upcoming),
                  "filed": _dedup(filed)[:40], "updated": today.isoformat()}
        if result["priced"] or result["upcoming"] or result["filed"]:
            _cache[cache_key] = {"data": result, "ts": time.time()}
        return result
    except Exception as e:
        logger.error(f"IPO calendar error: {e}")
        return _cache.get(cache_key, {}).get("data",
                {"priced": [], "upcoming": [], "filed": [], "updated": today.isoformat()})

# ══════════════════════════════════════════════════════════════
#  INTELLIGENCE AVANCÉE — Scoring / Asset Explorer / Metrics / Backtest
#  (style BlockUnity — 100% Python pur, aucune dépendance ajoutée)
# ══════════════════════════════════════════════════════════════

def _sma(values, period):
    """Simple Moving Average -> list aligné (None avant période atteinte)."""
    out = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            out.append(sum(values[i + 1 - period:i + 1]) / period)
    return out

def _ema(values, period):
    out = []
    k = 2 / (period + 1)
    ema = None
    for i, v in enumerate(values):
        if v is None:
            out.append(None); continue
        if ema is None:
            if i + 1 >= period:
                seed = sum(values[i + 1 - period:i + 1]) / period
                ema = seed
                out.append(ema)
            else:
                out.append(None)
        else:
            ema = v * k + ema * (1 - k)
            out.append(ema)
    return out

def _rsi(values, period=14):
    """RSI de Wilder."""
    out = [None] * len(values)
    if len(values) < period + 1:
        return out
    gains, losses = [], []
    for i in range(1, len(values)):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0)); losses.append(max(-ch, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(values)):
        if i > period:
            avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
            avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        rs = (avg_g / avg_l) if avg_l != 0 else 999
        out[i] = round(100 - (100 / (1 + rs)), 2)
    return out

def _macd(values, fast=12, slow=26, signal=9):
    ema_f = _ema(values, fast)
    ema_s = _ema(values, slow)
    macd_line = [(a - b) if (a is not None and b is not None) else None
                 for a, b in zip(ema_f, ema_s)]
    valid = [x for x in macd_line if x is not None]
    sig_valid = _ema(valid, signal) if valid else []
    sig_line = [None] * len(macd_line)
    j = 0
    for i in range(len(macd_line)):
        if macd_line[i] is not None:
            sig_line[i] = sig_valid[j] if j < len(sig_valid) else None
            j += 1
    hist = [(m - s) if (m is not None and s is not None) else None
            for m, s in zip(macd_line, sig_line)]
    return macd_line, sig_line, hist

def _bollinger(values, period=20, mult=2):
    mid = _sma(values, period)
    upper, lower = [], []
    for i in range(len(values)):
        if i + 1 < period or mid[i] is None:
            upper.append(None); lower.append(None); continue
        window = values[i + 1 - period:i + 1]
        m = mid[i]
        var = sum((x - m) ** 2 for x in window) / period
        sd = var ** 0.5
        upper.append(m + mult * sd); lower.append(m - mult * sd)
    return upper, mid, lower

def _max_drawdown(equity):
    peak = -float("inf"); mdd = 0.0
    for v in equity:
        if v > peak: peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < mdd: mdd = dd
    return round(mdd * 100, 2)

def _downsample_daily(series: List[dict]) -> List[dict]:
    """Garde une clôture par jour (UTC) — la dernière de chaque journée."""
    by_day = {}
    for p in series:
        day = int(p["time"]) // 86400
        by_day[day] = p  # la dernière écrase => clôture du jour
    return [by_day[d] for d in sorted(by_day)]

async def fetch_close_series(symbol: str, days: int = 365) -> List[dict]:
    """Série de clôtures journalières robuste.
    1) CoinGecko market_chart SANS interval (interval=daily => 429 sur plan gratuit)
    2) Normalisée en 1 point/jour
    3) Fallback sur l'endpoint /ohlc si vide (autre quota), avec retry/backoff.
    """
    cache_key = f"closes_{symbol}_{days}"
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 900:
        return _cache[cache_key]["data"]

    cg_id = COINGECKO_IDS.get(symbol.upper())
    if not cg_id:
        # Résout l'ID CoinGecko depuis le cache markets (memecoins, alts) — ex: WIF->dogwifcoin
        for ck in ("top_coins_base", "memecoins"):
            data = (_cache.get(ck) or {}).get("data") or []
            m = next((c for c in data if isinstance(c, dict)
                      and (c.get("symbol") or "").upper() == symbol.upper()), None)
            if m and m.get("id"):
                cg_id = m["id"]; break
        if not cg_id:
            cg_id = symbol.lower()
    headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
    days = min(max(days, 1), 365)

    # ── 1) market_chart (sans interval) avec 2 tentatives ──
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart",
                    params={"vs_currency": "usd", "days": days}, headers=headers
                )
                raw = r.json()
            prices = raw.get("prices", []) if isinstance(raw, dict) else []
            if prices:
                result = _downsample_daily(
                    [{"time": int(p[0] // 1000), "close": float(p[1])} for p in prices]
                )
                if result:
                    _cache[cache_key] = {"data": result, "ts": time.time()}
                    return result
            # 429 / vide -> petite pause avant retry
            await asyncio.sleep(1.2)
        except Exception as e:
            logger.warning(f"market_chart try{attempt} {symbol}: {e}")
            await asyncio.sleep(1.0)

    # ── 2) Fallback : endpoint /ohlc (quota distinct) ──
    try:
        ohlc = await fetch_ohlcv(symbol, "crypto", "365d")
        if ohlc:
            result = _downsample_daily(
                [{"time": int(c["time"]), "close": float(c["close"])} for c in ohlc]
            )
            if result:
                _cache[cache_key] = {"data": result, "ts": time.time()}
                return result
    except Exception as e:
        logger.warning(f"close series fallback {symbol}: {e}")

    # garde l'ancien cache si dispo, sinon vide
    if cache_key in _cache:
        return _cache[cache_key]["data"]
    return []

def _score_from_market(c: dict) -> dict:
    """Score composite 0-100 à partir des données markets CoinGecko."""
    ch1 = c.get("price_change_percentage_1h_in_currency") or 0
    ch24 = c.get("price_change_percentage_24h") or 0
    ch7 = c.get("price_change_percentage_7d_in_currency") or 0
    ath_chg = c.get("ath_change_percentage") or 0  # négatif = sous l'ATH
    vol = c.get("total_volume") or 0
    mcap = c.get("market_cap") or 0

    def clamp(x): return max(0, min(100, x))
    # Momentum : combinaison 24h + 7d + 1h, recentré sur 50
    momentum = clamp(50 + ch24 * 1.6 + ch7 * 0.9 + ch1 * 1.2)
    # Tendance : positif si 7j et 24h alignés haussiers
    trend = clamp(50 + (ch7 * 1.4) + (10 if (ch7 > 0 and ch24 > 0) else -10 if (ch7 < 0 and ch24 < 0) else 0))
    # Valeur/risque : plus on est proche de l'ATH, plus c'est "cher" (score bas)
    #   ath_chg=0 (à l'ATH) -> ~30 ; -50% -> ~65 ; -80% -> ~85
    value = clamp(30 + (-ath_chg) * 0.7)
    # Liquidité : ratio volume/mcap
    liq = clamp(40 + (vol / mcap * 100) * 2.5) if mcap else 50

    score = momentum * 0.34 + trend * 0.30 + value * 0.20 + liq * 0.16
    score = round(clamp(score), 1)
    if score >= 75: signal, label = "strong_buy", "Achat fort"
    elif score >= 60: signal, label = "buy", "Achat"
    elif score >= 45: signal, label = "neutral", "Neutre"
    elif score >= 30: signal, label = "sell", "Vente"
    else: signal, label = "strong_sell", "Vente forte"
    return {
        "score": score, "signal": signal, "label": label,
        "breakdown": {
            "Momentum": round(momentum, 0), "Tendance": round(trend, 0),
            "Valeur": round(value, 0), "Liquidité": round(liq, 0),
        },
    }

@app.get("/api/v1/scoring/coins")
async def scoring_coins(limit: int = 50, user=Depends(get_current_user)):
    """Scoring composite (style BlockUnity) sur le top marché."""
    coins = await fetch_top_coins(min(limit, 100))
    out = []
    for c in coins:
        if not isinstance(c, dict):
            continue
        sc = _score_from_market(c)
        out.append({
            "symbol": (c.get("symbol") or "").upper(),
            "name": c.get("name", ""),
            "image": c.get("image", ""),
            "rank": c.get("market_cap_rank"),
            "price": c.get("current_price", 0),
            "change_24h": c.get("price_change_percentage_24h", 0),
            "change_7d": c.get("price_change_percentage_7d_in_currency", 0),
            "market_cap": c.get("market_cap", 0),
            **sc,
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return {"coins": out}

def _indicators_snapshot(closes: List[float]) -> dict:
    """Photo des indicateurs techniques au dernier point."""
    if len(closes) < 2:
        return {}
    rsi = _rsi(closes, 14)
    sma20 = _sma(closes, 20); sma50 = _sma(closes, 50); sma200 = _sma(closes, 200)
    ema20 = _ema(closes, 20)
    macd_l, sig_l, hist = _macd(closes)
    up, mid, low = _bollinger(closes, 20, 2)
    last = closes[-1]

    def lv(arr):
        for v in reversed(arr):
            if v is not None: return round(v, 4)
        return None

    rsi_v = lv(rsi); sma20_v = lv(sma20); sma50_v = lv(sma50)
    macd_v = lv(macd_l); sig_v = lv(sig_l)
    signals = []
    if rsi_v is not None:
        if rsi_v < 30: signals.append(("RSI", "Survente", "buy"))
        elif rsi_v > 70: signals.append(("RSI", "Surachat", "sell"))
        else: signals.append(("RSI", "Neutre", "neutral"))
    if sma20_v and sma50_v:
        signals.append(("Tendance MM", "Haussière" if sma20_v > sma50_v else "Baissière",
                        "buy" if sma20_v > sma50_v else "sell"))
    if sma50_v:
        signals.append(("Prix vs MM50", "Au-dessus" if last > sma50_v else "En-dessous",
                        "buy" if last > sma50_v else "sell"))
    if macd_v is not None and sig_v is not None:
        signals.append(("MACD", "Haussier" if macd_v > sig_v else "Baissier",
                        "buy" if macd_v > sig_v else "sell"))
    return {
        "rsi": rsi_v, "sma20": sma20_v, "sma50": sma50_v, "sma200": lv(sma200),
        "ema20": lv(ema20), "macd": macd_v, "macd_signal": sig_v,
        "bb_upper": lv(up), "bb_mid": lv(mid), "bb_lower": lv(low),
        "signals": [{"name": n, "value": v, "dir": d} for n, v, d in signals],
    }

@app.get("/api/v1/asset/{symbol}")
async def asset_explorer(symbol: str, asset_type: str = "crypto", user=Depends(get_current_user)):
    """Fiche détaillée d'un actif : marché + indicateurs + score + signal."""
    symbol = symbol.upper()
    coins = await fetch_top_coins(100)
    meta = next((c for c in coins if isinstance(c, dict) and (c.get("symbol") or "").upper() == symbol), {})
    series = await fetch_close_series(symbol, 365)
    closes = [p["close"] for p in series]
    indicators = _indicators_snapshot(closes) if closes else {}
    score = _score_from_market(meta) if meta else {}
    return {
        "symbol": symbol,
        "name": meta.get("name", symbol),
        "image": meta.get("image", ""),
        "price": meta.get("current_price"),
        "change_24h": meta.get("price_change_percentage_24h"),
        "change_7d": meta.get("price_change_percentage_7d_in_currency"),
        "market_cap": meta.get("market_cap"),
        "market_cap_rank": meta.get("market_cap_rank"),
        "volume_24h": meta.get("total_volume"),
        "high_24h": meta.get("high_24h"),
        "low_24h": meta.get("low_24h"),
        "ath": meta.get("ath"),
        "ath_change_percentage": meta.get("ath_change_percentage"),
        "atl": meta.get("atl"),
        "circulating_supply": meta.get("circulating_supply"),
        "total_supply": meta.get("total_supply"),
        "max_supply": meta.get("max_supply"),
        "indicators": indicators,
        "score": score,
        "series": series,
    }

@app.get("/api/v1/metrics/{symbol}")
async def metrics_series(symbol: str, period: str = "180d", user=Depends(get_current_user)):
    """Séries d'indicateurs techniques pour graphique avancé."""
    days_map = {"30d": 30, "90d": 90, "180d": 180, "365d": 365}
    days = days_map.get(period, 180)
    series = await fetch_close_series(symbol.upper(), days)
    if not series:
        return {"symbol": symbol.upper(), "period": period, "points": []}
    closes = [p["close"] for p in series]
    times = [p["time"] for p in series]
    sma20 = _sma(closes, 20); sma50 = _sma(closes, 50)
    ema20 = _ema(closes, 20)
    rsi = _rsi(closes, 14)
    macd_l, sig_l, hist = _macd(closes)
    up, mid, low = _bollinger(closes, 20, 2)
    points = []
    for i in range(len(closes)):
        points.append({
            "time": times[i], "close": round(closes[i], 4),
            "sma20": round(sma20[i], 4) if sma20[i] is not None else None,
            "sma50": round(sma50[i], 4) if sma50[i] is not None else None,
            "ema20": round(ema20[i], 4) if ema20[i] is not None else None,
            "rsi": rsi[i],
            "macd": round(macd_l[i], 4) if macd_l[i] is not None else None,
            "macd_signal": round(sig_l[i], 4) if sig_l[i] is not None else None,
            "macd_hist": round(hist[i], 4) if hist[i] is not None else None,
            "bb_upper": round(up[i], 4) if up[i] is not None else None,
            "bb_lower": round(low[i], 4) if low[i] is not None else None,
        })
    return {"symbol": symbol.upper(), "period": period,
            "snapshot": _indicators_snapshot(closes), "points": points}

def _atr_proxy(closes: List[float], period: int = 14) -> List[float]:
    """ATR approximé à partir des seules clôtures (|close[i]-close[i-1]|), lissé EMA."""
    tr = [0.0]
    for i in range(1, len(closes)):
        tr.append(abs(closes[i] - closes[i - 1]))
    return _ema(tr, period)

def _magic_bands(closes: List[float]) -> dict:
    """Magic Bands (style BlockUnity) : nuage EMA + bandes ATR multi-niveaux.
    Nuage vert si EMA rapide > EMA lente (haussier), rouge sinon.
    3 niveaux de bandes -> support/résistance dynamiques + zones surachat/survente.
    """
    n = len(closes)
    ema_fast = _ema(closes, 20)
    ema_slow = _ema(closes, 50)
    atr = _atr_proxy(closes, 14)
    mults = [2.0, 3.5, 5.0]  # niveaux 1 (S/R) -> 3 (extrêmes OB/OS)
    pts = []
    for i in range(n):
        ef, es, a = ema_fast[i], ema_slow[i], atr[i]
        if ef is None or es is None or a is None:
            pts.append(None); continue
        basis = (ef + es) / 2
        up = (ef > es)
        bands = {}
        for k, m in enumerate(mults, start=1):
            bands[f"u{k}"] = round(basis + m * a, 6)
            bands[f"l{k}"] = round(basis - m * a, 6)
        pts.append({
            "basis": round(basis, 6),
            "ema_fast": round(ef, 6), "ema_slow": round(es, 6),
            "up": up, **bands,
        })
    return {"points": pts, "ema_fast": ema_fast, "ema_slow": ema_slow}

@app.get("/api/v1/magicband/{symbol}")
async def magic_band(symbol: str, period: str = "180d", user=Depends(get_current_user)):
    """MagicBand — nuage de tendance + bandes surachat/survente & S/R dynamiques."""
    days_map = {"90d": 90, "180d": 180, "365d": 365}
    days = days_map.get(period, 180)
    series = await fetch_close_series(symbol.upper(), days)
    if not series:
        return {"symbol": symbol.upper(), "period": period, "points": [], "snapshot": {}}
    closes = [p["close"] for p in series]
    times = [p["time"] for p in series]
    mb = _magic_bands(closes)
    out = []
    for i in range(len(closes)):
        p = mb["points"][i]
        row = {"time": times[i], "close": round(closes[i], 6)}
        if p:
            row.update(p)
        out.append(row)

    # ── Détection des POINTS D'ACHAT / VENTE sur l'historique ──
    #   Achat : le prix revient au-dessus de la bande basse (rebond depuis survente)
    #   Vente : le prix repasse sous la bande haute (rejet depuis surachat)
    signals = []
    for i in range(1, len(closes)):
        p, pp = mb["points"][i], mb["points"][i - 1]
        if not p or not pp:
            continue
        c, cprev = closes[i], closes[i - 1]
        # ACHAT : croisement haussier de la bande basse l1
        if cprev <= pp["l1"] and c > p["l1"]:
            strong = (cprev <= pp["l3"]) or p["up"]
            signals.append({
                "time": times[i], "type": "buy", "price": round(c, 6),
                "strength": "strong" if strong else "normal",
                "reason": "Rebond depuis la zone de survente" + (" + tendance haussière" if p["up"] else ""),
            })
        # VENTE : croisement baissier de la bande haute u1
        elif cprev >= pp["u1"] and c < p["u1"]:
            strong = (cprev >= pp["u3"]) or (not p["up"])
            signals.append({
                "time": times[i], "type": "sell", "price": round(c, 6),
                "strength": "strong" if strong else "normal",
                "reason": "Rejet depuis la zone de surachat" + (" + tendance baissière" if not p["up"] else ""),
            })

    # ── Snapshot / signal au dernier point valide + NIVEAUX CONCRETS ──
    snap, levels, explanation = {}, {}, ""
    last_i = next((i for i in range(len(closes) - 1, -1, -1) if mb["points"][i]), None)
    if last_i is not None:
        p = mb["points"][last_i]; price = closes[last_i]
        trend = "haussier" if p["up"] else "baissier"
        if price >= p["u3"]: zone, zsig = "Surachat extrême", "sell"
        elif price >= p["u1"]: zone, zsig = "Zone haute", "neutral"
        elif price <= p["l3"]: zone, zsig = "Survente extrême", "buy"
        elif price <= p["l1"]: zone, zsig = "Zone basse", "neutral"
        else: zone, zsig = "Neutre", "neutral"
        if zsig == "buy" and p["up"]: signal, slabel = "strong_buy", "Achat fort (rebond + tendance haussière)"
        elif zsig == "buy": signal, slabel = "buy", "Survente — rebond possible"
        elif zsig == "sell" and not p["up"]: signal, slabel = "strong_sell", "Vente forte (surachat + tendance baissière)"
        elif zsig == "sell": signal, slabel = "sell", "Surachat — prudence"
        else: signal, slabel = ("buy" if p["up"] else "neutral"), ("Tendance haussière" if p["up"] else "Sans signal fort")
        rng = p["u1"] - p["l1"]
        pos_pct = round(((price - p["l1"]) / rng) * 100, 1) if rng else 50
        snap = {
            "trend": trend, "zone": zone, "signal": signal, "label": slabel,
            "price": round(price, 6), "basis": p["basis"],
            "support": p["l1"], "resistance": p["u1"],
            "support_ext": p["l3"], "resistance_ext": p["u3"],
            "position_pct": max(0, min(100, pos_pct)),
        }
        # Niveaux opérationnels (zone d'achat / stop / objectifs de vente)
        last_buy = next((s for s in reversed(signals) if s["type"] == "buy"), None)
        last_sell = next((s for s in reversed(signals) if s["type"] == "sell"), None)
        levels = {
            "buy_zone_low": p["l3"], "buy_zone_high": p["l1"],
            "stop_loss": round(p["l3"] * 0.97, 6),
            "target_1": p["basis"], "target_2": p["u1"], "target_3": p["u2"],
            "last_buy": last_buy, "last_sell": last_sell,
        }
        # Explication pédagogique
        def _usd(v):
            try:
                v = float(v)
            except Exception:
                return "--"
            if abs(v) >= 1:
                return "$" + format(round(v, 2), ",.2f")
            if abs(v) >= 0.01:
                return "$" + format(v, ".4f")
            return "$" + format(v, ".8f").rstrip("0").rstrip(".")
        explanation = (
            f"Le MagicBand combine un nuage de tendance (moyennes mobiles) et des bandes de volatilité. "
            f"Tendance actuelle : {trend}. Le prix se situe en zone « {zone.lower()} ». "
            f"Zone d'achat indicative : {_usd(p['l1'])} à {_usd(p['l3'])}, stop sous {_usd(p['l3'] * 0.97)}. "
            f"Objectifs (résistances) : {_usd(p['basis'])}, {_usd(p['u1'])}, {_usd(p['u2'])}. "
            f"Les bandes vertes (bas) marquent la survente, les rouges (haut) le surachat ; "
            f"les flèches vertes/rouges indiquent les signaux d'achat/vente détectés."
        )

    return {"symbol": symbol.upper(), "period": period, "points": out,
            "snapshot": snap, "signals": signals[-30:], "levels": levels,
            "explanation": explanation}

@app.post("/api/v1/ai/magicband")
async def ai_magicband(req: dict, user=Depends(get_current_user)):
    """L'IA analyse le MagicBand et donne un plan d'achat/vente concret."""
    symbol = (req.get("symbol") or "BTC").upper()
    snap = req.get("snapshot") or {}
    levels = req.get("levels") or {}
    sigs = req.get("signals") or []
    # Repli déterministe (toujours disponible, même sans clé IA)
    fallback = {
        "verdict": snap.get("label", "Analyse indisponible"),
        "commentaire": (
            f"{symbol} : tendance {snap.get('trend','?')}, zone « {snap.get('zone','?')} ». "
            f"Plan : achat échelonné entre {levels.get('buy_zone_high')} et {levels.get('buy_zone_low')}, "
            f"stop sous {levels.get('stop_loss')}. Objectifs de vente : {levels.get('target_1')}, "
            f"{levels.get('target_2')}, {levels.get('target_3')}."
        ),
        "achat": [levels.get("buy_zone_high"), levels.get("buy_zone_low")],
        "stop": levels.get("stop_loss"),
        "objectifs": [levels.get("target_1"), levels.get("target_2"), levels.get("target_3")],
    }
    if not ai_enabled():
        return fallback
    try:
        recent = "; ".join(f"{s['type']}@{s['price']}" for s in sigs[-6:])
        prompt = (
            f"Tu es analyste trading. Indicateur MagicBand pour {symbol}. "
            f"Données: prix={snap.get('price')}, tendance={snap.get('trend')}, zone={snap.get('zone')}, "
            f"support={snap.get('support')}, résistance={snap.get('resistance')}, "
            f"zone d'achat={levels.get('buy_zone_low')}-{levels.get('buy_zone_high')}, "
            f"stop={levels.get('stop_loss')}, objectifs={levels.get('target_1')}/{levels.get('target_2')}/{levels.get('target_3')}, "
            f"derniers signaux: {recent}. "
            "Réponds en JSON strict avec les clés: verdict (1 phrase), commentaire (3-4 phrases pédagogiques en français), "
            "achat (liste de 2 nombres = fourchette), stop (nombre), objectifs (liste de 3 nombres). "
            "Sois concret et actionnable."
        )
        txt = await ai_complete(prompt, max_tokens=900, task="analysis")
        data = _safe_json_loads(txt)
        if data and data.get("commentaire"):
            return data
        return fallback
    except Exception as e:
        logger.warning(f"ai_magicband error: {e}")
        return fallback

@app.post("/api/v1/ai/analyze-express")
async def analyze_express(req: dict, user=Depends(get_current_user)):
    """Analyse EXPRESS — rapide + 100% factuelle.
    Tous les chiffres sont CALCULÉS à partir des vraies données de marché
    (prix, RSI, MM, MACD, ATH, score, niveaux MagicBand). L'IA ne fait QUE
    rédiger une courte synthèse à partir de ces chiffres — aucune invention.
    """
    symbol = (req.get("symbol") or "BTC").upper()
    coins = await fetch_top_coins(100)
    meta = next((c for c in coins if isinstance(c, dict)
                 and (c.get("symbol") or "").upper() == symbol), {})
    series = await fetch_close_series(symbol, 365)
    closes = [p["close"] for p in series]
    if not meta and not closes:
        raise HTTPException(404, f"Aucune donnée de marché pour {symbol}")

    ind = _indicators_snapshot(closes) if closes else {}
    score = _score_from_market(meta) if meta else {}
    mb = _magic_bands(closes) if closes else {"points": []}
    price = meta.get("current_price") or (closes[-1] if closes else None)

    # Niveaux d'achat/vente réels (MagicBand)
    levels = {}
    pts = mb.get("points", [])
    last_i = next((i for i in range(len(pts) - 1, -1, -1) if pts[i]), None)
    if last_i is not None:
        p = pts[last_i]
        levels = {
            "support": p["l1"], "resistance": p["u1"],
            "buy_zone_low": p["l3"], "buy_zone_high": p["l1"],
            "stop_loss": round(p["l3"] * 0.97, 6),
            "target_1": p["basis"], "target_2": p["u1"], "target_3": p["u2"],
        }

    rsi = ind.get("rsi")
    ch24 = meta.get("price_change_percentage_24h")
    ch7 = meta.get("price_change_percentage_7d_in_currency")
    ath_chg = meta.get("ath_change_percentage")

    # ── Points clés 100% factuels (calculés, jamais inventés) ──
    facts = []
    if rsi is not None:
        zone = "survente" if rsi < 30 else "surachat" if rsi > 70 else "neutre"
        facts.append(f"RSI(14) = {rsi} ({zone})")
    for s in ind.get("signals", []):
        facts.append(f"{s['name']} : {s['value']}")
    if ch24 is not None:
        facts.append(f"Variation 24h : {ch24:+.2f}%")
    if ch7 is not None:
        facts.append(f"Variation 7j : {ch7:+.2f}%")
    if ath_chg is not None:
        facts.append(f"{ath_chg:.1f}% vs plus-haut historique (ATH)")
    if score.get("score") is not None:
        facts.append(f"Score composite : {score['score']}/100 ({score.get('label','')})")

    verdict = score.get("label", "Neutre")
    signal = score.get("signal", "neutral")

    # ── Synthèse IA bornée aux faits (Haiku, courte) + repli déterministe ──
    commentaire = (
        f"{symbol} cote {price}. Tendance " +
        ("haussière" if (ind.get('sma50') and price and price > ind['sma50']) else "baissière") +
        f", score {score.get('score','--')}/100. " +
        (f"RSI à {rsi} ({'survente' if rsi and rsi<30 else 'surachat' if rsi and rsi>70 else 'neutre'}). " if rsi is not None else "") +
        (f"Zone d'achat {levels.get('buy_zone_high')}–{levels.get('buy_zone_low')}, stop {levels.get('stop_loss')}, objectifs {levels.get('target_1')}/{levels.get('target_2')}." if levels else "")
    )
    if ai_enabled():
        try:
            prompt = (
                "Tu es analyste marché. Voici des données RÉELLES calculées pour "
                f"{symbol} :\n- Prix : {price}\n- " + "\n- ".join(facts) +
                (f"\n- Niveaux : support {levels.get('support')}, résistance {levels.get('resistance')}, "
                 f"zone d'achat {levels.get('buy_zone_low')}–{levels.get('buy_zone_high')}, "
                 f"stop {levels.get('stop_loss')}, objectifs {levels.get('target_1')}/{levels.get('target_2')}/{levels.get('target_3')}" if levels else "") +
                "\n\nRédige une synthèse de 2 à 3 phrases en français, claire et actionnable. "
                "RÈGLE ABSOLUE : utilise UNIQUEMENT les chiffres ci-dessus. "
                "N'invente AUCUNE actualité, partenariat, chiffre, fondamental ou évènement. "
                "Pas de spéculation non chiffrée. Réponds en texte brut (pas de JSON)."
            )
            txt = (await ai_complete(prompt, max_tokens=350, task="summary")).strip()
            if txt:
                commentaire = txt
        except Exception as e:
            logger.warning(f"analyze_express AI error: {e}")

    return {
        "symbol": symbol,
        "name": meta.get("name", symbol),
        "image": meta.get("image", ""),
        "price": price,
        "change_24h": ch24, "change_7d": ch7,
        "market_cap": meta.get("market_cap"), "rank": meta.get("market_cap_rank"),
        "verdict": verdict, "signal": signal,
        "score": score.get("score"), "score_breakdown": score.get("breakdown", {}),
        "rsi": rsi, "sma50": ind.get("sma50"), "sma200": ind.get("sma200"),
        "facts": facts, "levels": levels,
        "commentaire": commentaire,
        "source": "Données réelles : CoinGecko + indicateurs calculés (RSI/MM/MACD/MagicBand)",
    }

@app.post("/api/v1/ai/analyze-ipo")
async def analyze_ipo(req: dict, user=Depends(get_current_user)):
    """Analyse IA d'une IPO à venir : verdict + intérêt d'investir ou non.
    Routage IA = tâche 'research' (Claude en priorité)."""
    if not ai_enabled():
        raise HTTPException(503, "Configurez une clé IA (ANTHROPIC/OPENAI/GOOGLE) dans .env")
    company = req.get("company") or req.get("name") or "?"
    ticker = req.get("ticker") or ""
    exchange = req.get("exchange") or ""
    price = req.get("price") or ""
    shares = req.get("shares") or ""
    value = req.get("value") or ""
    date = req.get("date") or ""
    prompt = f"""Tu es analyste IPO institutionnel chez HR5 Invest. Analyse cette introduction
en bourse À VENIR et donne un avis d'investissement clair et honnête.

Société : {company}
Ticker : {ticker}
Bourse : {exchange}
Fourchette de prix : {price}
Nombre d'actions : {shares}
Montant levé : {value}
Date prévue : {date}

Réponds UNIQUEMENT en JSON strict (toutes les valeurs texte sur une seule ligne) :
{{
  "societe": "{company}",
  "secteur": "secteur estimé",
  "verdict": "Tres interessant|Interessant|A surveiller|Prudence|A eviter",
  "interet_investir": true,
  "score": 0,
  "niveau_risque": "Faible|Modere|Eleve|Tres eleve",
  "synthese": "2-3 phrases sur l'opportunite, le business model et le contexte de marche",
  "points_forts": ["...", "..."],
  "points_faibles": ["...", "..."],
  "facteurs_cles": ["valorisation", "momentum du secteur", "..."],
  "strategie": "Comment aborder cette IPO (attendre la fin du lock-up, taille de position, jour 1 vs apres, etc.)",
  "avertissement": "Rappel: les IPO sont volatiles et l'information est limitee avant cotation."
}}

SOIS CONCIS (reponse rapide) : synthese en 2 phrases max, 2 points forts, 2 points faibles,
strategie en 1 phrase. Base-toi sur tes connaissances; si l'info est limitee, sois prudent et
dis-le. Retourne UNIQUEMENT le JSON."""
    try:
        text = await ai_complete(prompt, max_tokens=900, task="research")
        return _safe_json_loads(text)
    except Exception as e:
        logger.error(f"analyze_ipo error: {e}")
        raise HTTPException(500, f"Analyse IPO indisponible : {e}")

@app.post("/api/v1/backtest")
async def backtest(req: dict, user=Depends(get_current_user)):
    """Backtest d'une stratégie (style Strategy Builder BlockUnity).
    req: {symbol, strategy, capital, days, params:{...}}
    strategy ∈ sma_cross | rsi | dca | buy_hold
    """
    symbol = (req.get("symbol") or "BTC").upper()
    strategy = req.get("strategy", "sma_cross")
    capital = float(req.get("capital", 1000) or 1000)
    days = int(req.get("days", 365) or 365)
    p = req.get("params", {}) or {}

    series = await fetch_close_series(symbol, min(max(days, 30), 365))
    if len(series) < 20:
        raise HTTPException(400, "Pas assez de données historiques pour ce symbole.")
    closes = [s["close"] for s in series]
    times = [s["time"] for s in series]
    n = len(closes)

    cash = capital
    units = 0.0
    trades = []
    equity = []

    def buy(i, frac=1.0):
        nonlocal cash, units
        if cash <= 0: return
        amount = cash * frac
        u = amount / closes[i]
        units += u; cash -= amount
        trades.append({"time": times[i], "type": "buy", "price": round(closes[i], 4),
                       "units": round(u, 8)})

    def sell(i):
        nonlocal cash, units
        if units <= 0: return
        entry = next((t["price"] for t in reversed(trades) if t["type"] == "buy"), closes[i])
        proceeds = units * closes[i]
        pnl_pct = (closes[i] / entry - 1) * 100 if entry else 0
        cash += proceeds;
        trades.append({"time": times[i], "type": "sell", "price": round(closes[i], 4),
                       "units": round(units, 8), "pnl_pct": round(pnl_pct, 2)})
        units = 0.0

    if strategy == "buy_hold":
        buy(0)
        for i in range(n): equity.append(cash + units * closes[i])

    elif strategy == "dca":
        interval = int(p.get("interval_days", 7) or 7)
        contrib = float(p.get("contribution", capital / 12) or capital / 12)
        cash = 0.0  # DCA : on injecte au fil de l'eau
        invested = 0.0
        for i in range(n):
            if i % interval == 0:
                cash += contrib; invested += contrib
                buy(i)
            equity.append(cash + units * closes[i])
        capital = invested if invested else capital

    elif strategy == "rsi":
        os = float(p.get("oversold", 30) or 30)
        ob = float(p.get("overbought", 70) or 70)
        rsi = _rsi(closes, int(p.get("rsi_period", 14) or 14))
        for i in range(n):
            r = rsi[i]
            if r is not None:
                if r < os and units == 0: buy(i)
                elif r > ob and units > 0: sell(i)
            equity.append(cash + units * closes[i])

    else:  # sma_cross
        fast = int(p.get("fast", 20) or 20)
        slow = int(p.get("slow", 50) or 50)
        sf = _sma(closes, fast); ss = _sma(closes, slow)
        for i in range(n):
            if sf[i] is not None and ss[i] is not None and i > 0 and sf[i-1] is not None and ss[i-1] is not None:
                cross_up = sf[i-1] <= ss[i-1] and sf[i] > ss[i]
                cross_dn = sf[i-1] >= ss[i-1] and sf[i] < ss[i]
                if cross_up and units == 0: buy(i)
                elif cross_dn and units > 0: sell(i)
            equity.append(cash + units * closes[i])

    final_value = cash + units * closes[-1]
    total_return = (final_value / capital - 1) * 100 if capital else 0
    bh_return = (closes[-1] / closes[0] - 1) * 100
    sells = [t for t in trades if t["type"] == "sell"]
    wins = [t for t in sells if t.get("pnl_pct", 0) > 0]
    win_rate = (len(wins) / len(sells) * 100) if sells else None
    mdd = _max_drawdown(equity) if equity else 0
    # Sharpe simplifié sur rendements journaliers de l'équité
    rets = [(equity[i] / equity[i-1] - 1) for i in range(1, len(equity)) if equity[i-1] > 0]
    if len(rets) > 2:
        mean = sum(rets) / len(rets)
        var = sum((x - mean) ** 2 for x in rets) / len(rets)
        sharpe = round((mean / (var ** 0.5) * (365 ** 0.5)), 2) if var > 0 else None
    else:
        sharpe = None

    return {
        "symbol": symbol, "strategy": strategy,
        "initial_capital": round(capital, 2),
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return, 2),
        "buy_hold_return_pct": round(bh_return, 2),
        "alpha_pct": round(total_return - bh_return, 2),
        "max_drawdown_pct": mdd,
        "sharpe": sharpe,
        "n_trades": len(trades),
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "trades": trades[-40:],
        "equity": [{"time": times[i], "value": round(equity[i], 2)} for i in range(len(equity))],
        "price": [{"time": times[i], "value": round(closes[i], 4)} for i in range(n)],
    }

# ══════════════════════════════════════════════════════════════
#  WATCHLIST & ALERTS
# ══════════════════════════════════════════════════════════════
@app.get("/api/v1/watchlist")
async def get_watchlist(user=Depends(get_current_user)):
    conn = get_db()
    items = [dict(r) for r in conn.execute(
        "SELECT * FROM watchlist WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()]
    conn.close()
    crypto_syms = [i["symbol"] for i in items if i["asset_type"] == "crypto"]
    etf_syms = [i["symbol"] for i in items if i["asset_type"] in ("etf", "stock")]
    crypto_p = await fetch_crypto_prices(crypto_syms) if crypto_syms else {}
    etf_p = await fetch_etf_data(etf_syms) if etf_syms else {}
    for i in items:
        sym = i["symbol"].upper()
        if i["asset_type"] == "crypto":
            d = crypto_p.get(sym, {})
            i["current_price"] = d.get("price", 0)
            i["change_24h"] = d.get("change_24h", 0)
        else:
            d = etf_p.get(sym, {})
            i["current_price"] = d.get("price", 0)
            i["change_24h"] = d.get("change_1d", 0)
        if i["target_price"] and i["current_price"]:
            i["target_distance_pct"] = ((i["target_price"] - i["current_price"]) / i["current_price"] * 100)
        else:
            i["target_distance_pct"] = None
    return {"items": items}

@app.post("/api/v1/watchlist")
async def add_watchlist(req: WatchlistRequest, user=Depends(get_current_user)):
    conn = get_db()
    try:
        conn.execute("""INSERT OR IGNORE INTO watchlist
            (user_id, symbol, asset_type, name, target_price, stop_loss, notes) VALUES (?,?,?,?,?,?,?)""",
            (user["id"], req.symbol.upper(), req.asset_type, req.name, req.target_price, req.stop_loss, req.notes))
        conn.commit()
    finally:
        conn.close()
    return {"success": True}

@app.delete("/api/v1/watchlist/{item_id}")
async def remove_watchlist(item_id: int, user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM watchlist WHERE id=? AND user_id=?", (item_id, user["id"]))
    conn.commit(); conn.close()
    return {"success": True}

@app.get("/api/v1/alerts")
async def get_alerts(user=Depends(get_current_user)):
    conn = get_db()
    alerts = [dict(r) for r in conn.execute(
        "SELECT * FROM alerts WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()]
    conn.close()
    return {"alerts": alerts}

@app.post("/api/v1/alerts")
async def create_alert(req: AlertRequest, user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("INSERT INTO alerts (user_id, symbol, alert_type, threshold, message) VALUES (?,?,?,?,?)",
                 (user["id"], req.symbol.upper(), req.alert_type, req.threshold, req.message))
    conn.commit(); conn.close()
    return {"success": True}

@app.put("/api/v1/alerts/{alert_id}/toggle")
async def toggle_alert(alert_id: int, user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("UPDATE alerts SET is_active = 1 - is_active WHERE id=? AND user_id=?", (alert_id, user["id"]))
    conn.commit(); conn.close()
    return {"success": True}

@app.delete("/api/v1/alerts/{alert_id}")
async def delete_alert(alert_id: int, user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM alerts WHERE id=? AND user_id=?", (alert_id, user["id"]))
    conn.commit(); conn.close()
    return {"success": True}

# ══════════════════════════════════════════════════════════════
#  AI ROUTES
# ══════════════════════════════════════════════════════════════
@app.post("/api/v1/ai/analyze")
async def analyze(req: AnalyzeRequest, user=Depends(get_current_user)):
    result = await ai_analyze(req.symbol, req.asset_type, req.portfolio_context)
    conn = get_db()
    conn.execute("INSERT INTO ai_analyses (user_id, symbol, asset_type, analysis) VALUES (?,?,?,?)",
                 (user["id"], req.symbol.upper(), req.asset_type, json.dumps(result)))
    conn.commit(); conn.close()
    return result

@app.post("/api/v1/ai/analyze-portfolio")
async def analyze_portfolio(req: PortfolioAnalyzeRequest, user=Depends(get_current_user)):
    conn = get_db()
    if req.portfolio_id:
        prow = conn.execute("SELECT * FROM portfolios WHERE id=? AND user_id=?",
                            (req.portfolio_id, user["id"])).fetchone()
    else:
        prow = conn.execute("SELECT * FROM portfolios WHERE user_id=? AND is_default=1",
                           (user["id"],)).fetchone()
        if not prow:
            prow = conn.execute("SELECT * FROM portfolios WHERE user_id=? ORDER BY id LIMIT 1",
                               (user["id"],)).fetchone()
    if not prow:
        conn.close()
        raise HTTPException(404, "Aucun portefeuille trouvé")
    positions = conn.execute("SELECT * FROM portfolio_positions WHERE portfolio_id=?",
                            (prow["id"],)).fetchall()
    conn.close()
    if not positions:
        raise HTTPException(400, "Portefeuille vide — importez vos positions ou ajoutez-en avant de lancer l'analyse.")
    enriched = await enrich_portfolio(prow["id"], positions)
    result = await ai_analyze_portfolio(enriched)
    result["total_value"] = enriched.get("total_value", 0)
    result["total_pnl_pct"] = enriched.get("total_pnl_pct", 0)
    result["position_count"] = enriched.get("position_count", 0)
    result["portfolio_name"] = prow["name"]
    return result

@app.post("/api/v1/ai/chat")
async def chat(req: ChatRequest, user=Depends(get_current_user)):
    portfolio_data = None
    if req.include_portfolio:
        conn = get_db()
        if req.portfolio_id:
            portfolio = conn.execute("SELECT id FROM portfolios WHERE id=? AND user_id=?",
                                    (req.portfolio_id, user["id"])).fetchone()
        else:
            portfolio = conn.execute("SELECT id FROM portfolios WHERE user_id=? AND is_default=1",
                                    (user["id"],)).fetchone()
        if portfolio:
            positions = conn.execute("SELECT * FROM portfolio_positions WHERE portfolio_id=?",
                                    (portfolio["id"],)).fetchall()
            conn.close()
            portfolio_data = await enrich_portfolio(portfolio["id"], positions)
        else:
            conn.close()

    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    return StreamingResponse(
        ai_stream_chat(messages, req.context, portfolio_data),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.post("/api/v1/ai/dca")
async def dca_plan(req: DCARequest, user=Depends(get_current_user)):
    result = await generate_dca_plan(req.symbol, req.capital, req.horizon_months, req.risk_level)
    return result

@app.get("/api/v1/ai/opportunities")
async def opportunities(user=Depends(get_current_user)):
    coins = await fetch_top_coins(50)
    opps = []
    for c in coins:
        change_24h = c.get("price_change_percentage_24h", 0) or 0
        change_7d = c.get("price_change_percentage_7d_in_currency", 0) or 0
        volume = c.get("total_volume", 0) or 0
        mktcap = c.get("market_cap", 1) or 1
        vol_ratio = volume / mktcap if mktcap else 0
        score = 50
        if change_24h > 5: score += 15
        elif change_24h > 2: score += 8
        elif change_24h < -5: score += 10  # potential bounce
        if change_7d > 15: score += 15
        elif change_7d > 5: score += 8
        if vol_ratio > 0.15: score += 10
        score = min(96, max(30, score))
        if score >= 60 or abs(change_24h) > 5:
            signal = ("Momentum haussier fort" if change_24h > 5
                      else "Momentum haussier" if change_24h > 2
                      else "Survente — rebond potentiel" if change_24h < -5
                      else "Volume inhabituel")
            opps.append({
                "symbol": c.get("symbol", "").upper(),
                "name": c.get("name", ""),
                "price": c.get("current_price", 0),
                "change_24h": change_24h,
                "change_7d": change_7d,
                "market_cap": mktcap,
                "volume_24h": volume,
                "score": score,
                "signal": signal,
                "image": c.get("image", ""),
            })
    opps.sort(key=lambda x: x["score"], reverse=True)
    return {"opportunities": opps[:10]}

@app.get("/api/v1/ai/analyses")
async def get_analyses(user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("""SELECT id, symbol, asset_type, created_at,
        json_extract(analysis, '$.recommendation') as recommendation,
        json_extract(analysis, '$.score_global') as score_global
        FROM ai_analyses WHERE user_id=? ORDER BY created_at DESC LIMIT 20""",
        (user["id"],)).fetchall()
    conn.close()
    return {"analyses": [dict(r) for r in rows]}

# ══════════════════════════════════════════════════════════════
#  DCA PLANS
# ══════════════════════════════════════════════════════════════
@app.get("/api/v1/dca")
async def get_dca_plans(user=Depends(get_current_user)):
    conn = get_db()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM dca_plans WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()]
    conn.close()
    return {"plans": rows}

@app.post("/api/v1/dca")
async def save_dca_plan(plan: dict, user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("""INSERT INTO dca_plans
        (user_id, name, symbol, asset_type, amount_per_period, frequency, total_budget, notes)
        VALUES (?,?,?,?,?,?,?,?)""",
        (user["id"], plan.get("name", plan.get("symbol", "") + " DCA"),
         plan.get("symbol", ""), plan.get("asset_type", "crypto"),
         plan.get("montant_par_periode", 0), plan.get("frequence", "mensuel"),
         plan.get("total_budget", 0), json.dumps(plan)))
    conn.commit(); conn.close()
    return {"success": True}

# ══════════════════════════════════════════════════════════════
#  SIMULATION
# ══════════════════════════════════════════════════════════════
@app.get("/api/v1/simulation/accounts")
async def get_sim_accounts(user=Depends(get_current_user)):
    conn = get_db()
    accounts = [dict(r) for r in conn.execute(
        "SELECT * FROM simulation_accounts WHERE user_id=?", (user["id"],)).fetchall()]
    conn.close()
    return {"accounts": accounts}

@app.post("/api/v1/simulation/accounts")
async def create_sim_account(req: SimAccountRequest, user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("INSERT INTO simulation_accounts (user_id, name, initial_capital, current_capital, currency) VALUES (?,?,?,?,?)",
                 (user["id"], req.name, req.initial_capital, req.initial_capital, req.currency))
    conn.commit(); conn.close()
    return {"success": True}

@app.post("/api/v1/simulation/accounts/{account_id}/trade")
async def sim_trade(account_id: int, req: SimTradeRequest, user=Depends(get_current_user)):
    conn = get_db()
    acc = conn.execute("SELECT * FROM simulation_accounts WHERE id=? AND user_id=?",
                       (account_id, user["id"])).fetchone()
    if not acc:
        conn.close()
        raise HTTPException(404, "Compte introuvable")
    total = req.quantity * req.price
    new_capital = acc["current_capital"]
    pnl = 0
    if req.side == "buy":
        if total > new_capital:
            conn.close()
            raise HTTPException(400, f"Capital insuffisant (${new_capital:,.2f} disponible)")
        new_capital -= total
        pos = conn.execute("SELECT * FROM simulation_positions WHERE account_id=? AND symbol=?",
                           (account_id, req.symbol.upper())).fetchone()
        if pos:
            new_qty = pos["quantity"] + req.quantity
            new_avg = ((pos["quantity"] * pos["avg_cost"]) + (req.quantity * req.price)) / new_qty
            conn.execute("UPDATE simulation_positions SET quantity=?, avg_cost=? WHERE id=?",
                         (new_qty, new_avg, pos["id"]))
        else:
            conn.execute("INSERT INTO simulation_positions (account_id, symbol, quantity, avg_cost) VALUES (?,?,?,?)",
                         (account_id, req.symbol.upper(), req.quantity, req.price))
    else:
        pos = conn.execute("SELECT * FROM simulation_positions WHERE account_id=? AND symbol=?",
                           (account_id, req.symbol.upper())).fetchone()
        if not pos or pos["quantity"] < req.quantity:
            conn.close()
            raise HTTPException(400, "Position insuffisante pour vendre")
        pnl = (req.price - pos["avg_cost"]) * req.quantity
        new_capital += total
        new_qty = pos["quantity"] - req.quantity
        if new_qty <= 0:
            conn.execute("DELETE FROM simulation_positions WHERE id=?", (pos["id"],))
        else:
            conn.execute("UPDATE simulation_positions SET quantity=? WHERE id=?", (new_qty, pos["id"]))
    conn.execute("INSERT INTO simulation_trades (account_id, symbol, side, quantity, price, total, pnl) VALUES (?,?,?,?,?,?,?)",
                 (account_id, req.symbol.upper(), req.side, req.quantity, req.price, total, pnl))
    conn.execute("UPDATE simulation_accounts SET current_capital=? WHERE id=?", (new_capital, account_id))
    conn.commit(); conn.close()
    return {"success": True, "new_capital": new_capital, "pnl": pnl}

@app.get("/api/v1/simulation/accounts/{account_id}/positions")
async def get_sim_positions(account_id: int, user=Depends(get_current_user)):
    conn = get_db()
    acc = conn.execute("SELECT * FROM simulation_accounts WHERE id=? AND user_id=?",
                       (account_id, user["id"])).fetchone()
    if not acc:
        conn.close()
        raise HTTPException(403, "Accès refusé")
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM simulation_positions WHERE account_id=?", (account_id,)).fetchall()]
    trades = [dict(r) for r in conn.execute(
        "SELECT * FROM simulation_trades WHERE account_id=? ORDER BY created_at DESC LIMIT 50", (account_id,)).fetchall()]
    all_trades = [dict(r) for r in conn.execute(
        "SELECT side, pnl FROM simulation_trades WHERE account_id=?", (account_id,)).fetchall()]
    conn.close()

    open_value = 0.0
    unrealized = 0.0
    if positions:
        syms = [p["symbol"] for p in positions]
        prices = await fetch_crypto_prices(syms)
        for p in positions:
            px = prices.get(p["symbol"], {}).get("price", p["avg_cost"])
            p["current_price"] = px
            p["value"] = px * p["quantity"]
            p["pnl"] = (px - p["avg_cost"]) * p["quantity"]
            p["pnl_pct"] = ((px - p["avg_cost"]) / p["avg_cost"] * 100) if p["avg_cost"] else 0
            open_value += p["value"]
            unrealized += p["pnl"]

    # ── Récapitulatif de performance ──
    initial = acc["initial_capital"] or 0
    cash = acc["current_capital"] or 0
    equity = cash + open_value
    sells = [t for t in all_trades if t["side"] == "sell"]
    wins = [t for t in sells if (t["pnl"] or 0) > 0]
    realized = sum((t["pnl"] or 0) for t in sells)
    pnls = [(t["pnl"] or 0) for t in sells]
    stats = {
        "initial_capital": round(initial, 2),
        "cash": round(cash, 2),
        "open_value": round(open_value, 2),
        "equity": round(equity, 2),
        "total_return_pct": round(((equity - initial) / initial * 100), 2) if initial else 0,
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "n_trades": len(all_trades),
        "n_closed": len(sells),
        "open_positions": len(positions),
        "win_rate": round(len(wins) / len(sells) * 100, 1) if sells else None,
        "best_trade": round(max(pnls), 2) if pnls else None,
        "worst_trade": round(min(pnls), 2) if pnls else None,
    }
    return {"positions": positions, "trades": trades, "stats": stats}

@app.delete("/api/v1/simulation/accounts/{account_id}")
async def delete_sim_account(account_id: int, user=Depends(get_current_user)):
    conn = get_db()
    if not conn.execute("SELECT id FROM simulation_accounts WHERE id=? AND user_id=?",
                        (account_id, user["id"])).fetchone():
        conn.close()
        raise HTTPException(403, "Accès refusé")
    conn.execute("DELETE FROM simulation_positions WHERE account_id=?", (account_id,))
    conn.execute("DELETE FROM simulation_trades WHERE account_id=?", (account_id,))
    conn.execute("DELETE FROM simulation_accounts WHERE id=? AND user_id=?", (account_id, user["id"]))
    conn.commit(); conn.close()
    return {"success": True}

# ══════════════════════════════════════════════════════════════
#  WALLETS & EXCHANGES
# ══════════════════════════════════════════════════════════════

# Known SPL token mints → symbol mapping
SOL_TOKENS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "So11111111111111111111111111111111111111112": "SOL",
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs": "ETH",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "mSOL",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
    "WENWENvqqNya429ubCdR81ZmD69brwQaaBYY6p3LCpk": "WEN",
    "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux": "HNT",
    "mb1eu7TzEc71KxDpsmsKoucSSuuoGLv1drys1oP2jh6": "MOBILE",
}

async def _enrich_solana_tokens(tokens: list) -> None:
    """Resolve real symbol/name/price/value for SPL tokens via DexScreener
    (indexes Solana memecoins). Mutates the list in place; best-effort."""
    mints = list({t["mint"] for t in tokens if t.get("mint") and t["mint"] != "native"})
    if not mints:
        return
    best: dict = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # DexScreener accepte jusqu'à 30 adresses séparées par des virgules
            for i in range(0, len(mints), 30):
                chunk = mints[i:i + 30]
                r = await client.get(
                    "https://api.dexscreener.com/latest/dex/tokens/" + ",".join(chunk))
                for p in (r.json().get("pairs") or []):
                    if p.get("chainId") != "solana":
                        continue
                    bt = p.get("baseToken") or {}
                    m = bt.get("address")
                    liq = ((p.get("liquidity") or {}).get("usd")) or 0
                    if not m:
                        continue
                    if m not in best or liq > best[m]["liq"]:
                        best[m] = {"liq": liq, "symbol": bt.get("symbol"),
                                   "name": bt.get("name"),
                                   "price": float(p.get("priceUsd") or 0),
                                   "change_24h": (p.get("priceChange") or {}).get("h24")}
    except Exception as e:
        logger.warning(f"DexScreener enrich error: {e}")
    for t in tokens:
        info = best.get(t["mint"])
        if info:
            if info.get("symbol"):
                t["symbol"] = info["symbol"]
            t["name"] = info.get("name") or t.get("name") or ""
            t["price"] = round(info["price"], 8) if info.get("price") else None
            t["change_24h"] = info.get("change_24h")
            t["value"] = round(t["balance"] * info["price"], 2) if info.get("price") else None


async def fetch_solana_wallet(address: str) -> dict:
    """Fetch SOL balance + SPL tokens from a Solana wallet address."""
    try:
        # SOL balance
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.mainnet-beta.solana.com",
                json={"jsonrpc": "2.0", "id": 1, "method": "getBalance",
                      "params": [address]},
                headers={"Content-Type": "application/json"}
            )
            sol_lamports = r.json().get("result", {}).get("value", 0)
            sol_balance = sol_lamports / 1e9

            # SPL token accounts
            r2 = await client.post(
                "https://api.mainnet-beta.solana.com",
                json={"jsonrpc": "2.0", "id": 2,
                      "method": "getTokenAccountsByOwner",
                      "params": [address,
                                 {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                                 {"encoding": "jsonParsed"}]},
                headers={"Content-Type": "application/json"}
            )
            token_accounts = r2.json().get("result", {}).get("value", [])

        WSOL = "So11111111111111111111111111111111111111112"
        tokens = []
        if sol_balance > 0.001:
            tokens.append({"symbol": "SOL", "name": "Solana", "balance": round(sol_balance, 6),
                          "mint": WSOL, "decimals": 9})

        for acc in token_accounts:
            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            mint = info.get("mint", "")
            amount = info.get("tokenAmount", {})
            bal = float(amount.get("uiAmountString", "0") or "0")
            if bal > 0:
                sym = SOL_TOKENS.get(mint, mint[:4] + "…")
                tokens.append({"symbol": sym, "name": "", "balance": round(bal, 6),
                               "mint": mint, "decimals": amount.get("decimals", 0)})

        # Enrichissement nom + symbole + prix + valeur $ via DexScreener
        await _enrich_solana_tokens(tokens)
        # SOL natif identifié proprement
        for t in tokens:
            if t["mint"] == WSOL:
                t["symbol"] = "SOL"; t["name"] = t.get("name") or "Solana"
        tokens.sort(key=lambda t: t.get("value") or 0, reverse=True)
        total_value = round(sum((t.get("value") or 0) for t in tokens), 2)

        return {"chain": "solana", "address": address, "tokens": tokens,
                "token_count": len(tokens), "total_value": total_value}
    except Exception as e:
        logger.error(f"Solana wallet fetch error: {e}")
        raise HTTPException(400, f"Impossible de lire le wallet Solana: {str(e)}")

ETH_RPCS = [
    "https://cloudflare-eth.com",
    "https://rpc.ankr.com/eth",
    "https://ethereum.publicnode.com",
    "https://eth.llamarpc.com",
]

BASE_RPCS = [
    "https://mainnet.base.org",
    "https://base.llamarpc.com",
    "https://rpc.ankr.com/base",
    "https://base-mainnet.public.blastapi.io",
]

# Base chain known tokens (contract -> symbol)
BASE_TOKENS_KNOWN = {
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": "DAI",
    "0x4200000000000000000000000000000000000006": "WETH",
    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": "USDbC",
    "0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4": "TOSHI",
    "0xf6e932ca12afa26665dc4dde7e27be02a7c02e50": "MOCHI",
    "0x940181a94a35a4569e4529a3cdfb74e38fd98631": "AERO",
    "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22": "cbETH",
    "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42": "EURC",
}

async def fetch_evm_balance(address: str, rpcs: list) -> float:
    """Get native token balance from any EVM chain RPC."""
    async with httpx.AsyncClient(timeout=12) as client:
        for rpc in rpcs:
            try:
                r = await client.post(rpc,
                    json={"jsonrpc":"2.0","method":"eth_getBalance",
                          "params":[address,"latest"],"id":1},
                    headers={"Content-Type":"application/json"})
                if r.status_code == 200 and r.text.strip():
                    data = r.json()
                    if "result" in data:
                        return int(data["result"], 16) / 1e18
            except Exception as e:
                logger.warning(f"RPC {rpc} failed: {e}")
    return 0.0

async def fetch_base_tokens_ankr(address: str) -> list:
    """Fetch Base chain token balances via Ankr's free multi-chain API."""
    tokens = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://rpc.ankr.com/multichain",
                json={
                    "jsonrpc": "2.0", "method": "ankr_getAccountBalance",
                    "params": {
                        "blockchain": ["base"],
                        "walletAddress": address,
                        "onlyWhitelisted": False,
                        "pageSize": 50
                    }, "id": 1
                },
                headers={"Content-Type": "application/json"}
            )
            if r.status_code == 200 and r.text.strip():
                data = r.json()
                assets = data.get("result", {}).get("assets", [])
                for a in assets:
                    sym = a.get("tokenSymbol", "") or a.get("contractAddress","")[:6]
                    bal = float(a.get("balance", 0) or 0)
                    usd = float(a.get("balanceUsd", 0) or 0)
                    price = float(a.get("tokenPrice", 0) or 0)
                    if sym and bal > 0:
                        tokens.append({
                            "symbol": sym.upper(),
                            "balance": round(bal, 8),
                            "usd_value": round(usd, 4),
                            "price_usd": round(price, 8),
                            "contract": a.get("contractAddress","native"),
                            "name": a.get("tokenName", sym),
                        })
    except Exception as e:
        logger.warning(f"Ankr multichain error: {e}")
    return tokens

async def fetch_base_tokens_moralis(address: str) -> list:
    """Fetch Base chain tokens via Moralis free tier."""
    tokens = []
    moralis_key = ENV.get("MORALIS_API_KEY", "")
    if not moralis_key:
        return tokens
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(
                f"https://deep-index.moralis.io/api/v2.2/{address}/erc20",
                params={"chain": "base"},
                headers={"X-API-Key": moralis_key}
            )
            if r.status_code == 200:
                for t in r.json().get("result", []):
                    bal_raw = int(t.get("balance", "0") or "0")
                    dec = int(t.get("decimals", "18") or "18")
                    bal = bal_raw / (10 ** min(dec, 18))
                    if bal > 0:
                        tokens.append({
                            "symbol": (t.get("symbol","") or "").upper(),
                            "balance": round(bal, 8),
                            "usd_value": 0,
                            "price_usd": 0,
                            "contract": t.get("token_address",""),
                            "name": t.get("name",""),
                        })
    except Exception as e:
        logger.warning(f"Moralis Base error: {e}")
    return tokens

async def fetch_ethereum_wallet(address: str, etherscan_key: str = "") -> dict:
    """Fetch ETH balance + ERC20 tokens from an Ethereum wallet."""
    tokens = []
    eth_balance = 0

    # Try multiple RPCs for ETH balance
    async with httpx.AsyncClient(timeout=12) as client:
        for rpc in ETH_RPCS:
            try:
                r = await client.post(rpc,
                    json={"jsonrpc":"2.0","method":"eth_getBalance",
                          "params":[address,"latest"],"id":1},
                    headers={"Content-Type":"application/json"})
                if r.status_code == 200 and r.text.strip():
                    data = r.json()
                    hex_bal = data.get("result","0x0") or "0x0"
                    eth_balance = int(hex_bal, 16) / 1e18
                    break
            except Exception as e:
                logger.warning(f"ETH RPC {rpc} failed: {e}")
                continue

        if eth_balance > 0.0001:
            tokens.append({"symbol":"ETH","balance":round(eth_balance,6),
                           "contract":"native","decimals":18})

        # ERC20 tokens via Etherscan
        key = etherscan_key or ""
        if key and key != "YourApiKeyToken":
            try:
                r2 = await client.get("https://api.etherscan.io/api",
                    params={"module":"account","action":"tokentx","address":address,
                            "startblock":0,"endblock":99999999,"sort":"desc",
                            "apikey":key,"offset":50,"page":1}, timeout=10)
                if r2.status_code == 200 and r2.text.strip().startswith("{"):
                    data2 = r2.json()
                    if data2.get("status") == "1":
                        seen = set()
                        for tx in data2.get("result",[]):
                            sym = tx.get("tokenSymbol","")
                            contract = tx.get("contractAddress","")
                            if not sym or not contract or sym in seen:
                                continue
                            seen.add(sym)
                            try:
                                r3 = await client.get("https://api.etherscan.io/api",
                                    params={"module":"account","action":"tokenbalance",
                                            "contractaddress":contract,"address":address,
                                            "tag":"latest","apikey":key}, timeout=8)
                                if r3.status_code==200 and r3.text.strip().startswith("{"):
                                    raw = int(r3.json().get("result","0") or "0")
                                    dec = int(tx.get("tokenDecimal","18") or "18")
                                    bal = raw / (10**min(dec,18))
                                    if bal > 0:
                                        tokens.append({"symbol":sym,"balance":round(bal,6),
                                                       "contract":contract,"decimals":dec})
                            except Exception:
                                pass
                            if len(tokens) >= 20:
                                break
            except Exception as e:
                logger.warning(f"Etherscan ERC20 error: {e}")
        else:
            # Without API key, try Ethplorer free API
            try:
                r_ep = await client.get(
                    f"https://api.ethplorer.io/getAddressInfo/{address}",
                    params={"apiKey":"freekey"}, timeout=10)
                if r_ep.status_code == 200 and r_ep.text.strip().startswith("{"):
                    ep = r_ep.json()
                    for t in ep.get("tokens",[]):
                        info = t.get("tokenInfo",{})
                        sym = info.get("symbol","")
                        dec = int(info.get("decimals","18") or "18")
                        raw_bal = float(t.get("balance",0) or 0)
                        bal = raw_bal / (10**min(dec,18))
                        if sym and bal > 0:
                            tokens.append({"symbol":sym,"balance":round(bal,6),
                                          "contract":info.get("address",""),
                                          "decimals":dec})
                        if len(tokens) >= 20:
                            break
            except Exception as e:
                logger.warning(f"Ethplorer fallback error: {e}")

    return {"chain":"ethereum","address":address,
            "tokens":tokens,"token_count":len(tokens)}

async def fetch_base_wallet(address: str) -> dict:
    """Fetch ETH + token balances on Base chain (chain ID 8453)."""
    tokens = []

    # 1. Native ETH balance on Base
    eth_balance = await fetch_evm_balance(address, BASE_RPCS)
    if eth_balance > 0.0000001:
        tokens.append({"symbol": "ETH", "balance": round(eth_balance, 8),
                       "contract": "native", "decimals": 18,
                       "usd_value": 0, "price_usd": 0})

    # 2. Try Ankr multi-chain free API (best free option for Base)
    ankr_tokens = await fetch_base_tokens_ankr(address)
    if ankr_tokens:
        # Filter out ETH duplicate if Ankr returned it
        seen_syms = {"ETH"} if eth_balance > 0 else set()
        for t in ankr_tokens:
            sym = t.get("symbol", "").upper()
            if sym and sym not in seen_syms:
                seen_syms.add(sym)
                tokens.append(t)
    else:
        # 3. Blockscout free public API for Base (no key needed)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"https://base.blockscout.com/api/v2/addresses/{address}/tokens",
                    params={"type": "ERC-20"},
                    headers={"Accept": "application/json"}
                )
                if r.status_code == 200:
                    data = r.json()
                    for item in data.get("items", []):
                        token = item.get("token", {})
                        sym = (token.get("symbol") or "").upper()
                        dec = int(token.get("decimals") or "18")
                        raw_val = item.get("value", "0") or "0"
                        bal = int(raw_val) / (10 ** min(dec, 18))
                        if sym and bal > 0:
                            tokens.append({
                                "symbol": sym,
                                "balance": round(bal, 8),
                                "contract": token.get("address", ""),
                                "decimals": dec,
                                "usd_value": 0,
                                "price_usd": 0,
                                "name": token.get("name", sym),
                            })
        except Exception as e:
            logger.warning(f"Blockscout Base fallback error: {e}")

    # 4. Enrich with prices (Base-specific CoinGecko IDs)
    BASE_COINGECKO_IDS = {
        "TOSHI": "toshi", "MOCHI": "mochi-the-cat-coin",
        "AERO": "aerodrome-finance", "WETH": "weth",
        "CBETH": "coinbase-wrapped-staked-eth", "BRETT": "brett",
        "DEGEN": "degen-base", "BALD": "bald",
        "HIGHER": "higher", "NORMIE": "normie",
        "SATO": "sato", "RUSSELL": "russell-2000-meme",
        "ETH": "ethereum",
    }
    syms_to_price = [t["symbol"] for t in tokens if t.get("balance", 0) > 0]
    prices = {}
    if syms_to_price:
        try:
            # Map symbols to CoinGecko IDs
            cg_id_map = {s: BASE_COINGECKO_IDS.get(s, s.lower()) for s in syms_to_price}
            ids_str = ",".join(set(cg_id_map.values()))
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": ids_str, "vs_currencies": "usd"},
                    headers={"Accept": "application/json"}
                )
                if r.status_code == 200:
                    cg_data = r.json()
                    for sym, cg_id in cg_id_map.items():
                        if cg_id in cg_data:
                            prices[sym] = cg_data[cg_id].get("usd", 0)
        except Exception as e:
            logger.warning(f"Base price fetch error: {e}")

    total_usd = 0
    for t in tokens:
        sym = t["symbol"]
        if sym in prices and prices[sym]:
            t["price_usd"] = round(prices[sym], 8)
            t["usd_value"] = round(t["balance"] * prices[sym], 4)
        total_usd += t.get("usd_value", 0)

    return {
        "chain": "base", "address": address,
        "tokens": tokens, "token_count": len(tokens),
        "total_usd": round(total_usd, 2)
    }


async def fetch_binance_balances(api_key: str, api_secret: str) -> dict:
    """Fetch spot balances from Binance using read-only API keys."""
    try:
        timestamp = int(time.time() * 1000)
        query = f"timestamp={timestamp}"
        sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.binance.com/api/v3/account",
                params={"timestamp": timestamp, "signature": sig},
                headers={"X-MBX-APIKEY": api_key}
            )
            data = r.json()

        if "code" in data:
            raise HTTPException(400, f"Binance API error: {data.get('msg', 'Clé invalide')}")

        balances = []
        for b in data.get("balances", []):
            free = float(b.get("free", 0))
            locked = float(b.get("locked", 0))
            total = free + locked
            if total > 0:
                balances.append({
                    "symbol": b["asset"],
                    "free": round(free, 8),
                    "locked": round(locked, 8),
                    "total": round(total, 8)
                })

        return {"exchange": "binance", "balances": balances,
                "total_assets": len(balances)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Binance API error: {e}")
        raise HTTPException(400, f"Erreur Binance: {str(e)}")

ANKR_CHAINS = {
    "eth": "eth", "ethereum": "eth", "base": "base", "polygon": "polygon",
    "bsc": "bsc", "arbitrum": "arbitrum", "optimism": "optimism",
    "avalanche": "avalanche", "avax": "avalanche", "fantom": "fantom",
}

_KRAKEN_SYM_MAP = {
    "XBT": "BTC", "XXBT": "BTC", "XETH": "ETH", "XDG": "DOGE", "XXDG": "DOGE",
    "XLTC": "LTC", "XXLM": "XLM", "XXRP": "XRP", "XREP": "REP", "XMLN": "MLN",
    "XZEC": "ZEC", "XETC": "ETC", "ZUSD": "USD", "ZEUR": "EUR", "ZGBP": "GBP",
    "ZCAD": "CAD", "ZJPY": "JPY", "ZAUD": "AUD",
}

def _normalize_cex_symbol(sym: str) -> str:
    """Ramène un symbole d'exchange à son actif de base.
    Ex: ETH2.S->ETH, BTC.B->BTC, SOL03.S->SOL, XBT->BTC, ZUSD->USD.
    """
    import re
    s = (sym or "").upper().strip()
    s = s.split(".")[0]                      # retire .S /.B /.T /.M (staking, bonded, tokenisé)
    if s in _KRAKEN_SYM_MAP:
        return _KRAKEN_SYM_MAP[s]
    s2 = re.sub(r"\d+$", "", s)              # ETH2->ETH, SOL03->SOL
    return s2 or s

def _cex_balances_sync(exchange_id: str, key: str, secret: str, password: str = "") -> dict:
    """Bloc synchrone (ccxt utilise `requests` — fiable ici, contrairement au client async)."""
    import ccxt
    if exchange_id not in ccxt.exchanges:
        raise ValueError("__UNSUPPORTED__")
    # Nettoyage : espaces / retours-ligne collés au copier-coller cassent la signature
    cfg = {"apiKey": (key or "").strip(), "secret": (secret or "").strip(),
           "enableRateLimit": True, "timeout": 20000}
    if password:
        cfg["password"] = password.strip()
    ex = getattr(ccxt, exchange_id)(cfg)
    return ex.fetch_balance()

async def fetch_cex_balances(exchange_id: str, key: str, secret: str, password: str = "") -> dict:
    """Solde de N'IMPORTE QUEL exchange via ccxt (105+ supportés, lecture seule)."""
    import ccxt
    exchange_id = exchange_id.lower().strip()
    if exchange_id not in ccxt.exchanges:
        raise HTTPException(400, f"Exchange '{exchange_id}' non supporté")
    try:
        # ccxt synchrone dans un thread : son client async (aiohttp) échoue sur ce serveur
        bal = await asyncio.to_thread(_cex_balances_sync, exchange_id, key, secret, password)
    except ccxt.AuthenticationError as e:
        raise HTTPException(400,
            f"Clé {exchange_id} refusée ({str(e)[:90]}). Vérifie : 1) la Clé API ET le "
            f"Secret (sur Kraken, le « Private Key ») sont bien copiés en entier, sans espace ; "
            f"2) la clé a la permission « Query Funds » ; 3) clé non expirée. Recrée-la si besoin.")
    except ccxt.PermissionDenied as e:
        raise HTTPException(400, f"Permissions insuffisantes ({exchange_id}) — autorisez « Query Funds/Balance ». Détail: {str(e)[:140]}")
    except Exception as e:
        raise HTTPException(400, f"Erreur {exchange_id}: {str(e)[:180] or 'connexion impossible'}")
    totals = bal.get("total", {}) or {}
    free = bal.get("free", {}) or {}
    used = bal.get("used", {}) or {}
    # Normalise (ETH2.S->ETH, BTC.B->BTC, XBT->BTC…) puis regroupe les doublons
    merged = {}
    for sym, amt in totals.items():
        try:
            amt = float(amt or 0)
        except Exception:
            continue
        if amt <= 0:
            continue
        canon = _normalize_cex_symbol(sym)
        m = merged.setdefault(canon, {"symbol": canon, "total": 0.0, "free": 0.0,
                                      "locked": 0.0, "raw": []})
        m["total"] += amt
        m["free"] += float(free.get(sym, 0) or 0)
        m["locked"] += float(used.get(sym, 0) or 0)
        if str(sym).upper() != canon:
            m["raw"].append(str(sym).upper())
    balances = sorted(merged.values(), key=lambda b: b["total"], reverse=True)
    return {"chain": "exchange", "exchange": exchange_id,
            "balances": balances, "total_assets": len(balances)}

async def fetch_evm_generic(chain: str, address: str) -> dict:
    """Soldes d'une chaîne EVM quelconque via Ankr multichain (natif + ERC-20)."""
    blockchain = ANKR_CHAINS.get(chain.lower().strip(), "eth")
    tokens = []
    total_usd = 0.0
    try:
        async with httpx.AsyncClient(timeout=18) as client:
            r = await client.post(
                "https://rpc.ankr.com/multichain",
                json={"jsonrpc": "2.0", "method": "ankr_getAccountBalance",
                      "params": {"blockchain": [blockchain], "walletAddress": address,
                                 "onlyWhitelisted": True, "pageSize": 50}, "id": 1},
                headers={"Content-Type": "application/json"})
            if r.status_code == 200 and r.text.strip():
                for a in r.json().get("result", {}).get("assets", []):
                    sym = (a.get("tokenSymbol") or "").upper()
                    bal = float(a.get("balance", 0) or 0)
                    usd = float(a.get("balanceUsd", 0) or 0)
                    price = float(a.get("tokenPrice", 0) or 0)
                    if sym and bal > 0:
                        total_usd += usd
                        tokens.append({"symbol": sym, "balance": round(bal, 8),
                                       "usd_value": round(usd, 4), "price_usd": round(price, 8),
                                       "contract": a.get("contractAddress", "native"),
                                       "name": a.get("tokenName", sym)})
    except Exception as e:
        logger.warning(f"EVM generic ({blockchain}) error: {e}")
    if not tokens:
        # repli : au moins le solde natif via RPC public
        rpcs = {"eth": ETH_RPCS, "base": BASE_RPCS}.get(blockchain, ETH_RPCS)
        native = await fetch_evm_balance(address, rpcs)
        if native > 0:
            nsym = {"eth": "ETH", "base": "ETH", "polygon": "MATIC", "bsc": "BNB",
                    "avalanche": "AVAX", "fantom": "FTM"}.get(blockchain, "ETH")
            tokens.append({"symbol": nsym, "balance": round(native, 6),
                           "usd_value": 0, "contract": "native", "name": nsym})
    return {"chain": "evm", "evm_chain": blockchain, "address": address,
            "tokens": tokens, "token_count": len(tokens), "total_usd": round(total_usd, 2)}

class WalletConnectRequest(BaseModel):
    chain: str  # solana | ethereum | base | binance | exchange | evm
    address: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_password: str = ""      # passphrase (OKX, KuCoin, Coinbase...)
    exchange: str = ""          # id ccxt: kraken, okx, bybit, kucoin, coinbase...
    evm_chain: str = ""         # eth | base | polygon | bsc | arbitrum | optimism | avalanche | fantom
    portfolio_id: Optional[int] = None
    import_to_portfolio: bool = False

@app.post("/api/v1/wallets/fetch")
async def fetch_wallet(req: WalletConnectRequest, user=Depends(get_current_user)):
    """Fetch balances from a wallet or exchange."""
    if req.chain == "solana":
        if not req.address:
            raise HTTPException(400, "Adresse Solana requise")
        result = await fetch_solana_wallet(req.address)
    elif req.chain == "ethereum":
        if not req.address:
            raise HTTPException(400, "Adresse Ethereum requise")
        result = await fetch_ethereum_wallet(req.address,
                                             ENV.get("ETHERSCAN_API_KEY", ""))
    elif req.chain == "base":
        if not req.address:
            raise HTTPException(400, "Adresse Base chain requise")
        result = await fetch_base_wallet(req.address)
    elif req.chain == "binance":
        if not req.api_key or not req.api_secret:
            raise HTTPException(400, "Clé API et secret Binance requis")
        result = await fetch_binance_balances(req.api_key.strip(), req.api_secret.strip())
    elif req.chain == "exchange":
        if not req.exchange:
            raise HTTPException(400, "Sélectionnez un exchange")
        if not req.api_key or not req.api_secret:
            raise HTTPException(400, "Clé API et secret requis")
        result = await fetch_cex_balances(req.exchange, req.api_key.strip(), req.api_secret.strip(),
                                          (req.api_password or "").strip())
    elif req.chain == "evm":
        if not req.address:
            raise HTTPException(400, "Adresse EVM requise (0x...)")
        result = await fetch_evm_generic(req.evm_chain or "eth", req.address)
    else:
        raise HTTPException(400, f"Chain non supportée: {req.chain}")

    # Optionally import to portfolio
    if req.import_to_portfolio and req.portfolio_id:
        conn = get_db()
        p = conn.execute("SELECT id FROM portfolios WHERE id=? AND user_id=?",
                         (req.portfolio_id, user["id"])).fetchone()
        if not p:
            conn.close()
            raise HTTPException(403, "Portefeuille introuvable")

        STABLE = {"USDT","USDC","BUSD","DAI","TUSD","USDS","FDUSD","PYUSD","FRAX","GUSD","USDC.E","USDBC"}
        tokens = result.get("tokens") or result.get("balances") or []

        # Fetch live prices pour les symboles non-stables (les stables valent ~1$)
        syms = [t.get("symbol","").upper() for t in tokens
                if t.get("symbol","").upper() not in STABLE]
        prices = {}
        try:
            prices = await fetch_crypto_prices(syms) if syms else {}
        except Exception:
            pass

        imported = 0
        for t in tokens:
            sym = (t.get("symbol","") or "").upper().strip()
            bal = float(t.get("balance") or t.get("total") or 0)
            # On importe TOUT, y compris les stablecoins (actifs réels ~1$)
            if not sym or bal <= 0 or len(sym) > 20:
                continue
            if sym in STABLE:
                current_price = 1.0
            else:
                # 1) prix live CoinGecko, sinon 2) prix USD fourni par le wallet
                current_price = prices.get(sym, {}).get("price", 0) or float(t.get("price_usd") or 0)
                if not current_price and t.get("usd_value") and bal:
                    current_price = float(t["usd_value"]) / bal
            source = "Binance" if req.chain == "binance" else (req.exchange.capitalize() if req.chain == "exchange" and req.exchange else req.chain.capitalize())
            existing = conn.execute(
                "SELECT id FROM portfolio_positions WHERE portfolio_id=? AND symbol=?",
                (req.portfolio_id, sym)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE portfolio_positions SET quantity=?, current_price=?, notes=? WHERE id=?",
                    (bal, current_price, f"Sync {source}", existing["id"]))
            else:
                conn.execute("""INSERT INTO portfolio_positions
                    (portfolio_id, symbol, asset_type, quantity, avg_cost, current_price, notes)
                    VALUES (?,?,?,?,?,?,?)""",
                    (req.portfolio_id, sym, "crypto", bal,
                     current_price, current_price, f"Importé depuis {source}"))
            imported += 1
        conn.commit()
        conn.close()
        result["imported_to_portfolio"] = imported

    return result

# ══════════════════════════════════════════════════════════════
#  CONNEXIONS CEX PERSISTANTES (clé chiffrée) + SYNCHRO AUTO
# ══════════════════════════════════════════════════════════════
@app.post("/api/v1/cex/sync")
async def cex_sync(user=Depends(get_current_user)):
    """Resynchronise le portefeuille depuis toutes les connexions CEX stockées."""
    conn = get_db()
    conns = conn.execute("SELECT * FROM cex_connections WHERE user_id=?", (user["id"],)).fetchall()
    if not conns:
        conn.close()
        return {"synced": 0, "imported": 0, "message": "Aucune connexion CEX enregistrée"}
    pf = conn.execute("SELECT id FROM portfolios WHERE user_id=? AND is_default=1", (user["id"],)).fetchone() \
        or conn.execute("SELECT id FROM portfolios WHERE user_id=? LIMIT 1", (user["id"],)).fetchone()
    if not pf:
        conn.close()
        raise HTTPException(400, "Aucun portefeuille")
    pid = pf["id"]
    imported = 0
    errors = []
    for c in conns:
        ex = c["exchange"]
        try:
            res = await fetch_cex_balances(ex, dec_secret(c["api_key_enc"]),
                                           dec_secret(c["api_secret_enc"]),
                                           dec_secret(c["api_password_enc"]))
        except HTTPException as e:
            errors.append(f"{ex}: {e.detail}")
            continue
        except Exception as e:
            errors.append(f"{ex}: {str(e)[:120]}")
            continue
        balances = res.get("balances", [])
        prices = await fetch_crypto_prices([b["symbol"].upper() for b in balances])
        for b in balances:
            sym = (b.get("symbol") or "").upper().strip()
            bal = float(b.get("total") or 0)
            if not sym or bal <= 0 or len(sym) > 20:
                continue
            cur = (prices.get(sym, {}) or {}).get("price", 0) or 0
            existing = conn.execute(
                "SELECT id FROM portfolio_positions WHERE portfolio_id=? AND symbol=?",
                (pid, sym)).fetchone()
            if existing:
                conn.execute("UPDATE portfolio_positions SET quantity=?, notes=? WHERE id=?",
                             (bal, f"Sync {ex.capitalize()}", existing["id"]))
            else:
                conn.execute("""INSERT INTO portfolio_positions
                    (portfolio_id, symbol, asset_type, quantity, avg_cost, current_price, notes)
                    VALUES (?,?,?,?,?,?,?)""",
                    (pid, sym, "crypto", bal, cur, cur, f"Sync {ex.capitalize()}"))
            imported += 1
        conn.execute("UPDATE cex_connections SET last_sync=datetime('now') WHERE id=?", (c["id"],))
    conn.commit()
    conn.close()
    return {"synced": len(conns), "imported": imported, "errors": errors}

@app.post("/api/v1/cex/connect")
async def cex_connect(req: dict, user=Depends(get_current_user)):
    """Teste puis stocke (chiffré) une clé CEX read-only, et synchronise aussitôt."""
    exchange = (req.get("exchange") or "").lower().strip()
    api_key = (req.get("api_key") or "").strip()
    api_secret = (req.get("api_secret") or "").strip()
    api_password = (req.get("api_password") or "").strip()
    if not exchange or not api_key or not api_secret:
        raise HTTPException(400, "exchange, api_key et api_secret requis")
    # Valide la clé avant de stocker (lève une erreur claire si invalide)
    await fetch_cex_balances(exchange, api_key, api_secret, api_password)
    conn = get_db()
    conn.execute("""INSERT INTO cex_connections
        (user_id, exchange, label, api_key_enc, api_secret_enc, api_password_enc)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(user_id, exchange) DO UPDATE SET
          api_key_enc=excluded.api_key_enc, api_secret_enc=excluded.api_secret_enc,
          api_password_enc=excluded.api_password_enc""",
        (user["id"], exchange, exchange.capitalize(),
         enc_secret(api_key), enc_secret(api_secret), enc_secret(api_password)))
    conn.commit()
    conn.close()
    return await cex_sync(user)

@app.get("/api/v1/cex/connections")
async def cex_connections(user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, exchange, label, created_at, last_sync FROM cex_connections WHERE user_id=?",
        (user["id"],)).fetchall()
    conn.close()
    return {"connections": [dict(r) for r in rows]}

@app.delete("/api/v1/cex/connections/{cid}")
async def cex_connection_delete(cid: int, user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM cex_connections WHERE id=? AND user_id=?", (cid, user["id"]))
    conn.commit()
    conn.close()
    return {"deleted": cid}

# ══════════════════════════════════════════════════════════════
#  ADMIN
# ══════════════════════════════════════════════════════════════
@app.get("/api/v1/admin/stats")
async def admin_stats(user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "Accès refusé")
    conn = get_db()
    stats = {
        "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "portfolios": conn.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0],
        "positions": conn.execute("SELECT COUNT(*) FROM portfolio_positions").fetchone()[0],
        "transactions": conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        "alerts": conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0],
        "analyses": conn.execute("SELECT COUNT(*) FROM ai_analyses").fetchone()[0],
        "sim_accounts": conn.execute("SELECT COUNT(*) FROM simulation_accounts").fetchone()[0],
    }
    conn.close()
    return stats

@app.get("/api/v1/admin/users")
async def admin_users(user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "Accès refusé")
    conn = get_db()
    users = [dict(r) for r in conn.execute(
        "SELECT id, email, username, full_name, is_admin, is_active, subscription, created_at FROM users").fetchall()]
    conn.close()
    return {"users": users}

# ══════════════════════════════════════════════════════════════
#  LANDING PUBLIQUE (site marketing) — routes explicites avant le mount
# ══════════════════════════════════════════════════════════════
@app.get("/", include_in_schema=False)
@app.get("/welcome", include_in_schema=False)
@app.get("/landing", include_in_schema=False)
async def landing_page():
    f = STATIC_DIR / "landing.html"
    if f.exists():
        return FileResponse(str(f))
    raise HTTPException(404, "landing.html introuvable")

@app.get("/app", include_in_schema=False)
async def app_spa():
    """Le terminal (SPA) — login puis Institutional Desk."""
    f = STATIC_DIR / "index.html"
    if f.exists():
        return FileResponse(str(f))
    raise HTTPException(404, "index.html introuvable")

# ══════════════════════════════════════════════════════════════
#  STATIC FRONTEND
# ══════════════════════════════════════════════════════════════
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
