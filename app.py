import os
from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from mysql.connector import IntegrityError

from db import get_db_connection
from utils import get_stock_live, get_cap_category

# ----------------------------------------------------
# APP SETUP
# ----------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-fallback-key")


# ----------------------------------------------------
# HOME
# ----------------------------------------------------
@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/dashboard")
    return redirect("/login")


# ----------------------------------------------------
# LOGIN
# ----------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email")
    password = request.form.get("password")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return render_template("login.html", error="User does not exist")

    if not check_password_hash(user["password"], password):
        return render_template("login.html", error="Incorrect password")

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect("/dashboard")


# ----------------------------------------------------
# REGISTER
# ----------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name")
    email = request.form.get("email")
    password = request.form.get("password")

    if not name or not email or not password:
        return render_template("register.html", error="All fields required")

    hashed_pw = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO users (name, email, password)
            VALUES (%s, %s, %s)
        """, (name, email, hashed_pw))
        conn.commit()
    except IntegrityError:
        conn.close()
        return render_template("login.html", error="User already exists")

    conn.close()
    return redirect("/login")


# ----------------------------------------------------
# DASHBOARD
# ----------------------------------------------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("dashboard.html", active_page="dashboard")


# ----------------------------------------------------
# PORTFOLIO
# ----------------------------------------------------
SECTORS = [
    "All", "IT Industry", "Banking", "Energy", "Financial", "FMCG",
    "Healthcare", "Chemicals", "Real Estate", "Automobile & Ancillaries",
    "Agricultural", "Consumer Durables", "Industrial Products",
    "Hospitality & Travel", "Insurance", "Media & Entertainment",
    "Textile Industry", "Power", "Paints"
]


@app.route("/portfolio", methods=["GET", "POST"])
def portfolio():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # -------- ADD STOCK --------
    if request.method == "POST":
        symbol = request.form["symbol"].upper().strip()
        exchange = request.form["exchange"]

        live = get_stock_live(symbol, exchange)
        company_name = live.get("name") or symbol

        cursor.execute("""
            INSERT INTO portfolio
            (user_id, sector, company_name, symbol, purchase_date,
             exchange, average_purchase_price, quantity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            request.form["sector"],
            company_name,
            symbol,
            request.form["purchase_date"],
            exchange,
            float(request.form["buy_price"]),
            int(request.form["quantity"])
        ))
        conn.commit()

    # -------- FILTER --------
    selected_sector = request.args.get("sector", "All")

    if selected_sector == "All":
        cursor.execute("SELECT * FROM portfolio WHERE user_id=%s", (user_id,))
    else:
        cursor.execute("""
            SELECT * FROM portfolio
            WHERE user_id=%s AND sector=%s
        """, (user_id, selected_sector))

    stocks = cursor.fetchall()
    conn.close()

    # -------- TOTALS --------
    total_invested = 0.0
    total_current = 0.0
    sector_map = {}

    for s in stocks:
        avg = float(s["average_purchase_price"])
        qty = int(s["quantity"])
        invested = avg * qty
        total_invested += invested
        sector_map[s["sector"]] = sector_map.get(s["sector"], 0) + invested

        live = get_stock_live(s["symbol"], s["exchange"])
        price = live.get("price") or avg

        s["category"] = get_cap_category(
            market_cap=live.get("market_cap"),
            exchange=s["exchange"]
        )

        current_value = price * qty
        total_current += current_value

        s["current_price"] = round(price, 2)
        s["gain"] = round(current_value - invested, 2)

    total_pnl = total_current - total_invested
    return_pct = (total_pnl / total_invested * 100) if total_invested else 0

    return render_template(
        "portfolio.html",
        stocks=stocks,
        all_sectors=SECTORS,
        selected_sector=selected_sector,
        sector_labels=list(sector_map.keys()),
        sector_values=list(sector_map.values()),
        total_invested=round(total_invested, 2),
        total_current=round(total_current, 2),
        total_pnl=round(total_pnl, 2),
        return_pct=round(return_pct, 2),
        active_page="portfolio"
    )


# ----------------------------------------------------
# CHART APIs
# ----------------------------------------------------
@app.route("/api/portfolio/cap-allocation")
def cap_allocation_chart():

    if "user_id" not in session:
        return {"error": "not logged in"}, 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT symbol, exchange, average_purchase_price, quantity
        FROM portfolio WHERE user_id=%s
    """, (session["user_id"],))
    rows = cursor.fetchall()
    conn.close()

    cap_totals = {}

    for r in rows:
        live = get_stock_live(r["symbol"], r["exchange"])
        category = get_cap_category(live.get("market_cap"), r["exchange"])
        invested = float(r["average_purchase_price"]) * int(r["quantity"])
        cap_totals[category] = cap_totals.get(category, 0) + invested

    return {"labels": list(cap_totals.keys()), "values": list(cap_totals.values())}


@app.route("/api/portfolio/pnl")
def portfolio_pnl_api():

    if "user_id" not in session:
        return {"error": "not logged in"}, 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT symbol, average_purchase_price, quantity, exchange
        FROM portfolio WHERE user_id=%s
    """, (session["user_id"],))
    rows = cursor.fetchall()
    conn.close()

    labels, pnl, colors = [], [], []

    for r in rows:
        live = get_stock_live(r["symbol"], r["exchange"])
        price = live.get("price") or float(r["average_purchase_price"])

        invested = float(r["average_purchase_price"]) * int(r["quantity"])
        gain = round(price * int(r["quantity"]) - invested, 2)

        labels.append(r["symbol"])
        pnl.append(gain)
        colors.append("#16a34a" if gain >= 0 else "#dc2626")

    return {"labels": labels, "pnl": pnl, "colors": colors}


# ----------------------------------------------------
# LIVE PORTFOLIO
# ----------------------------------------------------
@app.route("/live/portfolio")
def live_portfolio():

    if "user_id" not in session:
        return {"error": "not logged in"}, 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, symbol, company_name, exchange,
               average_purchase_price, quantity
        FROM portfolio
        WHERE user_id=%s
    """, (session["user_id"],))

    rows = cursor.fetchall()
    conn.close()

    data = []

    for r in rows:
        live = get_stock_live(r["symbol"], r["exchange"])
        price = live.get("price")

        if price is None:
            price = float(r["average_purchase_price"])

        gain = (price - float(r["average_purchase_price"])) * int(r["quantity"])

        data.append({
            "id": r["id"],
            "symbol": r["symbol"],
            "company_name": r["company_name"],  # ✅ FIX
            "current_price": round(price, 2),
            "gain": round(gain, 2)
        })

    return {"data": data}

# ----------------------------------------------------
# DELETE PORTFOLIO STOCK
# ----------------------------------------------------
@app.route("/portfolio/delete/<int:id>")
def portfolio_delete(id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM portfolio WHERE id=%s AND user_id=%s",
                   (id, session["user_id"]))
    conn.commit()
    conn.close()

    return redirect("/portfolio")


# ----------------------------------------------------
# WATCHLIST
# ----------------------------------------------------
@app.route("/watchlist", methods=["GET", "POST"])
def watchlist_home():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        name = request.form.get("name")
        if name:
            cursor.execute("""
                INSERT INTO watchlists (user_id, name)
                VALUES (%s, %s)
            """, (session["user_id"], name))
            conn.commit()

    cursor.execute("SELECT * FROM watchlists WHERE user_id=%s", (session["user_id"],))
    watchlists = cursor.fetchall()
    conn.close()

    return render_template("watchlist.html",
                           watchlists=watchlists,
                           active_page="watchlist")


@app.route("/watchlist/<int:id>")
def watchlist_view(id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM watchlists
        WHERE id=%s AND user_id=%s
    """, (id, session["user_id"]))
    wl = cursor.fetchone()

    if not wl:
        conn.close()
        return "Not found", 404

    cursor.execute("SELECT * FROM watchlist_items WHERE watchlist_id=%s", (id,))
    items = cursor.fetchall()
    conn.close()

    enriched = []
    for it in items:
        live = get_stock_live(it["symbol"], it["exchange"])
        enriched.append({
            "id": it["id"],
            "symbol": it["symbol"],
            "company_name": live.get("name") or it["symbol"],
            "price": live.get("price"),
            "change": live.get("change"),
            "percent_change": live.get("percent_change")
        })

    return render_template("watchlist_view.html",
                           wl=wl,
                           items=enriched,
                           active_page="watchlist")


@app.route("/live/watchlist/<int:id>")
def live_watchlist(id):

    if "user_id" not in session:
        return {"error": "not logged in"}, 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM watchlist_items WHERE watchlist_id=%s
    """, (id,))
    items = cursor.fetchall()
    conn.close()

    data = []
    for it in items:
        live = get_stock_live(it["symbol"], it["exchange"])

        data.append({
            "id": it["id"],
            "symbol": it["symbol"],
            "company_name": live.get("name") or it["symbol"],  # ✅ FIX
            "price": live.get("price"),
            "change": live.get("change"),
            "percent_change": live.get("percent_change")
        })

    return {"data": data}



@app.route("/watchlist/<int:id>/add", methods=["POST"])
def watchlist_add(id):

    symbol = request.form["symbol"].upper().strip()
    exchange = request.form["exchange"]

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO watchlist_items (watchlist_id, symbol, exchange)
            VALUES (%s, %s, %s)
        """, (id, symbol, exchange))
        conn.commit()
    except IntegrityError:
        conn.close()
        return redirect(f"/watchlist/{id}?error=duplicate")

    conn.close()
    return redirect(f"/watchlist/{id}")


@app.route("/watchlist/item/<int:item_id>/delete")
def watchlist_item_delete(item_id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT watchlist_id FROM watchlist_items WHERE id=%s", (item_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return "Not found", 404

    wl_id = row["watchlist_id"]
    cursor.execute("DELETE FROM watchlist_items WHERE id=%s", (item_id,))
    conn.commit()
    conn.close()

    return redirect(f"/watchlist/{wl_id}")


@app.route("/watchlist/delete/<int:id>")
def delete_watchlist(id):

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM watchlist_items WHERE watchlist_id=%s", (id,))
    cursor.execute("DELETE FROM watchlists WHERE id=%s AND user_id=%s",
                   (id, session["user_id"]))
    conn.commit()
    conn.close()

    return redirect("/watchlist")


# ----------------------------------------------------
# LOGOUT
# ----------------------------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ----------------------------------------------------
# MAIN
# ----------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5004)
