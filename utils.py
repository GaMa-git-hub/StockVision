# utils.py
import yfinance as yf
from functools import lru_cache
import time


# ------------------------------
# Cached Yahoo Finance Fetch
# ------------------------------
# Cache lasts as long as server runs
@lru_cache(maxsize=512)
def _fetch_yf(symbol):
    """
    Handles yfinance fetch + fallback history.
    Returns {info, hist}, timestamp
    """
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        hist = t.history(period="2d")  # yesterday + today
        return {"info": info, "hist": hist}, int(time.time())
    except Exception:
        return {"info": {}, "hist": None}, int(time.time())


# ------------------------------
# Map to Yahoo Finance Syntax
# ------------------------------
def map_symbol_for_yahoo(symbol, exchange):
    s = symbol.upper().strip()

    if exchange == "NSE":
        return f"{s}.NS"
    if exchange == "BSE":
        return f"{s}.BO"
    if exchange == "US":
        return s  # no suffix for US

    return s


# ------------------------------
# Live Stock Fetch Function
# ------------------------------
def get_stock_live(symbol, exchange):
    """
    Returns a clean dict:

    {
      "name": str,
      "price": float or None,
      "change": float or None,
      "percent_change": float or None
    }
    """

    yf_sym = map_symbol_for_yahoo(symbol, exchange)

    try:
        data, ts = _fetch_yf(yf_sym)
        info = data.get("info", {})
        hist = data.get("hist")

        # --------------------------
        # Extract Name
        # --------------------------
        name = (
            info.get("shortName")
            or info.get("longName")
            or symbol.upper()
        )

        # --------------------------
        # Extract Current Price
        # --------------------------
        price = (
            info.get("regularMarketPrice")
            or info.get("currentPrice")
        )

        # fallback from history
        if price is None and hist is not None and len(hist) >= 1:
            try:
                price = float(hist["Close"].iloc[-1])
            except:
                price = None

        # --------------------------
        # Previous Close
        # --------------------------
        prev_close = info.get("previousClose")

        if prev_close is None and hist is not None and len(hist) >= 2:
            try:
                prev_close = float(hist["Close"].iloc[-2])
            except:
                prev_close = None

        # --------------------------
        # Compute Change
        # --------------------------
        change = None
        pct = None

        if price is not None and prev_close not in (None, 0):
            try:
                change = round(price - prev_close, 2)
                pct = round((change / prev_close) * 100, 2)
                price = round(price, 2)
            except:
                change = None
                pct = None

        return {
            "name": name,
            "price": price,
            "change": change,
            "percent_change": pct
        }

    except Exception:
        return {
            "name": symbol.upper(),
            "price": None,
            "change": None,
            "percent_change": None
        }
