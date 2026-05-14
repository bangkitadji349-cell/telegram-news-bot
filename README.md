# 📰 Telegram Financial News Bot

Bot otomatis yang memantau berita keuangan dari **Finnhub** + **MarketAux**,
lalu mengirimkan headline + terjemahan Bahasa Indonesia ke Telegram.

---

## ✅ Cakupan Berita

| Kategori | Detail |
|---|---|
| 📈 Indeks Saham | S&P500, NASDAQ, DJIA, DAX, CAC, FTSE, Nikkei, Hang Seng, IHSG, dll |
| 💱 Forex | USD, EUR, GBP, IDR, INR, CAD, NZD, AUD, CNH, CHF, JPY |
| 🪙 Crypto | BTC, ETH, SOL, XRP, DeFi, Blockchain, dll |
| 🌍 Geopolitik | Perang, sanksi, tarif, pemilu, G7/G20, OPEC |
| 🏦 Kebijakan | Fed, ECB, BI, suku bunga, inflasi, CPI, GDP |

---

## 🚀 Cara Deploy

### 1. Dapatkan Chat ID Telegram

Kirim pesan ke bot kamu, lalu buka URL berikut di browser:
```
https://api.telegram.org/bot<TELEGRAM_TOKEN>/getUpdates
```
Cari field `"chat": {"id": XXXXXXXX}` — itulah Chat ID kamu.

---

### 2. Push ke GitHub

```bash
git init
git add .
git commit -m "init: telegram news bot"
git branch -M main
git remote add origin https://github.com/USERNAME/REPO.git
git push -u origin main
```

---

### 3. Deploy ke Railway

1. Buka [railway.app](https://railway.app) → **New Project → Deploy from GitHub Repo**
2. Pilih repo yang baru dipush
3. Masuk ke tab **Variables**, tambahkan:

| Key | Value |
|---|---|
| `TELEGRAM_TOKEN` | Token dari @BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID dari langkah 1 |
| `FINNHUB_KEY` | API key Finnhub |
| `MARKETAUX_KEY` | API key MarketAux |
| `ANTHROPIC_API_KEY` | API key Anthropic (untuk terjemahan) |

4. Railway otomatis build & deploy. Bot langsung aktif!

---

## 📦 Struktur File

```
telegram-news-bot/
├── bot.py              # Main bot
├── requirements.txt    # Dependencies
├── Procfile            # Railway/Heroku process
├── railway.toml        # Railway config
└── .github/
    └── workflows/
        └── deploy.yml  # Auto-deploy via GitHub Actions (opsional)
```

---

## ⚙️ Cara Kerja

- **Finnhub** di-poll tiap **60 detik** (kategori: general, forex, crypto, merger)
- **MarketAux** di-poll tiap **90 detik**
- Setiap artikel dicek pakai keyword filter
- Artikel baru yang lolos filter → diterjemahkan → dikirim ke Telegram
- Sistem dedup mencegah artikel yang sama dikirim dua kali

---

## 🔧 Tanpa Anthropic API (terjemahan dinonaktifkan)

Kalau tidak punya Anthropic API key, bot tetap jalan tapi tanpa terjemahan.
Cukup hapus/kosongkan variabel `ANTHROPIC_API_KEY` di Railway.
