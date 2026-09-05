import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "instance", "scraptrade.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema():
    """Ensure all required columns and tables exist (safe lightweight migration)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    
    # Create password_resets if missing
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Create deposit_transactions if missing
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deposit_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER NOT NULL REFERENCES users(id),
            deposit_id INTEGER REFERENCES deposits(id),
            transaction_type TEXT NOT NULL CHECK(transaction_type IN ('initial_deposit','deduction','refund','topup')),
            amount REAL NOT NULL,
            reason TEXT NOT NULL,
            order_id INTEGER REFERENCES orders(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Create market_price_trends if missing
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_price_trends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_name TEXT NOT NULL,
            category TEXT NOT NULL,
            grade TEXT,
            current_price REAL NOT NULL,
            previous_price REAL NOT NULL,
            weekly_change_pct REAL NOT NULL,
            volume_traded_tonnes REAL NOT NULL,
            unit TEXT NOT NULL DEFAULT 'kg',
            market_sentiment TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    
    # Check users columns
    user_cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "google_id" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN google_id TEXT")
    if "avatar_url" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT")
        
    # Check listings columns
    listing_cols = [row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()]
    if "image_url" not in listing_cols:
        conn.execute("ALTER TABLE listings ADD COLUMN image_url TEXT")
        
    # Check buyer_requests columns
    req_cols = [row[1] for row in conn.execute("PRAGMA table_info(buyer_requests)").fetchall()]
    if "image_url" not in req_cols:
        conn.execute("ALTER TABLE buyer_requests ADD COLUMN image_url TEXT")

    # Check bids columns
    bid_cols = [row[1] for row in conn.execute("PRAGMA table_info(bids)").fetchall()]
    if "counter_price" not in bid_cols:
        conn.execute("ALTER TABLE bids ADD COLUMN counter_price REAL")
    if "counter_message" not in bid_cols:
        conn.execute("ALTER TABLE bids ADD COLUMN counter_message TEXT")
    if "last_acted_by" not in bid_cols:
        conn.execute("ALTER TABLE bids ADD COLUMN last_acted_by TEXT DEFAULT 'buyer'")
    if "updated_at" not in bid_cols:
        conn.execute("ALTER TABLE bids ADD COLUMN updated_at TEXT")
        conn.execute("UPDATE bids SET updated_at = created_at WHERE updated_at IS NULL")

    # Check inspections columns
    insp_cols = [row[1] for row in conn.execute("PRAGMA table_info(inspections)").fetchall()]
    if "evidence_image_url" not in insp_cols:
        conn.execute("ALTER TABLE inspections ADD COLUMN evidence_image_url TEXT")

    # Check pickups columns
    pickup_cols = [row[1] for row in conn.execute("PRAGMA table_info(pickups)").fetchall()]
    if "weighbridge_slip_url" not in pickup_cols:
        conn.execute("ALTER TABLE pickups ADD COLUMN weighbridge_slip_url TEXT")
    if "vehicle_number" not in pickup_cols:
        conn.execute("ALTER TABLE pickups ADD COLUMN vehicle_number TEXT")
    if "driver_name" not in pickup_cols:
        conn.execute("ALTER TABLE pickups ADD COLUMN driver_name TEXT")
    if "driver_phone" not in pickup_cols:
        conn.execute("ALTER TABLE pickups ADD COLUMN driver_phone TEXT")
    if "tracking_stage" not in pickup_cols:
        conn.execute("ALTER TABLE pickups ADD COLUMN tracking_stage TEXT DEFAULT 'Pickup Scheduled'")
    if "current_location" not in pickup_cols:
        conn.execute("ALTER TABLE pickups ADD COLUMN current_location TEXT DEFAULT 'Origin Weighbridge'")
    if "eta_minutes" not in pickup_cols:
        conn.execute("ALTER TABLE pickups ADD COLUMN eta_minutes INTEGER DEFAULT 180")

    # Seed market price trends if empty
    trend_count = conn.execute("SELECT COUNT(*) c FROM market_price_trends").fetchone()["c"]
    if trend_count == 0:
        trends = [
            ("Copper Wire Scrap", "Metal", "Grade 1 (Bright)", 720.0, 705.0, 2.13, 142.5, "kg", "Bullish"),
            ("Aluminium Sheet Scrap", "Metal", "Grade A", 185.0, 190.0, -2.63, 380.0, "kg", "Stable"),
            ("Brass Honey Scrap", "Metal", "Honey Grade", 450.0, 442.0, 1.81, 95.0, "kg", "Bullish"),
            ("Heavy Melting Steel (HMS 1&2)", "Metal", "6mm+ Offcuts", 28.5, 27.8, 2.52, 1250.0, "kg", "High Demand"),
            ("HDPE Mixed Plastic Scrap", "Plastic", "Post-industrial Bales", 32.0, 31.0, 3.23, 210.0, "kg", "Strong Demand"),
            ("PET Bottle Scrap", "Plastic", "Flaked & Washed", 42.0, 43.5, -3.45, 185.0, "kg", "Bearish"),
            ("Corrugated Paper (OCC)", "Paper", "Baled Brown Craft", 14.5, 14.0, 3.57, 620.0, "kg", "Stable"),
            ("Assorted PCB Circuit Boards", "E-Waste", "Mixed Motherboards", 410.0, 395.0, 3.80, 45.0, "kg", "Bullish"),
        ]
        conn.executemany("""
            INSERT INTO market_price_trends (material_name, category, grade, current_price, previous_price, weekly_change_pct, volume_traded_tonnes, unit, market_sentiment)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, trends)

    conn.commit()
    conn.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def seed_db():
    """Insert realistic demo data so the app is immediately explorable."""
    from werkzeug.security import generate_password_hash

    conn = get_db()
    cur = conn.cursor()

    def add_user(name, email, phone, password, role, business=None, location=None,
                 gst=None, kyc="verified", seller_type=None, score=80):
        cur.execute(
            """INSERT INTO users (full_name, email, phone, password_hash, role,
               business_name, location, gst_number, kyc_status, seller_type, reliability_score)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (name, email, phone, generate_password_hash(password), role,
             business, location, gst, kyc, seller_type, score),
        )
        return cur.lastrowid

    admin_id = add_user("Platform Admin", "admin@scraptrade.hub", "9000000000",
                         "admin123", "admin")

    s1 = add_user("Ramesh Traders", "ramesh@scrap.in", "9876500001", "password123",
                   "seller", "Ramesh Metal Traders", "Pune, MH", "27ABCDE1234F1Z5",
                   "verified", "verified_deposit", 94)
    s2 = add_user("Anita Recyclers", "anita@scrap.in", "9876500002", "password123",
                   "seller", "Anita Recycling Co.", "Pimpri-Chinchwad, MH", "27PQRSX5678L1Z2",
                   "verified", "normal", 76)

    b1 = add_user("Suresh Metals Pvt Ltd", "suresh@buyer.in", "9876500003", "password123",
                   "buyer", "Suresh Metals Pvt Ltd", "Pune, MH", "27BUYER9999B1Z1", "verified", None, 91)
    b2 = add_user("GreenCycle Industries", "greencycle@buyer.in", "9876500004", "password123",
                   "buyer", "GreenCycle Industries", "Mumbai, MH", "27GREEN1111C1Z3", "verified", None, 85)

    cur.execute("INSERT INTO deposits (seller_id, deposit_amount, current_balance, status) VALUES (?,?,?,?)",
                (s1, 25000, 25000, "active"))

    listings = [
        (s1, "Aluminium Scrap", "Metal", "Grade A", 500, "kg", 185, "Pune, MH",
         "Clean aluminium sheet offcuts from fabrication unit, sorted, no contamination."),
        (s1, "Copper Wire Scrap", "Metal", "Grade 1 (Bright)", 120, "kg", 720, "Pune, MH",
         "Bright bare copper wire, stripped, ready for pickup."),
        (s2, "Mixed Plastic (HDPE)", "Plastic", "Post-industrial", 800, "kg", 32, "Pimpri-Chinchwad, MH",
         "HDPE crates and containers, baled, minimal contamination."),
        (s2, "E-Waste — PCB Boards", "E-Waste", "Mixed grade", 60, "kg", 410, "Pimpri-Chinchwad, MH",
         "Assorted circuit boards from decommissioned office equipment."),
        (s1, "MS Steel Scrap", "Metal", "Heavy melting", 2000, "kg", 28, "Pune, MH",
         "Structural steel offcuts from construction site, 6mm+ thickness."),
    ]
    listing_ids = []
    for l in listings:
        cur.execute(
            """INSERT INTO listings (seller_id, material_type, category, grade, estimated_quantity,
               unit, expected_price, location, description, status)
               VALUES (?,?,?,?,?,?,?,?,?,'active')""", l)
        listing_ids.append(cur.lastrowid)

    # A couple of bids on the first listing
    cur.execute("""INSERT INTO bids (listing_id, buyer_id, bid_price, quantity, message, status)
                   VALUES (?,?,?,?,?, 'active')""",
                (listing_ids[0], b1, 190, 500, "Can pick up within 24 hours."))
    cur.execute("""INSERT INTO bids (listing_id, buyer_id, bid_price, quantity, message, status)
                   VALUES (?,?,?,?,?, 'active')""",
                (listing_ids[0], b2, 182, 500, "Weekly recurring buyer, flexible timing."))

    # One completed order to demonstrate full lifecycle in Order Detail view
    cur.execute("""INSERT INTO orders (order_type, listing_id, buyer_id, seller_id,
                   material_type, category, unit, estimated_quantity,
                   final_quantity, agreed_price, total_amount, status)
                   VALUES ('forward', ?,?,?,?,?,?,?,?,?,?, 'completed')""",
                (listing_ids[2], b2, s2, "Mixed Plastic (HDPE)", "Plastic", "kg",
                 800, 790, 32, 790 * 32))
    order_id = cur.lastrowid
    cur.execute("""INSERT INTO inspections (order_id, inspector_notes, quality_verified,
                   estimated_quantity, result) VALUES (?,?,?,?, 'passed')""",
                (order_id, "Material matches listing description.", "HDPE confirmed", 800))
    cur.execute("""INSERT INTO payments (order_id, total_amount, status, amount_held, amount_released)
                   VALUES (?,?, 'released', ?, ?)""",
                (order_id, 790 * 32, 790 * 32, 790 * 32))
    cur.execute("""INSERT INTO pickups (order_id, final_weight, pickup_status) VALUES (?,?, 'in_transit')""",
                (order_id, 790))
    cur.execute("""INSERT INTO deliveries (order_id, delivery_status, buyer_confirmation)
                   VALUES (?, 'confirmed', 1)""", (order_id,))
    cur.execute("UPDATE listings SET status='sold' WHERE id=?", (listing_ids[2],))

    # --- Reverse bidding demo data: buyer requests + seller bids ---
    from datetime import date, timedelta
    future = (date.today() + timedelta(days=14)).isoformat()
    near_expiry = (date.today() + timedelta(days=2)).isoformat()
    past = (date.today() - timedelta(days=3)).isoformat()

    cur.execute(
        """INSERT INTO buyer_requests (buyer_id, material_type, category, grade, required_quantity,
           unit, location, max_price, delivery_preference, description, expiry_date, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?, 'open')""",
        (b1, "Copper Scrap", "Metal", "Grade 1 (Bright)", 300, "kg", "Pune, MH", 700,
         "pickup", "Looking for a recurring weekly supplier of bright copper scrap.", future),
    )
    req1 = cur.lastrowid

    cur.execute(
        """INSERT INTO buyer_requests (buyer_id, material_type, category, grade, required_quantity,
           unit, location, max_price, delivery_preference, description, expiry_date, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?, 'open')""",
        (b2, "HDPE Plastic", "Plastic", "Post-industrial", 1500, "kg", "Mumbai, MH", 30,
         "delivery", "Need a large one-off batch for a packaging production run.", near_expiry),
    )
    req2 = cur.lastrowid

    # An expired request, to demonstrate expiry gating
    cur.execute(
        """INSERT INTO buyer_requests (buyer_id, material_type, category, grade, required_quantity,
           unit, location, max_price, delivery_preference, description, expiry_date, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?, 'open')""",
        (b1, "Mixed Paper Waste", "Paper", "Sorted", 1000, "kg", "Pune, MH", 12,
         "pickup", "This request has already expired — used to demonstrate expiry handling.", past),
    )

    # Bids from sellers on req1
    cur.execute(
        """INSERT INTO reverse_bids (request_id, seller_id, offered_price, available_quantity,
           grade, delivery_option, message, expiry_date, status)
           VALUES (?,?,?,?,?,?,?,?, 'active')""",
        (req1, s1, 690, 300, "Grade 1 (Bright)", "pickup",
         "Can supply weekly. Payment terms flexible.", future),
    )
    cur.execute(
        """INSERT INTO reverse_bids (request_id, seller_id, offered_price, available_quantity,
           grade, delivery_option, message, expiry_date, status)
           VALUES (?,?,?,?,?,?,?,?, 'active')""",
        (req1, s2, 705, 280, "Grade 1", "pickup",
         "Slightly below requested quantity but consistent supply.", future),
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    seed_db()
    print("Database initialised and seeded at", DB_PATH)
