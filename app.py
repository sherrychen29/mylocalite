from flask import Flask, session, render_template, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
import sqlite3
import os
import uuid
import random
import hashlib
from datetime import datetime, timedelta

# Config: paths and app settings
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "locallift.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
DB_TIMEOUT = 20
CARDS_PER_ROW = 3
ROWS_PER_PAGE = 5
PER_PAGE = CARDS_PER_ROW * ROWS_PER_PAGE

app = Flask(__name__)
app.secret_key = "wenis"
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB max upload
RATE_LIMIT_SECONDS = 60
MAX_COMMENT_LEN = 250
MAX_USERNAME_LEN = 35


# Database init & seed: create tables and insert demo data if empty
def db_init():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)

    conn = get_conn()
    cursor = conn.cursor()

    # Table: businesses (name, category, description, address, hours, phone)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS business (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        category TEXT,
        description TEXT,
        address TEXT,
        hours TEXT,
        phone TEXT
    )
    """)

    # Table: reviews (business_id, username, rating, comment, created_at, is_flagged)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS review (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER,
        username TEXT,
        rating INTEGER,
        comment TEXT,
        created_at TEXT,
        is_flagged INTEGER
    )
    """)

    # Table: bookmarks (username = anonymous owner id, business_id, created_at)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bookmark (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        business_id INTEGER,
        created_at TEXT
    )
    """)

    # Table: deals (business_id, title, description, coupon_code, expires_at, is_active)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS deal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER,
        title TEXT,
        description TEXT,
        coupon_code TEXT,
        expires_at TEXT,
        is_active INTEGER
    )
    """)

    # Table: verification_attempt (review verification: question, answer_hash, passed, ip)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS verification_attempt (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        business_id INTEGER,
        question TEXT,
        answer_hash TEXT,
        passed INTEGER,
        created_at TEXT,
        ip TEXT
    )
    """)

    # Table: business_photo (business_id, filename, created_at)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS business_photo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        created_at TEXT,
        FOREIGN KEY (business_id) REFERENCES business(id)
    )
    """)

    conn.commit()
    conn.close()


# Return a DB connection with WAL mode for better concurrent reads
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# Get or create anonymous bookmark owner id (stored in session)
def get_bookmark_owner_id() -> str:
    if "bookmark_owner_id" not in session:
        session["bookmark_owner_id"] = str(uuid.uuid4())
    return session["bookmark_owner_id"]


# Insert demo businesses and deals if DB is empty
def seed_data():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM business")
    count = cur.fetchone()[0]
    if count > 0:
        conn.close()
        return

    # Demo businesses: Food, Retail, Services
    businesses = [
        ("Maple Moon Café", "Food", "Cozy café with pastries and espresso drinks.", "123 Bloor St W, Toronto, ON M5S 1W7", "8am–6pm", "(416) 555-0101"),
        ("Saffron Street Eats", "Food", "Quick local eats with vegetarian options.", "88 Spadina Ave, Toronto, ON M5V 2J4", "11am–9pm", "(416) 555-0102"),
        ("Harbourview Noodles", "Food", "Hand-pulled noodles and soups.", "200 Queens Quay W, Toronto, ON M5J 2Y3", "12pm–10pm", "(416) 555-0103"),
        ("Sunny Side Bakery", "Food", "Fresh bread, cakes, and weekend specials.", "45 St Clair Ave W, Toronto, ON M4V 1K6", "7am–5pm", "(416) 555-0104"),

        ("Local Leaf Bookshop", "Retail", "Independent bookstore featuring local authors.", "310 Dundas St W, Toronto, ON M5T 1G5", "10am–7pm", "(416) 555-0201"),
        ("North Star Boutique", "Retail", "Curated clothing and accessories from small makers.", "500 Queen St W, Toronto, ON M5V 2B5", "11am–7pm", "(416) 555-0202"),
        ("Tiny Trinkets Studio", "Retail", "Handmade charms, pins, and custom gifts.", "1201 Yonge St, Toronto, ON M4T 1W1", "12pm–6pm", "(416) 555-0203"),
        ("Urban Pantry Market", "Retail", "Local snacks, jams, and pantry staples.", "60 Front St E, Toronto, ON M5E 1B7", "9am–6pm", "(416) 555-0204"),

        ("BrightPath Tutoring", "Services", "After-school tutoring in math, science, and writing.", "15 King St W, Toronto, ON M5H 1A1", "3pm–8pm", "(416) 555-0301"),
        ("GreenGlow Nail Bar", "Services", "Eco-friendly nail salon using non-toxic products.", "250 Bathurst St, Toronto, ON M5T 2S4", "10am–8pm", "(416) 555-0302"),
        ("Sunrise Fitness Studio", "Services", "Small group classes and beginner-friendly training.", "700 Bay St, Toronto, ON M5G 1Z6", "6am–9pm", "(416) 555-0303"),
        ("Neighbour Tech Repair", "Services", "Quick phone/laptop repairs and diagnostics.", "90 Eglinton Ave E, Toronto, ON M4P 2Y3", "10am–6pm", "(416) 555-0304"),
    ]

    cur.executemany("""
        INSERT INTO business (name, category, description, address, hours, phone)
        VALUES (?, ?, ?, ?, ?, ?)
    """, businesses)

    # Helper: get business id by name for linking deals
    def business_id(name: str) -> int:
        cur.execute("SELECT id FROM business WHERE name = ?", (name,))
        row = cur.fetchone()
        return row[0] if row else None

    now = datetime.now()
    # Demo deals linked to specific businesses
    deals = [
        (business_id("Maple Moon Café"), "Student Special", "10% off any drink with student ID.", "STUDENT10", (now + timedelta(days=30)).isoformat(timespec="seconds"), 1),
        (business_id("Local Leaf Bookshop"), "Weekend Deal", "Buy 2 used books, get 1 free.", "B2G1", (now + timedelta(days=14)).isoformat(timespec="seconds"), 1),
        (business_id("GreenGlow Nail Bar"), "First Visit Offer", "15% off your first service.", "WELCOME15", (now + timedelta(days=45)).isoformat(timespec="seconds"), 1),
        (business_id("Neighbour Tech Repair"), "Screen Repair Promo", "$15 off screen repairs this month.", "SCREEN15", (now + timedelta(days=20)).isoformat(timespec="seconds"), 1),
    ]

    cur.executemany("""
        INSERT INTO deal (business_id, title, description, coupon_code, expires_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?)
    """, deals)

    conn.commit()
    conn.close()


# Data helpers

# Fetch one business by id with avg_rating and review_count
def fetch_business_by_id(business_id: int):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT b.*,
               IFNULL(AVG(r.rating), 0) AS avg_rating,
               COUNT(r.id) AS review_count
        FROM business b
        LEFT JOIN review r ON r.business_id = b.id
        WHERE b.id = ?
        GROUP BY b.id
    """, (business_id,))

    row = cur.fetchone()
    conn.close()
    return row


# Fetch active deals for a business, ordered by expiry
def fetch_active_deals_for_business(business_id: int):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM deal
        WHERE business_id = ?
          AND is_active = 1
        ORDER BY expires_at ASC
    """, (business_id,))

    rows = cur.fetchall()
    conn.close()
    return rows


# Fetch all reviews for a business, newest first
def fetch_reviews_for_business(business_id: int):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM review
        WHERE business_id = ?
        ORDER BY created_at DESC
    """, (business_id,))

    rows = cur.fetchall()
    conn.close()
    return rows


# Fetch photo filenames for a business; return list of {url} for template
def fetch_photos_for_business(business_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT filename FROM business_photo WHERE business_id = ? ORDER BY id ASC",
        (business_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"url": url_for("static", filename=f"uploads/{r[0]}")} for r in rows]


# Fetch all photo URLs (for landing slideshow)
def fetch_all_photo_urls():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT filename FROM business_photo ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    return [url_for("static", filename=f"uploads/{r[0]}") for r in rows]


# True if this owner has bookmarked this business
def is_bookmarked(owner_id: str, business_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM bookmark
        WHERE username = ? AND business_id = ?
        LIMIT 1
    """, (owner_id, business_id))
    row = cur.fetchone()
    conn.close()
    return row is not None


# Add or remove bookmark; returns False if removed, True if added
def toggle_bookmark(owner_id: str, business_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM bookmark
        WHERE username = ? AND business_id = ?
        LIMIT 1
    """, (owner_id, business_id))
    row = cur.fetchone()

    if row:
        # Already bookmarked: remove it
        cur.execute("DELETE FROM bookmark WHERE id = ?", (row[0],))
        conn.commit()
        conn.close()
        return False
    else:
        # Not bookmarked: add it
        created_at = datetime.now().isoformat(timespec="seconds")
        cur.execute("""
            INSERT INTO bookmark (username, business_id, created_at)
            VALUES (?, ?, ?)
        """, (owner_id, business_id, created_at))
        conn.commit()
        conn.close()
        return True


# Fetch all bookmarked businesses for owner with avg_rating and review_count
def fetch_bookmarks_for_owner(owner_id: str):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            b.*,
            IFNULL(AVG(r.rating), 0) AS avg_rating,
            COUNT(r.id) AS review_count
        FROM bookmark bm
        JOIN business b ON b.id = bm.business_id
        LEFT JOIN review r ON r.business_id = b.id
        WHERE bm.username = ?
        GROUP BY b.id
        ORDER BY bm.created_at DESC
    """, (owner_id,))

    rows = cur.fetchall()
    conn.close()
    return rows


# Hash verification answer with salt for secure comparison
def _hash_answer(salt: str, answer: str) -> str:
    return hashlib.sha256((salt + ":" + answer.strip()).encode("utf-8")).hexdigest()


# Client IP for logging (X-Forwarded-For when behind proxy)
def _get_client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"


db_init()
seed_data()


# Routes

# Landing page: pass all photos and three shuffled lists for slideshow rows
@app.route("/")
def home():
    photos = fetch_all_photo_urls()
    # Shuffle order per row so each row scrolls differently
    photos_row1 = random.sample(photos, len(photos)) if photos else []
    photos_row2 = random.sample(photos, len(photos)) if photos else []
    photos_row3 = random.sample(photos, len(photos)) if photos else []
    return render_template(
        "landing.html",
        photos=photos,
        photos_row1=photos_row1,
        photos_row2=photos_row2,
        photos_row3=photos_row3,
    )


# Discover: list businesses with filter, sort, pagination
@app.route("/discover")
def discover():
    category = request.args.get("category", "All")
    sort = request.args.get("sort", "random")
    q = (request.args.get("q") or "").strip()

    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1
    if page < 1:
        page = 1

    owner_id = get_bookmark_owner_id()
    conn = get_conn()
    cur = conn.cursor()

    # Build WHERE from category and search
    conditions = []
    params = []
    if category != "All":
        conditions.append("b.category = ?")
        params.append(category)
    if q:
        conditions.append("(b.name LIKE ? OR b.description LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Total count and pagination bounds
    cur.execute(f"SELECT COUNT(*) FROM business b {where_sql}", params)
    total = cur.fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * PER_PAGE

    # Order by name, rating, review count, or id (random uses shuffle later)
    if sort == "name":
        order_sql = "ORDER BY b.name ASC"
    elif sort == "rating":
        order_sql = "ORDER BY avg_rating DESC, b.name ASC"
    elif sort == "reviews":
        order_sql = "ORDER BY review_count DESC, b.name ASC"
    else:
        order_sql = "ORDER BY b.id ASC"

    use_random_shuffle = sort == "random"
    # Random: fetch all matching rows then shuffle in Python; others: LIMIT/OFFSET
    if use_random_shuffle:
        query = f"""
            SELECT
                b.id, b.name, b.category, b.description, b.address, b.hours, b.phone,
                COALESCE(AVG(r.rating), 0) as avg_rating,
                COUNT(r.id) as review_count
            FROM business b
            LEFT JOIN review r ON b.id = r.business_id
            {where_sql}
            GROUP BY b.id, b.name, b.category, b.description, b.address, b.hours, b.phone
            {order_sql}
        """
        cur.execute(query, params)
    else:
        query = f"""
            SELECT
                b.id, b.name, b.category, b.description, b.address, b.hours, b.phone,
                COALESCE(AVG(r.rating), 0) as avg_rating,
                COUNT(r.id) as review_count
            FROM business b
            LEFT JOIN review r ON b.id = r.business_id
            {where_sql}
            GROUP BY b.id, b.name, b.category, b.description, b.address, b.hours, b.phone
            {order_sql}
            LIMIT ? OFFSET ?
        """
        cur.execute(query, params + [PER_PAGE, offset])
    rows = cur.fetchall()
    conn.close()

    # Build list of dicts and add bookmarked flag per business
    all_businesses = []
    for row in rows:
        all_businesses.append({
            "id": row[0],
            "name": row[1],
            "category": row[2],
            "description": row[3],
            "address": row[4],
            "hours": row[5],
            "phone": row[6],
            "avg_rating": row[7],
            "review_count": row[8],
            "bookmarked": is_bookmarked(owner_id, row[0])
        })

    # For random sort: use session cache so page 2+ keeps same order
    if use_random_shuffle:
        shuffle_key = (category, q)
        cached = (
            page > 1
            and session.get("shuffle_order_key") == shuffle_key
            and session.get("shuffle_order")
            and len(session["shuffle_order"]) == total
        )
        if cached:
            # Reorder current page's businesses to match cached shuffle
            id_to_biz = {b["id"]: b for b in all_businesses}
            all_businesses = [id_to_biz[bid] for bid in session["shuffle_order"] if bid in id_to_biz]
        else:
            random.shuffle(all_businesses)
            session["shuffle_order"] = [b["id"] for b in all_businesses]
            session["shuffle_order_key"] = shuffle_key
            session.modified = True
        businesses = all_businesses[offset : offset + PER_PAGE]
    else:
        businesses = all_businesses

    return render_template(
        "index.html",
        businesses=businesses,
        category=category,
        sort=sort,
        q=q,
        page=page,
        total_pages=total_pages
    )


# Business detail page: one business with deals, reviews, photos, bookmark state
@app.route("/business/<int:business_id>")
def business_detail(business_id):
    business = fetch_business_by_id(business_id)
    if business is None:
        return "Business not found", 404

    deals = fetch_active_deals_for_business(business_id)
    reviews = fetch_reviews_for_business(business_id)

    owner_id = get_bookmark_owner_id()
    bookmarked = is_bookmarked(owner_id, business_id)

    photos = fetch_photos_for_business(business_id)
    return render_template(
        "business.html",
        business=business,
        deals=deals,
        reviews=reviews,
        bookmarked=bookmarked,
        photos=photos,
    )


# True if filename has an allowed image extension
def _allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


MAX_UPLOAD_PHOTOS_PER_REQUEST = 5


# Upload photos for a business; save to static/uploads and insert into business_photo
@app.route("/business/<int:business_id>/upload_photo", methods=["POST"])
def upload_business_photo(business_id):
    business = fetch_business_by_id(business_id)
    if business is None:
        return "Business not found", 404
    files = request.files.getlist("image") or request.files.getlist("photo")
    files = [f for f in files if f and f.filename and f.filename.strip()]
    if not files:
        return redirect(url_for("business_detail", business_id=business_id))
    files = files[:MAX_UPLOAD_PHOTOS_PER_REQUEST]
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    for file in files:
        if not _allowed_image(file.filename):
            continue
        ext = file.filename.rsplit(".", 1)[1].lower()
        safe_name = f"{business_id}_{uuid.uuid4().hex[:12]}.{ext}"
        path = os.path.join(UPLOAD_FOLDER, safe_name)
        file.save(path)
        cur.execute(
            "INSERT INTO business_photo (business_id, filename, created_at) VALUES (?, ?, ?)",
            (business_id, safe_name, now),
        )
    conn.commit()
    conn.close()
    return redirect(url_for("business_detail", business_id=business_id))


# Toggle bookmark (POST); redirect back to referrer or home
@app.route("/bookmark/toggle", methods=["POST"])
def bookmark_toggle():
    business_id = request.form.get("business_id", "").strip()
    if not business_id.isdigit():
        return "Invalid business id.", 400
    business_id = int(business_id)

    owner_id = get_bookmark_owner_id()
    toggle_bookmark(owner_id, business_id)

    return redirect(request.referrer or url_for("home"))


# Bookmarks list: paginated businesses for current session owner
@app.route("/bookmarks")
def bookmarks_page():
    owner_id = get_bookmark_owner_id()

    try:
        page = int(request.args.get("page", "1"))
    except:
        page = 1
    if page < 1:
        page = 1
    offset = (page - 1) * PER_PAGE

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM bookmark WHERE username = ?", (owner_id,))
    total = cur.fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    if page > total_pages:
        page = total_pages
        offset = (page - 1) * PER_PAGE

    # Join bookmark -> business, attach avg_rating and review_count
    cur.execute("""
        SELECT
            b.*,
            IFNULL(AVG(r.rating), 0) AS avg_rating,
            COUNT(r.id) AS review_count
        FROM bookmark bm
        JOIN business b ON b.id = bm.business_id
        LEFT JOIN review r ON r.business_id = b.id
        WHERE bm.username = ?
        GROUP BY b.id
        ORDER BY bm.created_at DESC
        LIMIT ? OFFSET ?
    """, (owner_id, PER_PAGE, offset))

    businesses = cur.fetchall()
    conn.close()

    return render_template(
        "bookmarks.html",
        businesses=businesses,
        page=page,
        total_pages=total_pages
    )


# Review: validate input, rate-limit, generate math question, store attempt and draft in session
@app.route("/review/start_verification", methods=["POST"])
def start_verification():
    data = request.get_json(silent=True) or {}
    business_id = str(data.get("business_id", "")).strip()
    username = str(data.get("username", "")).strip()
    rating = str(data.get("rating", "")).strip()
    comment = str(data.get("comment", "")).strip()

    # Validate business_id, username, comment length, rating 1-5
    if not business_id.isdigit():
        return jsonify({"ok": False, "error": "Invalid business id."}), 400

    if username == "":
        return jsonify({"ok": False, "error": "Display name cannot be empty."}), 400
    if len(username) > MAX_USERNAME_LEN:
        return jsonify({"ok": False, "error": f"Display name too long (max {MAX_USERNAME_LEN} chars)."}), 400

    if comment == "":
        return jsonify({"ok": False, "error": "Comment cannot be empty."}), 400
    if len(comment) > MAX_COMMENT_LEN:
        return jsonify({"ok": False, "error": f"Comment too long (max {MAX_COMMENT_LEN} chars)."}), 400

    try:
        rating_int = int(rating)
        if rating_int < 1 or rating_int > 5:
            return jsonify({"ok": False, "error": "Rating must be 1–5."}), 400
    except:
        return jsonify({"ok": False, "error": "Invalid rating."}), 400

    business_id_int = int(business_id)

    # Rate limit: block if user submitted a review recently
    now_ts = int(datetime.now().timestamp())
    last_ts = int(session.get("last_review_ts", 0))

    if last_ts and (now_ts - last_ts) < RATE_LIMIT_SECONDS:
        wait = RATE_LIMIT_SECONDS - (now_ts - last_ts)
        return jsonify({
            "ok": False,
            "error": f"Rate limit: please wait {wait}s before posting another review.",
            "tries_left": None
        }), 429

    session["last_review_ts"] = now_ts
    session.modified = True

    # Generate simple math question and hash the answer
    a = random.randint(2, 12)
    b = random.randint(2, 12)
    question = f"What is {a} + {b}?"
    answer = str(a + b)

    salt = uuid.uuid4().hex
    answer_hash = f"{salt}${_hash_answer(salt, answer)}"

    ip = _get_client_ip()
    created_at = datetime.now().isoformat(timespec="seconds")

    # Save verification attempt (passed=0 until user answers correctly)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO verification_attempt (username, business_id, question, answer_hash, passed, created_at, ip)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (username, business_id_int, question, answer_hash, 0, created_at, ip))
    attempt_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Store review draft in session keyed by attempt_id
    session.setdefault("pending_reviews", {})
    session["pending_reviews"][str(attempt_id)] = {
        "business_id": business_id_int,
        "username": username,
        "rating": rating_int,
        "comment": comment
    }
    session.setdefault("verification_tries", {})
    session["verification_tries"][str(attempt_id)] = 0
    session.modified = True

    return jsonify({"ok": True, "attempt_id": attempt_id, "question": question})


# Review: verify answer; if correct, insert review and redirect to business page
@app.route("/review/submit", methods=["POST"])
def submit_review():
    data = request.get_json(silent=True) or {}
    attempt_id = str(data.get("attempt_id", "")).strip()
    answer = str(data.get("answer", "")).strip()

    if not attempt_id.isdigit():
        return jsonify({"ok": False, "error": "Invalid attempt id."}), 400

    # Load verification attempt from DB
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM verification_attempt WHERE id = ?", (int(attempt_id),))
    attempt = cur.fetchone()
    conn.close()

    if attempt is None:
        return jsonify({"ok": False, "error": "Verification attempt not found."}), 400

    stored = attempt["answer_hash"] or ""
    if "$" not in stored:
        return jsonify({"ok": False, "error": "Verification data corrupted."}), 400

    salt, stored_hash = stored.split("$", 1)
    provided_hash = _hash_answer(salt, answer)

    # Increment try count (max 5)
    session.setdefault("verification_tries", {})
    tries = int(session["verification_tries"].get(attempt_id, 0)) + 1
    session["verification_tries"][attempt_id] = tries
    session.modified = True

    max_tries = 5
    tries_left = max_tries - tries

    if provided_hash != stored_hash:
        # Wrong answer: clear draft if max tries reached
        if tries >= max_tries:
            session.setdefault("pending_reviews", {})
            session["pending_reviews"].pop(attempt_id, None)
            session["verification_tries"].pop(attempt_id, None)
            session.modified = True
            return jsonify({"ok": False, "error": "Too many failed attempts. Please try again.", "tries_left": 0})
        return jsonify({"ok": False, "error": "Incorrect answer. Try again.", "tries_left": tries_left})

    # Correct: mark attempt passed in DB
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE verification_attempt SET passed = 1 WHERE id = ?", (int(attempt_id),))
    conn.commit()
    conn.close()

    # Get review draft from session and insert into review table
    draft = session.get("pending_reviews", {}).get(attempt_id)
    if not draft:
        return jsonify({"ok": False, "error": "No pending review found. Please re-submit your review."}), 400

    created_at = datetime.now().isoformat(timespec="seconds")
    is_flagged = 0

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO review (business_id, username, rating, comment, created_at, is_flagged)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (draft["business_id"], draft["username"], draft["rating"], draft["comment"], created_at, is_flagged))
    conn.commit()
    conn.close()

    # Clear draft and try count from session
    session["pending_reviews"].pop(attempt_id, None)
    session["verification_tries"].pop(attempt_id, None)
    session.modified = True

    return jsonify({"ok": True, "redirect": url_for("business_detail", business_id=draft["business_id"])})


# Add business from modal form; require name, category, address
@app.route("/admin/add_business", methods=["POST"])
def admin_add_business():
    name = request.form.get("name", "").strip().title()
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()
    address = request.form.get("address", "").strip().title()
    hours = request.form.get("hours", "").strip()
    phone = request.form.get("phone", "").strip()

    if name == "" or category == "" or address == "":
        return "Name, category, and address are required", 400

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO business (name, category, description, address, hours, phone)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, category, description, address, hours, phone))
        conn.commit()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            return "Database is busy; please try again in a moment.", 503
        raise
    finally:
        conn.close()

    return redirect(url_for("home"))







if __name__ == "__main__":
    app.run(debug=True)