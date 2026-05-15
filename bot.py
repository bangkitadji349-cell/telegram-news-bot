import os
import time
import logging
import requests
import hashlib
import feedparser
from datetime import datetime, timezone, timedelta
from threading import Thread
from deep_translator import GoogleTranslator

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Env vars ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
TELEGRAM_THREAD_ID = int(os.environ.get("TELEGRAM_THREAD_ID", "9"))
FINNHUB_KEY        = os.environ["FINNHUB_KEY"]
MARKETAUX_KEY      = os.environ["MARKETAUX_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ── Dedup cache ───────────────────────────────────────────────────────────────
seen_hashes: set = set()

# ── Kategori & keyword ────────────────────────────────────────────────────────
CATEGORIES = {
    "🌍 Global Macro": [
        "geopolit", "war", "conflict", "sanction", "tariff", "trade war",
        "election", "nato", "g7", "g20", "opec", "imf", "world bank",
        "supply", "demand", "fed", "federal reserve", "ecb", "boj", "boe",
        "rba", "rbnz", "bank indonesia", "bi rate", "interest rate",
        "rate hike", "rate cut", "inflation", "cpi", "ppi", "gdp",
        "monetary policy", "fiscal policy", "central bank", "quantitative",
        "treasury", "budget", "deficit", "surplus", "recession",
        "stagflation", "yield curve", "perang", "sanksi", "tarif",
        "pemilu", "kebijakan", "suku bunga", "inflasi",
    ],
    "📊 Proyeksi & Analisis": [
        "forecast", "outlook", "projection", "target", "expect", "predict",
        "analyst", "estimate", "rating", "upgrade", "downgrade",
        "price target", "consensus", "survey", "poll", "bearish", "bullish",
        "rate cut expectations", "rate hike expectations",
        "neutral", "overweight", "underweight",
    ],
    "💱 Forex": [
        "usd", "eur", "gbp", "inr", "idr", "cad", "nzd", "aud",
        "cnh", "cny", "jpy", "chf", "forex", "currency", "exchange rate",
        "dollar", "euro", "pound", "rupiah", "rupee", "yen", "fx",
    ],
    "🪙 Crypto & ETF": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
        "altcoin", "defi", "blockchain", "stablecoin", "usdt", "usdc",
        "solana", "sol", "xrp", "ripple", "binance", "coinbase",
        "etf", "spot etf", "crypto etf", "bitcoin etf",
    ],
    "📈 Indeks & Saham": [
        "s&p", "sp500", "nasdaq", "dow jones", "djia", "nyse",
        "dax", "cac", "ftse", "eurostoxx", "hang seng", "nikkei",
        "kospi", "asx", "nifty", "sensex", "ihsg", "idx",
        "stock market", "equity", "shares", "ipo", "earnings",
        "revenue", "profit", "quarterly", "annual report",
    ],
    "🏦 Bonds & Yield": [
        "bond", "yield", "treasury", "sovereign", "coupon",
        "10-year", "2-year", "30-year", "gilt", "bund",
        "spread", "credit", "debt", "issuance",
    ],
    "🛢️ Komoditas": [
        "crude oil", "brent", "wti", "natural gas", "coal",
        "gold", "silver", "copper", "iron ore", "wheat",
        "corn", "soybean", "commodity", "energy",
    ],
}

ALL_KEYWORDS = [kw for kws in CATEGORIES.values() for kw in kws]

def detect_category(text: str) -> str:
    lower = text.lower()
    for cat, keywords in CATEGORIES.items():
        if any(kw in lower for kw in keywords):
            return cat
    return ""

def passes_filter(text: str) -> bool:
    return any(kw in text.lower() for kw in ALL_KEYWORDS)

def make_hash(title: str, url: str = "") -> str:
    return hashlib.md5((title + url).encode()).hexdigest()

# ── Translation ───────────────────────────────────────────────────────────────
def translate_to_id(text: str) -> str:
    try:
        result = GoogleTranslator(source="auto", target="id").translate(text)
        return result.strip() if result else text
    except Exception as e:
        log.warning(f"Translate error: {e}")
        return text

# ── Telegram sender ───────────────────────────────────────────────────────────
def send_telegram(message: str, thread_id: int = None):
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id:
        payload["message_thread_id"] = thread_id
    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=15)
        if not resp.ok:
            log.error(f"Telegram error: {resp.text}")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")

def to_wib(published: str) -> str:
    try:
        if "UTC" in published:
            dt = datetime.strptime(published, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        return (dt + timedelta(hours=7)).strftime("%H:%M WIB")
    except:
        return published

def format_and_send(source: str, title: str, url: str, published: str):
    h = make_hash(title, url)
    if h in seen_hashes:
        return
    seen_hashes.add(h)

    if not passes_filter(title):
        return

    category = detect_category(title)
    label = category if category else "📰 Berita"
    translation = translate_to_id(title)
    time_str = to_wib(published) if published else ""

    lines = [
        f"{label}",
        f"",
        f"🔹 <b>{translation}</b>",
        f"📡 {source}",
    ]
    if time_str:
        lines.append(f"🕐 {time_str}")
    if url:
        lines.append(f"🔗 <a href='{url}'>Baca selengkapnya</a>")

    send_telegram("\n".join(lines), thread_id=TELEGRAM_THREAD_ID)
    log.info(f"Sent [{source}] {label}: {title[:60]}")

# ── RSS Feeds ─────────────────────────────────────────────────────────────────
RSS_FEEDS = {
    "CNBC": [
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://www.cnbc.com/id/10000664/device/rss/rss.html",
        "https://www.cnbc.com/id/100727362/device/rss/rss.html",
    ],
    "MarketWatch": [
        "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
    ],
    "Yahoo Finance": [
        "https://finance.yahoo.com/news/rssindex",
    ],
    "Investing.com": [
        "https://www.investing.com/rss/news.rss",
        "https://www.investing.com/rss/news_25.rss",
        "https://www.investing.com/rss/news_14.rss",
    ],
}

rss_seen: dict = {src: set() for src in RSS_FEEDS}

def poll_rss():
    log.info("RSS poller started")
    # Seed existing entries
    for source, feeds in RSS_FEEDS.items():
        for feed_url in feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    rss_seen[source].add(entry.get("id") or entry.get("link", ""))
            except:
                pass

    while True:
        for source, feeds in RSS_FEEDS.items():
            for feed_url in feeds:
                try:
                    feed = feedparser.parse(feed_url)
                    for entry in feed.entries:
                        eid = entry.get("id") or entry.get("link", "")
                        if eid in rss_seen[source]:
                            continue
                        rss_seen[source].add(eid)
                        title = entry.get("title", "")
                        url   = entry.get("link", "")
                        pub   = ""
                        if entry.get("published_parsed"):
                            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                            pub = dt.strftime("%Y-%m-%d %H:%M UTC")
                        if title:
                            format_and_send(source, title, url, pub)
                except Exception as e:
                    log.error(f"RSS [{source}] error: {e}")
        time.sleep(120)

# ── Finnhub poller ────────────────────────────────────────────────────────────
FINNHUB_CATEGORIES = ["general", "forex", "crypto", "merger"]

def poll_finnhub():
    log.info("Finnhub poller started")
    last_ts: dict = {c: int(time.time()) for c in FINNHUB_CATEGORIES}
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
                        ts    = a.get("datetime", 0)
                        pub   = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else ""
                        if title:
                            format_and_send("Finnhub", title, url, pub)
            except Exception as e:
                log.error(f"Finnhub [{category}] error: {e}")
        time.sleep(60)

# ── MarketAux poller ──────────────────────────────────────────────────────────
def poll_marketaux():
    log.info("MarketAux poller started")
    last_seen_uuid: set = set()
    try:
        resp = requests.get(
            "https://api.marketaux.com/v1/news/all",
            params={"api_token": MARKETAUX_KEY, "language": "en", "limit": 50},
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
                params={"api_token": MARKETAUX_KEY, "language": "en", "limit": 50, "sort": "published_at"},
                timeout=15,
            )
            if resp.ok:
                for a in resp.json().get("data", []):
                    uid = a.get("uuid", "")
                    if uid in last_seen_uuid:
                        continue
                    last_seen_uuid.add(uid)
                    title = a.get("title", "")
                    url   = a.get("url", "")
                    pub   = a.get("published_at", "")[:16].replace("T", " ") + " UTC" if a.get("published_at") else ""
                    if title:
                        format_and_send("MarketAux", title, url, pub)
        except Exception as e:
            log.error(f"MarketAux error: {e}")
        time.sleep(90)

# ── Command handler ───────────────────────────────────────────────────────────
COMMAND_CATEGORIES = {
    "/forex":   "💱 Forex",
    "/bonds":   "🏦 Bonds & Yield",
    "/crypto":  "🪙 Crypto & ETF",
    "/indeks":  "📈 Indeks & Saham",
    "/macro":   "🌍 Global Macro",
    "/komoditas": "🛢️ Komoditas",
}

def handle_commands():
    log.info("Command handler started")
    offset = 0
    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=40,
            )
            if resp.ok:
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "").lower().strip()
                    cmd = text.split("@")[0]  # hapus @botname jika ada

                    if cmd in COMMAND_CATEGORIES:
                        cat_label = COMMAND_CATEGORIES[cmd]
                        reply = (
                            f"{cat_label}\n\n"
                            f"Menampilkan berita <b>{cat_label}</b> terbaru.\n"
                            f"Bot memantau berita ini secara realtime dan akan mengirim otomatis saat ada berita baru. ✅"
                        )
                        send_telegram(reply, thread_id=TELEGRAM_THREAD_ID)

                    elif cmd == "/start" or cmd == "/help":
                        reply = (
                            "🤖 <b>News Bot Aktif!</b>\n\n"
                            "Memantau berita realtime dari:\n"
                            "Finnhub, MarketAux, CNBC, MarketWatch, Yahoo Finance, Investing.com\n\n"
                            "<b>Command:</b>\n"
                            "/forex — Berita Forex\n"
                            "/crypto — Berita Crypto & ETF\n"
                            "/indeks — Berita Indeks & Saham\n"
                            "/bonds — Berita Bonds & Yield\n"
                            "/macro — Berita Global Macro\n"
                            "/komoditas — Berita Komoditas\n"
                            "/help — Bantuan"
                        )
                        send_telegram(reply, thread_id=TELEGRAM_THREAD_ID)
        except Exception as e:
            log.error(f"Command handler error: {e}")
        time.sleep(2)

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("🚀 Bot started")
    send_telegram(
        "🤖 <b>News Bot Aktif!</b>\n"
        "Memantau berita: Indeks Saham (US/EU/UK/Asia), FX, Crypto, "
        "Komoditas, Bonds/Yield, Geopolitik & Kebijakan Bank Sentral.\n"
        "Berita dikirim otomatis + terjemahan 🇮🇩\n\n"
        "Ketik /help untuk melihat command.",
        thread_id=TELEGRAM_THREAD_ID
    )
    Thread(target=poll_finnhub, daemon=True).start()
    Thread(target=poll_marketaux, daemon=True).start()
    Thread(target=poll_rss, daemon=True).start()
    Thread(target=handle_commands, daemon=True).start()

    while True:
        time.sleep(3600)
