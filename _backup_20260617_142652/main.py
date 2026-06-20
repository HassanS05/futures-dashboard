"""
HR5 Invest — Institutional Investment Desk
FastAPI + SQLite — Production Grade
"""
import os, json, time, asyncio, hashlib, secrets, sqlite3, io, csv, hmac
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Depends, status, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
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
DEFAULT_AI_PROVIDER = ENV.get("DEFAULT_AI_PROVIDER", "anthropic")
COINGECKO_API_KEY = ENV.get("COINGECKO_API_KEY", "")

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

    # Only use known CoinGecko IDs — don't guess for unknown tokens
    sym_to_id = {s.upper(): COINGECKO_IDS[s.upper()] for s in symbols if s.upper() in COINGECKO_IDS}
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
        _cache[cache_key] = {"data": result, "ts": time.time()}
        return result
    except Exception as e:
        logger.error(f"CoinGecko price error: {e}")
        return {}

async def fetch_top_coins(limit: int = 50) -> List[dict]:
    cache_key = f"top_coins_{limit}"
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 120:
        return _cache[cache_key]["data"]
    try:
        headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "market_cap_desc",
                        "per_page": limit, "page": 1,
                        "sparkline": "false", "price_change_percentage": "1h,24h,7d"},
                headers=headers
            )
            data = r.json()
        _cache[cache_key] = {"data": data, "ts": time.time()}
        return data
    except Exception as e:
        logger.error(f"CoinGecko markets error: {e}")
        return []

async def fetch_fear_greed() -> dict:
    cache_key = "fear_greed"
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 3600:
        return _cache[cache_key]["data"]
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get("https://api.alternative.me/fng/?limit=1")
            d = r.json()["data"][0]
        result = {"value": int(d["value"]), "label": d["value_classification"]}
        _cache[cache_key] = {"data": result, "ts": time.time()}
        return result
    except:
        return {"value": 50, "label": "Neutral"}

async def fetch_etf_data(symbols: List[str]) -> dict:
    cache_key = "etf_" + "_".join(sorted(symbols))
    if cache_key in _cache and time.time() - _cache[cache_key]["ts"] < 300:
        return _cache[cache_key]["data"]
    if not HAS_YFINANCE:
        return {}
    try:
        result = {}
        import yfinance as yf
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                t = tickers.tickers.get(sym)
                if not t:
                    continue
                hist = t.history(period="5d")
                info = t.fast_info
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
        _cache[cache_key] = {"data": result, "ts": time.time()}
        return result
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
        return {}

# ══════════════════════════════════════════════════════════════
#  AI ENGINE
# ══════════════════════════════════════════════════════════════
async def build_market_context(symbol: str, asset_type: str) -> dict:
    """Fetch real market data to enrich AI analysis."""
    ctx = {}
    try:
        if asset_type == "crypto":
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
        if DEFAULT_AI_PROVIDER == "anthropic" and ANTHROPIC_API_KEY and HAS_ANTHROPIC:
            client = anthropic_sdk.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            msg = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}]
            )
            text = msg.content[0].text
        elif OPENAI_API_KEY and HAS_OPENAI:
            client = AsyncOpenAI(api_key=OPENAI_API_KEY)
            resp = await client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8000
            )
            text = resp.choices[0].message.content
        else:
            return {"error": "Configurez ANTHROPIC_API_KEY dans le fichier .env"}

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

    try:
        if DEFAULT_AI_PROVIDER == "anthropic" and ANTHROPIC_API_KEY and HAS_ANTHROPIC:
            client = anthropic_sdk.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=3000,
                system=system,
                messages=messages
            ) as stream:
                async for text in stream.text_stream:
                    yield f"data: {json.dumps({'content': text})}\n\n"
        elif OPENAI_API_KEY and HAS_OPENAI:
            client = AsyncOpenAI(api_key=OPENAI_API_KEY)
            stream = await client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": system}] + messages,
                max_tokens=3000, stream=True
            )
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield f"data: {json.dumps({'content': chunk.choices[0].delta.content})}\n\n"
        else:
            yield f"data: {json.dumps({'content': 'Configurez ANTHROPIC_API_KEY dans le fichier .env'})}\n\n"
    except Exception as e:
        logger.error(f"AI stream error: {e}")
        yield f"data: {json.dumps({'content': f'Erreur IA : {str(e)}'})}\n\n"
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
        if DEFAULT_AI_PROVIDER == "anthropic" and ANTHROPIC_API_KEY and HAS_ANTHROPIC:
            client = anthropic_sdk.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            msg = await client.messages.create(
                model="claude-sonnet-4-6", max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )
            return _safe_json_loads(msg.content[0].text)
        else:
            return {"error": "Provider IA non configuré"}
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

    has_ai = (DEFAULT_AI_PROVIDER == "anthropic" and ANTHROPIC_API_KEY and HAS_ANTHROPIC) \
        or (OPENAI_API_KEY and HAS_OPENAI)
    if not has_ai:
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
        if DEFAULT_AI_PROVIDER == "anthropic" and ANTHROPIC_API_KEY and HAS_ANTHROPIC:
            client = anthropic_sdk.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            msg = await client.messages.create(
                model="claude-sonnet-4-6", max_tokens=8000,
                messages=[{"role": "user", "content": prompt}])
            text = msg.content[0].text
        else:
            client = AsyncOpenAI(api_key=OPENAI_API_KEY)
            resp = await client.chat.completions.create(
                model="gpt-4o", max_tokens=8000,
                messages=[{"role": "user", "content": prompt}])
            text = resp.choices[0].message.content
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

    crypto_prices, etf_prices = {}, {}
    tasks = []
    if crypto_syms:
        crypto_prices = await fetch_crypto_prices(crypto_syms)
    if etf_syms:
        etf_prices = await fetch_etf_data(etf_syms)

    total_value = 0
    total_cost = 0
    for p in positions:
        sym = p["symbol"].upper()
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
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("🚀 HR5 Invest Institutional Desk — http://localhost:8000")
    yield

app = FastAPI(title="HR5 Invest Institutional API", version="2.0.0", lifespan=lifespan)

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
            _cache[cache_key] = {"data": data, "ts": time.time()}
            return {"coins": data}
        return {"coins": []}
    except Exception as e:
        logger.error(f"Memecoins error: {e}")
        return {"coins": []}

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
    if not conn.execute("SELECT id FROM simulation_accounts WHERE id=? AND user_id=?",
                        (account_id, user["id"])).fetchone():
        conn.close()
        raise HTTPException(403, "Accès refusé")
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM simulation_positions WHERE account_id=?", (account_id,)).fetchall()]
    trades = [dict(r) for r in conn.execute(
        "SELECT * FROM simulation_trades WHERE account_id=? ORDER BY created_at DESC LIMIT 50", (account_id,)).fetchall()]
    conn.close()
    if positions:
        syms = [p["symbol"] for p in positions]
        prices = await fetch_crypto_prices(syms)
        for p in positions:
            px = prices.get(p["symbol"], {}).get("price", p["avg_cost"])
            p["current_price"] = px
            p["value"] = px * p["quantity"]
            p["pnl"] = (px - p["avg_cost"]) * p["quantity"]
            p["pnl_pct"] = ((px - p["avg_cost"]) / p["avg_cost"] * 100) if p["avg_cost"] else 0
    return {"positions": positions, "trades": trades}

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

        tokens = []
        if sol_balance > 0.001:
            tokens.append({"symbol": "SOL", "balance": round(sol_balance, 6),
                          "mint": "native", "decimals": 9})

        for acc in token_accounts:
            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            mint = info.get("mint", "")
            amount = info.get("tokenAmount", {})
            bal = float(amount.get("uiAmountString", "0") or "0")
            if bal > 0:
                sym = SOL_TOKENS.get(mint, mint[:6] + "...")
                tokens.append({"symbol": sym, "balance": round(bal, 6), "mint": mint,
                               "decimals": amount.get("decimals", 0)})

        return {"chain": "solana", "address": address,
                "tokens": tokens, "token_count": len(tokens)}
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

class WalletConnectRequest(BaseModel):
    chain: str  # solana | ethereum | base | binance
    address: str = ""
    api_key: str = ""
    api_secret: str = ""
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
        result = await fetch_binance_balances(req.api_key, req.api_secret)
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

        STABLE = {"USDT","USDC","BUSD","DAI","TUSD","USDS","FDUSD","PYUSD","FRAX","GUSD"}
        tokens = result.get("tokens") or result.get("balances") or []

        # Fetch live prices for known symbols
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
            if not sym or bal <= 0 or sym in STABLE or len(sym) > 20:
                continue
            current_price = prices.get(sym, {}).get("price", 0)
            source = "Binance" if req.chain == "binance" else req.chain.capitalize()
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
#  STATIC FRONTEND
# ══════════════════════════════════════════════════════════════
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
