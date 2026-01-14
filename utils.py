import requests
import time

FINNHUB_API_KEY = "d4nvmqpr01qk2nue8m40d4nvmqpr01qk2nue8m4g"

# --------------------------------------------
# GLOBAL NSE SESSION
# --------------------------------------------
NSE = requests.Session()

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/get-quotes/equity",
    "Connection": "keep-alive"
}

def nse_bootstrap():
    try:
        NSE.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=3)
    except:
        pass

nse_bootstrap()

# --------------------------------------------
# CACHE
# --------------------------------------------
LIVE_CACHE = {}
CACHE_TTL = 12


# --------------------------------------------
# NSE PRICE (INDIA)
# --------------------------------------------
def get_nse_price(symbol):
    symbol = normalize_nse_symbol(symbol)
    url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"


    try:
        r = NSE.get(url, headers=NSE_HEADERS, timeout=6)
        if "application/json" not in r.headers.get("Content-Type", ""):
            return None

        data = r.json()
        price_info = data.get("priceInfo", {})
        info = data.get("info", {})

        price = price_info.get("lastPrice")
        prev = price_info.get("previousClose")
        market_cap = info.get("marketCap")   # ✅ IMPORTANT

        if price is None or prev is None:
            return None

        return {
            "name": info.get("companyName") or symbol,
            "price": float(price),
            "change": round(price - prev, 2),
            "percent_change": round(((price - prev) / prev) * 100, 2),
            "market_cap": market_cap          # ✅ RETURNED
        }

    except:
        return None

def normalize_nse_symbol(symbol):
    return symbol.replace("&", "%26")

# --------------------------------------------
# FINNHUB (US)
# --------------------------------------------
def get_finnhub_price(symbol):
    try:
        q = requests.get(
            f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}",
            timeout=5
        ).json()

        curr, prev = q.get("c"), q.get("pc")
        if curr is None or prev is None:
            return None

        p = requests.get(
            f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={FINNHUB_API_KEY}",
            timeout=5
        ).json()

        return {
            "name": p.get("name") or symbol,
            "price": float(curr),
            "change": round(curr - prev, 2),
            "percent_change": round(((curr - prev) / prev) * 100, 2),
            "market_cap": p.get("marketCapitalization") * 1_000_000  # 🔥 IMPORTANT
        }

    except:
        return None

# --------------------------------------------
# MASTER ROUTER
# --------------------------------------------
def get_stock_live(symbol, exchange):
    symbol = symbol.upper().strip()
    key = f"{symbol}|{exchange}"

    if key in LIVE_CACHE and time.time() - LIVE_CACHE[key]["ts"] < CACHE_TTL:
        return LIVE_CACHE[key]["data"]

    if exchange in ["NSE", "BSE"]:
        data = get_nse_price(symbol)
    else:
        data = get_finnhub_price(symbol)

    if data is None:
        return {
            "name": symbol,
            "price": None,
            "change": None,
            "percent_change": None,
            "market_cap": None
        }

    LIVE_CACHE[key] = {"data": data, "ts": time.time()}
    return data


# --------------------------------------------
# MARKET CAP CATEGORY
# --------------------------------------------
NSE_KNOWN_CAPS = {
    "RELIANCE": "Large Cap",
    "TCS": "Large Cap",
    "INFY": "Large Cap",
    "HDFCBANK": "Large Cap",
    "ICICIBANK": "Large Cap",
    "SBIN": "Large Cap",
}

def get_cap_category(market_cap, exchange, symbol=None):
    if exchange in ["NSE", "BSE"]:
        return NSE_KNOWN_CAPS.get(symbol, "Mid Cap")  # safe fallback

    if market_cap is None:
        return "N/A"

    market_cap = float(market_cap)

    if market_cap >= 10_000_000_000:
        return "Large Cap"
    elif market_cap >= 2_000_000_000:
        return "Mid Cap"
    else:
        return "Small Cap"
