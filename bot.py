import os
import time
import logging
import requests
import hashlib
from datetime import datetime, timezone
from threading import Thread
from deep_translator import GoogleTranslator

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Env vars ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
FINNHUB_KEY      = os.environ["FINNHUB_KEY"]
MARKETAUX_KEY    = os.environ["MARKETAUX_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ── Dedup cache (in-memory, keyed by article hash) ───────────────────────────
seen_hashes: set[str] = set()

# ── Filter keywords ───────────────────────────────────────────────────────────
# Indeks saham
EQUITY_KEYWORDS = [
    "s&p", "sp500", "s&p 500", "nasdaq", "dow jones", "djia", "nyse",
    "dax", "cac", "ftse", "eurostoxx", "stoxx", "hang seng", "nikkei",
    "kospi", "asx", "nifty", "sensex", "ihsg", "idx", "jci",
    "stock market", "equity", "shares", "pasar saham", "bursa",
]
# FX
FX_KEYWORDS = [
    "usd", "eur", "gbp", "inr", "idr", "cad", "nzd", "aud",
    "cnh", "cny", "jpy", "forex", "currency", "exchange rate",
    "dollar", "euro", "pound", "rupiah", "rupee", "yen",
    "mata uang", "kurs",
]
# Crypto
CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
    "altcoin", "defi", "blockchain", "stablecoin", "usdt", "usdc",
    "binance", "coinbase", "solana", "sol", "xrp", "ripple",
]
# Geopolitik
GEO_KEYWORDS = [
    "geopolit", "war", "conflict", "sanction", "tariff", "trade war",
    "election", "nato", "g7", "g20", "opec", "imf", "world bank",
    "perang", "sanksi", "tarif", "pemilu", "kebijakan",
]
# Bank sentral & kebijakan
POLICY_KEYWORDS = [
    "fed", "federal reserve", "ecb", "boj", "boe", "rba", "rbnz",
    "bank indonesia", "bi rate", "interest rate", "rate hike", "rate cut",
    "inflation", "cpi", "ppi", "gdp", "monetary policy", "fiscal policy",
    "suku bunga", "inflasi", "kebijakan moneter", "kebijakan fiskal",
    "central bank", "bank sentral", "quantitative", "qe", "qt",
]

ALL_KEYWORDS = (
    EQUITY_KEYWORDS + FX_KEYWORDS + CRYPTO_KEYWORDS +
    GEO_KEYWORDS + POLICY_KEYWORDS
)


def passes_filter(text: str) -> bool:
    """Return True if the text matches at least one keyword."""
    lower = text.lower()
    return any(kw in lower for kw in ALL_KEYWORDS)


def make_hash(title: str, url: str = "") -> str:
    raw = (title + url).encode()
    return hashlib.md5(raw).hexdigest()


# ── Translation via Google Translate (gratis, no API key) ────────────────────
def translate_to_id(text: str) -> str:
    """Terjemahkan teks ke Bahasa Indonesia via Google Translate (gratis)."""
    try:
        result = GoogleTranslator(source="auto", target="id").translate(text)
        return result.strip() if result else ""
    except Exception as e:
        log.warning(f"Translate error: {e}")
        return ""


# ── Telegram sender ───────────────────────────────────────────────────────────
def send_telegram(message: str):
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if not resp.ok:
            log.error(f"Telegram error: {resp.text}")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


def format_and_send(source: str, title: str, url: str, published: str):
    h = make_hash(title, url)
    if h in seen_hashes:
        return
    seen_hashes.add(h)

    translation = translate_to_id(title)

    lines = [
        f"📰 <b>[{source}]</b>",
        f"🔹 <b>{title}</b>",
    ]
    if translation and translation.lower() != title.lower():
        lines.append(f"🇮🇩 {translation}")
    if published:
        lines.append(f"🕐 {published}")
    if url:
        lines.append(f"🔗 <a href='{url}'>Baca selengkapnya</a>")

    send_telegram("\n".join(lines))
    log.info(f"Sent [{source}]: {title[:60]}")


# ── Finnhub poller ────────────────────────────────────────────────────────────
FINNHUB_CATEGORIES = ["general", "forex", "crypto", "merger"]

def poll_finnhub():
    log.info("Finnhub poller started")
    # Simpan timestamp terakhir per kategori
    last_ts: dict[str, int] = {c: int(time.time()) for c in FINNHUB_CATEGORIES}

    while True:
        for category in FINNHUB_CATEGORIES:
            try:
                resp = requests.get(
                    "https://finnhub.io/api/v1/news",
                    params={"category": category, "token": FINNHUB_KEY},
                    timeout=15,
                )
                articles = resp.json() if resp.ok else []
                new_articles = [
                    a for a in articles
                    if isinstance(a, dict) and a.get("datetime", 0) > last_ts[category]
                ]
                if new_articles:
                    last_ts[category] = max(a["datetime"] for a in new_articles)
                    for a in sorted(new_articles, key=lambda x: x["datetime"]):
                        title = a.get("headline", "")
                        url   = a.get("url", "")
                        if title and passes_filter(title):
                            ts = a.get("datetime", 0)
                            pub = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else ""
                            format_and_send("Finnhub", title, url, pub)
            except Exception as e:
                log.error(f"Finnhub [{category}] error: {e}")
        time.sleep(60)  # poll tiap 60 detik


# ── MarketAux poller ──────────────────────────────────────────────────────────
MARKETAUX_SYMBOLS = [
    "SPY,QQQ,DIA,EFA,FXI,EWJ,EWG,EWU,EWA,EWZ,EWC,EWD",  # ETF indeks
]
MARKETAUX_FILTER_ENTITIES = [
    "index", "forex", "cryptocurrency", "government", "central_bank",
]

def poll_marketaux():
    log.info("MarketAux poller started")
    last_seen_uuid: set[str] = set()

    # Seed: tandai semua artikel yang sudah ada saat startup
    try:
        resp = requests.get(
            "https://api.marketaux.com/v1/news/all",
            params={
                "api_token": MARKETAUX_KEY,
                "language": "en",
                "limit": 50,
            },
            timeout=15,
        )
        if resp.ok:
            for a in resp.json().get("data", []):
                last_seen_uuid.add(a.get("uuid", ""))
    except Exception as e:
        log.warning(f"MarketAux seed error: {e}")

    while True:
        try:
            resp = requests.get(
                "https://api.marketaux.com/v1/news/all",
                params={
                    "api_token": MARKETAUX_KEY,
                    "language": "en",
                    "limit": 50,
                    "sort": "published_at",
                },
                timeout=15,
            )
            if resp.ok:
                articles = resp.json().get("data", [])
                new_articles = [a for a in articles if a.get("uuid") not in last_seen_uuid]
                for a in new_articles:
                    last_seen_uuid.add(a.get("uuid", ""))
                    title = a.get("title", "")
                    url   = a.get("url", "")
                    pub   = a.get("published_at", "")[:16].replace("T", " ") + " UTC" if a.get("published_at") else ""
                    if title and passes_filter(title):
                        format_and_send("MarketAux", title, url, pub)
        except Exception as e:
            log.error(f"MarketAux error: {e}")
        time.sleep(90)  # poll tiap 90 detik


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("🚀 Bot started")

    # Kirim pesan startup
    send_telegram(
        "🤖 <b>News Bot Aktif!</b>\n"
        "Memantau berita: Indeks Saham (US/EU/UK/Asia), FX, Crypto, "
        "Geopolitik & Kebijakan Bank Sentral.\n"
        "Berita akan dikirim otomatis + terjemahan 🇮🇩"
    )

    # Jalankan kedua poller di thread terpisah
    Thread(target=poll_finnhub, daemon=True).start()
    Thread(target=poll_marketaux, daemon=True).start()

    # Keep-alive
    while True:
        time.sleep(3600)
