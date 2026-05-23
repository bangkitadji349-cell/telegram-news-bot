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

# ── Dedup ─────────────────────────────────────────────────────────────────────
seen_hashes: set = set()

# ══════════════════════════════════════════════════════════════════════════════
# KATEGORI & KEYWORD — FX TERMINAL
# ══════════════════════════════════════════════════════════════════════════════

# Mata uang & identitas negara
CURRENCY_MAP = {
    "usd": ["usd", "dollar", "united states", "us economy", "america", "american"],
    "eur": ["eur", "euro", "eurozone", "ecb", "european central bank", "eu economy", "germany", "france", "italy", "spain"],
    "gbp": ["gbp", "pound", "sterling", "boe", "bank of england", "uk economy", "britain", "british"],
    "jpy": ["jpy", "yen", "boj", "bank of japan", "japan economy", "japanese"],
    "cad": ["cad", "canadian dollar", "bank of canada", "boc", "canada economy", "canadian"],
    "aud": ["aud", "australian dollar", "rba", "reserve bank of australia", "australia economy", "australian"],
    "nzd": ["nzd", "new zealand dollar", "rbnz", "reserve bank of new zealand", "new zealand economy"],
    "chf": ["chf", "swiss franc", "snb", "swiss national bank", "switzerland economy", "swiss"],
    "cny": ["cny", "cnh", "yuan", "renminbi", "pboc", "people's bank of china", "china economy", "chinese"],
    "inr": ["inr", "indian rupee", "rbi", "reserve bank of india", "india economy", "indian"],
    "idr": ["idr", "rupiah", "bank indonesia", "bi rate", "indonesia economy", "indonesian"],
    "nok": ["nok", "norwegian krone", "norges bank", "norway economy", "norwegian"],
    "sek": ["sek", "swedish krona", "riksbank", "sweden economy", "swedish"],
    "dkk": ["dkk", "danish krone", "danmarks nationalbank", "denmark economy", "danish"],
    "sgd": ["sgd", "singapore dollar", "mas", "monetary authority of singapore", "singapore economy"],
    "hkd": ["hkd", "hong kong dollar", "hkma", "hong kong economy"],
    "mxn": ["mxn", "mexican peso", "banxico", "banco de mexico", "mexico economy", "mexican"],
    "zar": ["zar", "south african rand", "sarb", "south africa reserve bank", "south africa economy"],
    "try": ["try", "turkish lira", "tcmb", "central bank of turkey", "turkey economy", "turkish"],
    "pln": ["pln", "polish zloty", "nbp", "national bank of poland", "poland economy", "polish"],
    "thb": ["thb", "thai baht", "bank of thailand", "thailand economy", "thai"],
}

ALL_CURRENCY_KEYWORDS = [kw for kws in CURRENCY_MAP.values() for kw in kws]

# Topik ekonomi & kebijakan
MACRO_KEYWORDS = [
    # Bank sentral & suku bunga
    "interest rate", "rate hike", "rate cut", "rate decision", "rate hold",
    "monetary policy", "policy meeting", "policy decision", "policy statement",
    "minutes", "fomc", "mpc", "governing council", "rate expectations",
    "forward guidance", "quantitative easing", "qe", "qt", "tapering",
    "rate cut expectations", "rate hike expectations", "dovish", "hawkish",
    # Data ekonomi
    "inflation", "cpi", "ppi", "core inflation", "gdp", "growth",
    "unemployment", "nonfarm payroll", "nfp", "jobs report", "labor market",
    "retail sales", "industrial production", "manufacturing", "pmi",
    "trade balance", "current account", "balance of payments",
    "consumer confidence", "business confidence", "sentiment",
    "housing", "construction", "ism", "ifo", "zew",
    # Kebijakan pemerintah & fiskal
    "fiscal policy", "government spending", "budget", "deficit", "surplus",
    "debt ceiling", "public debt", "stimulus", "austerity", "tax",
    "government bond", "sovereign", "treasury",
    # Bonds & Yield
    "bond yield", "treasury yield", "gilt yield", "bund yield",
    "yield curve", "10-year", "2-year", "30-year", "spread",
    "bond market", "fixed income", "credit rating", "sovereign rating",
    # Indeks negara (bukan saham individu)
    "s&p 500", "nasdaq", "dow jones", "ftse", "dax", "cac 40",
    "nikkei", "topix", "hang seng", "kospi", "asx 200", "nifty",
    "sensex", "ihsg", "jci", "sti", "set index", "ipc mexico",
    "stock index", "equity index", "market index",
    # Proyeksi & analisis
    "forecast", "outlook", "projection", "target", "expect", "predict",
    "analyst", "estimate", "consensus", "survey", "poll",
    "price target", "currency target", "fx target",
    "bearish", "bullish", "neutral", "overweight", "underweight",
    "upgrade", "downgrade", "revision",
    # Geopolitik & ketidakpastian
    "geopolit", "war", "conflict", "sanction", "tariff", "trade war",
    "election", "political", "uncertainty", "risk",
    "nato", "g7", "g20", "imf", "world bank", "bis",
    "opec", "supply shock", "demand shock",
]

# Komoditas fokus: emas, perak, minyak
COMMODITY_KEYWORDS = [
    "gold", "xau", "emas",
    "silver", "xag", "perak",
    "crude oil", "brent", "wti", "oil price", "minyak",
    # Komoditas lain hanya kalau impact global
    "commodity shock", "energy crisis", "food crisis", "supply disruption",
]

# Kata yang langsung SKIP (saham individu, crypto, dll)
EXCLUDE_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
    "altcoin", "defi", "blockchain", "nft", "solana", "ripple", "xrp",
    "binance", "coinbase", "dogecoin",
    # Saham individu — ciri khas: ticker dalam kurung, earnings call, dll
    "earnings call transcript", "q1 earnings", "q2 earnings", "q3 earnings", "q4 earnings",
    "quarterly earnings", "annual earnings", "revenue growth", "net loss", "net income",
    "stock split", "dividend", "buyback", "ipo ",
]

# Topik geopolitik global yang tetap masuk meski bukan mata uang fokus
GLOBAL_IMPACT_KEYWORDS = [
    "global recession", "world economy", "global economy", "global trade",
    "global inflation", "global growth", "global market", "global risk",
    "geopolit", "world war", "nuclear", "nato", "g7", "g20", "imf",
    "world bank", "wto", "opec", "energy crisis", "food crisis",
    "financial crisis", "systemic risk", "contagion",
]


def passes_filter(title: str) -> bool:
    lower = title.lower()

    # Hapus dulu berita yang jelas tidak relevan
    if any(ex in lower for ex in EXCLUDE_KEYWORDS):
        return False

    # Lolos jika: ada mata uang relevan + topik makro/ekonomi
    has_currency = any(kw in lower for kw in ALL_CURRENCY_KEYWORDS)
    has_macro    = any(kw in lower for kw in MACRO_KEYWORDS)
    has_commodity = any(kw in lower for kw in COMMODITY_KEYWORDS)
    has_global   = any(kw in lower for kw in GLOBAL_IMPACT_KEYWORDS)

    if has_commodity:
        return True
    if has_global:
        return True
    if has_currency and has_macro:
        return True
    if has_currency:
        return True  # berita tentang mata uang apapun tetap masuk

    return False


def detect_category(title: str) -> str:
    lower = title.lower()

    if any(kw in lower for kw in COMMODITY_KEYWORDS[:6]):  # emas, perak, minyak
        return "🛢️ Komoditas"
    if any(kw in lower for kw in ["bond yield", "treasury yield", "gilt yield", "bund yield",
                                    "yield curve", "10-year", "2-year", "spread", "fixed income"]):
        return "🏦 Bonds & Yield"
    if any(kw in lower for kw in ["interest rate", "rate hike", "rate cut", "rate decision",
                                    "monetary policy", "fomc", "mpc", "governing council",
                                    "minutes", "dovish", "hawkish", "rate expectations"]):
        return "🏛️ Kebijakan Bank Sentral"
    if any(kw in lower for kw in ["inflation", "cpi", "ppi", "gdp", "nonfarm", "nfp",
                                    "unemployment", "retail sales", "pmi", "ism", "ifo",
                                    "trade balance", "consumer confidence"]):
        return "📊 Data Ekonomi"
    if any(kw in lower for kw in ["fiscal policy", "government", "budget", "deficit",
                                    "stimulus", "tax", "election", "political", "uncertainty"]):
        return "🏛️ Kebijakan Pemerintah"
    if any(kw in lower for kw in ["s&p 500", "nasdaq", "dow jones", "ftse", "dax", "cac 40",
                                    "nikkei", "hang seng", "kospi", "asx 200", "nifty",
                                    "sensex", "ihsg", "stock index", "equity index"]):
        return "📈 Indeks Negara"
    if any(kw in lower for kw in ["forecast", "outlook", "projection", "target", "expect",
                                    "analyst", "estimate", "consensus", "bearish", "bullish",
                                    "upgrade", "downgrade"]):
        return "📡 Proyeksi & Analisis"
    if any(kw in lower for kw in GLOBAL_IMPACT_KEYWORDS):
        return "🌍 Global Macro"
    if any(kw in lower for kw in ["forex", "currency", "exchange rate", "fx"]):
        return "💱 Forex"

    # Deteksi mata uang spesifik
    for cur, keywords in CURRENCY_MAP.items():
        if any(kw in lower for kw in keywords):
            return f"💱 {cur.upper()}"

    return "📰 Makro"


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


# ── Telegram ──────────────────────────────────────────────────────────────────
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

    category  = detect_category(title)
    translation = translate_to_id(title)
    time_str  = to_wib(published) if published else ""

    lines = [
        f"{category}",
        f"",
        f"🔹 <b>{translation}</b>",
        f"📡 {source}",
    ]
    if time_str:
        lines.append(f"🕐 {time_str}")
    if url:
        lines.append(f"🔗 <a href='{url}'>Baca selengkapnya</a>")

    send_telegram("\n".join(lines), thread_id=TELEGRAM_THREAD_ID)
    log.info(f"Sent [{source}] {category}: {title[:70]}")


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
        "https://www.investing.com/rss/news_301.rss",  # commodities
    ],
    "FXStreet": [
        "https://www.fxstreet.com/rss/news",
    ],
    "ForexLive": [
        "https://www.forexlive.com/feed/news",
    ],
}

rss_seen: dict = {src: set() for src in RSS_FEEDS}


def poll_rss():
    log.info("RSS poller started")
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
                            dt  = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                            pub = dt.strftime("%Y-%m-%d %H:%M UTC")
                        if title:
                            format_and_send(source, title, url, pub)
                except Exception as e:
                    log.error(f"RSS [{source}] error: {e}")
        time.sleep(120)


# ── Finnhub poller ────────────────────────────────────────────────────────────
FINNHUB_CATEGORIES = ["general", "forex", "merger"]

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
                params={
                    "api_token": MARKETAUX_KEY,
                    "language": "en",
                    "limit": 50,
                    "sort": "published_at",
                },
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
COMMAND_HELP = {
    "/forex":    "💱 Forex — berita pergerakan & analisis mata uang",
    "/macro":    "🌍 Global Macro — geopolitik, kebijakan global",
    "/rate":     "🏛️ Kebijakan Bank Sentral — suku bunga, minutes, forward guidance",
    "/data":     "📊 Data Ekonomi — CPI, GDP, NFP, PMI, dll",
    "/bonds":    "🏦 Bonds & Yield — treasury, spread, yield curve",
    "/indeks":   "📈 Indeks Negara — FTSE, DAX, Nikkei, IHSG, dll",
    "/komoditas":"🛢️ Komoditas — Emas, Perak, Minyak",
    "/analisa":  "📡 Proyeksi & Analisis — forecast, target, outlook",
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
                    msg  = update.get("message", {})
                    text = msg.get("text", "").lower().strip()
                    cmd  = text.split("@")[0]

                    if cmd == "/start" or cmd == "/help":
                        lines = [
                            "🤖 <b>FX News Terminal</b>",
                            "",
                            "Memantau berita realtime untuk <b>22 mata uang</b>:",
                            "USD · EUR · GBP · JPY · CAD · AUD · NZD · CHF",
                            "CNY · INR · IDR · NOK · SEK · DKK · SGD · HKD",
                            "MXN · ZAR · TRY · PLN · THB",
                            "",
                            "Sumber: Finnhub, MarketAux, CNBC, MarketWatch,",
                            "Yahoo Finance, Investing.com, FXStreet, ForexLive",
                            "",
                            "<b>Command:</b>",
                        ]
                        for cmd_name, desc in COMMAND_HELP.items():
                            lines.append(f"{cmd_name} — {desc}")
                        send_telegram("\n".join(lines), thread_id=TELEGRAM_THREAD_ID)

                    elif cmd in COMMAND_HELP:
                        desc = COMMAND_HELP[cmd]
                        reply = (
                            f"{desc}\n\n"
                            f"Bot memantau kategori ini secara realtime.\n"
                            f"Berita akan masuk otomatis saat dirilis. ✅"
                        )
                        send_telegram(reply, thread_id=TELEGRAM_THREAD_ID)

        except Exception as e:
            log.error(f"Command handler error: {e}")
        time.sleep(2)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("🚀 FX Terminal Bot started")
    send_telegram(
        "🤖 <b>FX News Terminal Aktif!</b>\n\n"
        "Memantau berita untuk 22 mata uang:\n"
        "USD · EUR · GBP · JPY · CAD · AUD · NZD · CHF · CNY · INR · IDR\n"
        "NOK · SEK · DKK · SGD · HKD · MXN · ZAR · TRY · PLN · THB\n\n"
        "Cakupan: Forex · Kebijakan Bank Sentral · Data Ekonomi\n"
        "Bonds/Yield · Indeks Negara · Komoditas (Emas/Perak/Minyak)\n"
        "Proyeksi Analis · Geopolitik · Ketidakpastian Politik\n\n"
        "Ketik /help untuk command. 🇮🇩",
        thread_id=TELEGRAM_THREAD_ID
    )

    Thread(target=poll_finnhub, daemon=True).start()
    Thread(target=poll_marketaux, daemon=True).start()
    Thread(target=poll_rss, daemon=True).start()
    Thread(target=handle_commands, daemon=True).start()

    while True:
        time.sleep(3600)

