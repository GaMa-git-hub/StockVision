from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from db import get_db_connection
from utils import get_stock_live



app = Flask(__name__)
app.secret_key = "supersecretkey"


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
        return render_template("register.html", error="All fields are required")

    hashed_pw = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO users (name, email, password)
            VALUES (%s, %s, %s)
        """, (name, email, hashed_pw))

        conn.commit()
        conn.close()
        return redirect("/login")

    except mysql.connector.IntegrityError:
        return render_template("login.html",
                               error="User already exists. Please login.")


# ----------------------------------------------------
# DASHBOARD
# ----------------------------------------------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    return render_template("dashboard.html", active_page="dashboard")


# ----------------------------------------------------
# PORTFOLIO SECTORS (unchanged)
# ----------------------------------------------------
SECTORS = [
    "All",
    "IT Industry", "Banking", "Energy", "Financial", "FMCG",
    "Healthcare", "Chemicals", "Real Estate",
    "Automobile & Ancillaries", "Agricultural", "Consumer Durables",
    "Industrial Products", "Hospitality & Travel", "Insurance",
    "Media & Entertainment", "Textile Industry", "Power", "Paints"
]


# ----------------------------------------------------
# PORTFOLIO (unchanged)
# ----------------------------------------------------
@app.route("/portfolio", methods=["GET", "POST"])
def portfolio():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # ADD STOCK
    if request.method == "POST":
        sector = request.form.get("sector")
        company = request.form.get("company_name")
        symbol = request.form.get("symbol")
        purchase_date = request.form.get("purchase_date")
        exchange = request.form.get("exchange")
        avg_price = float(request.form.get("buy_price"))
        quantity = int(request.form.get("quantity"))

        cursor.execute("""
            INSERT INTO portfolio 
            (user_id, sector, company_name, symbol, purchase_date, exchange,
             average_purchase_price, quantity, current_price)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)
        """, (user_id, sector, company, symbol, purchase_date, exchange,
              avg_price, quantity))

        conn.commit()

    # FILTER
    selected_sector = request.args.get("sector", "All")

    if selected_sector == "All":
        cursor.execute("SELECT * FROM portfolio WHERE user_id=%s", (user_id,))
    else:
        cursor.execute("""
            SELECT * FROM portfolio
            WHERE user_id=%s AND sector=%s
        """, (user_id, selected_sector))

    stocks = cursor.fetchall()

    # NO LIVE PRICE YET — placeholders
    for s in stocks:
        s["current_price"] = "N/A"
        s["gain"] = "N/A"

    conn.close()

    return render_template("portfolio.html",
                           all_sectors=SECTORS,
                           selected_sector=selected_sector,
                           stocks=stocks,
                           active_page="portfolio")


# ----------------------------------------------------
# WATCHLISTS
# ----------------------------------------------------
TABLE_WATCHLIST_ITEMS = "watchlist_items"   # <-- FIXED


# SHOW ALL WATCHLISTS (GET + POST)
@app.route("/watchlist", methods=["GET", "POST"])
def watchlist_home():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Create watchlist
    if request.method == "POST":
        name = request.form.get("name")
        if name:
            cursor.execute("""
                INSERT INTO watchlists (user_id, name)
                VALUES (%s, %s)
            """, (session["user_id"], name))
            conn.commit()

    # Fetch all watchlists
    cursor.execute("SELECT * FROM watchlists WHERE user_id=%s", (session["user_id"],))
    watchlists = cursor.fetchall()

    conn.close()

    return render_template("watchlist.html",
                           watchlists=watchlists,
                           active_page="watchlist")


# SHOW ONE WATCHLIST (with live data)
from utils import get_stock_live
from flask import request, render_template

@app.route("/watchlist/<int:id>")
def watchlist_view(id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get watchlist
    cursor.execute("SELECT * FROM watchlists WHERE id=%s AND user_id=%s", (id, session["user_id"]))
    wl = cursor.fetchone()
    if wl is None:
        conn.close()
        return "Watchlist not found", 404

    # Get items
    cursor.execute("SELECT * FROM watchlist_items WHERE watchlist_id=%s", (id,))
    items = cursor.fetchall()
    conn.close()

    # Enrich items with live data
    enriched = []
    for it in items:
        sym = it.get("symbol")
        ex = it.get("exchange")
        live = get_stock_live(sym, ex)

        price = live.get("price")
        change = live.get("change")
        pct = live.get("percent_change")
        name = live.get("name") or sym

        it["company_name"] = name
        it["price"] = price if price is not None else "N/A"
        it["change"] = change if change is not None else "N/A"
        it["percent_change"] = pct if pct is not None else "N/A"

        enriched.append(it)

    # --- Sorting logic ---
    sort = request.args.get("sort")  # expected: 'price', 'change', 'percent_change', 'symbol', 'name'
    direction = request.args.get("dir", "desc").lower()  # 'asc' or 'desc'

    def sort_key_price(x):
        v = x.get("price")
        return float(v) if (isinstance(v, (int,float)) or (isinstance(v,str) and v != "N/A")) else float("-inf")

    def sort_key_change(x):
        v = x.get("change")
        return float(v) if (isinstance(v, (int,float)) or (isinstance(v,str) and v != "N/A")) else float("-inf")

    def sort_key_pct(x):
        v = x.get("percent_change")
        return float(v) if (isinstance(v, (int,float)) or (isinstance(v,str) and v != "N/A")) else float("-inf")

    if sort:
        if sort == "price":
            enriched.sort(key=sort_key_price, reverse=(direction=="desc"))
        elif sort == "change":
            enriched.sort(key=sort_key_change, reverse=(direction=="desc"))
        elif sort in ("percent_change", "pct"):
            enriched.sort(key=sort_key_pct, reverse=(direction=="desc"))
        elif sort == "symbol":
            enriched.sort(key=lambda x: (x.get("symbol") or "").upper(), reverse=(direction=="desc"))
        elif sort == "name":
            enriched.sort(key=lambda x: (x.get("company_name") or "").upper(), reverse=(direction=="desc"))

    # If AJAX request, return the rows partial only
    if request.args.get("ajax") == "1":
        return render_template("partials/watchlist_rows.html", items=enriched)

    # Otherwise render full page
    return render_template("watchlist_view.html", wl=wl, items=enriched, active_page="watchlist", current_sort=sort or "", current_dir=direction)

# ADD ITEM
from mysql.connector import IntegrityError

@app.route("/watchlist/<int:id>/add", methods=["POST"])
def watchlist_add_item(id):

    symbol = request.form.get("symbol", "").upper().strip()
    exchange = request.form.get("exchange")

    if not symbol or not exchange:
        return redirect(f"/watchlist/{id}")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO watchlist_items (watchlist_id, symbol, exchange)
            VALUES (%s, %s, %s)
        """, (id, symbol, exchange))
        conn.commit()

    except IntegrityError:
        # Duplicate entry detected
        conn.close()
        return redirect(f"/watchlist/{id}?error=duplicate")

    conn.close()
    return redirect(f"/watchlist/{id}")
    enriched = enrich_items_with_live_prices(items)

    # ---------------------------------------------------
    # 🔥 THIS IS WHERE YOU PUT THE AJAX CHECK
    # ---------------------------------------------------
    if request.args.get("ajax"):
        return render_template("partials/watchlist_rows.html", items=enriched)

    # 3. Normal page load
    return render_template("watchlist_view.html", items=enriched)



# DELETE ITEM
@app.route("/watchlist/item/<int:item_id>/delete")
def watchlist_delete_item(item_id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(f"SELECT watchlist_id FROM {TABLE_WATCHLIST_ITEMS} WHERE id=%s", (item_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        return "Item not found", 404

    watchlist_id = row["watchlist_id"]

    cursor.execute(f"DELETE FROM {TABLE_WATCHLIST_ITEMS} WHERE id=%s", (item_id,))
    conn.commit()
    conn.close()

    return redirect(f"/watchlist/{watchlist_id}")


# DELETE WATCHLIST
@app.route("/watchlist/delete/<int:id>")
def delete_watchlist(id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(f"DELETE FROM {TABLE_WATCHLIST_ITEMS} WHERE watchlist_id=%s", (id,))
    cursor.execute("DELETE FROM watchlists WHERE id=%s AND user_id=%s",
                   (id, session["user_id"]))

    conn.commit()
    conn.close()

    return redirect("/watchlist")

#------Live price in portfolio -------------------
@app.route("/live/portfolio")
def live_portfolio():
    if "user_id" not in session:
        return {"error": "not logged in"}, 403

    user_id = session["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, symbol, average_purchase_price, quantity, exchange
        FROM portfolio
        WHERE user_id = %s
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()

    results = []

    for r in rows:
        try:
            # FIXED FUNCTION NAME ↓↓↓↓↓
            live = get_stock_live(r["symbol"], r["exchange"])

            current_price = live.get("price")

            if current_price is None:
                raise Exception("No live price")

            gain_value = (current_price - r["average_purchase_price"]) * r["quantity"]

            results.append({
                "id": r["id"],
                "symbol": r["symbol"],
                "current_price": round(current_price, 2),
                "gain": round(gain_value, 2),
            })

        except:
            results.append({
                "id": r["id"],
                "symbol": r["symbol"],
                "current_price": "N/A",
                "gain": "N/A",
            })

    return {"data": results}

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
