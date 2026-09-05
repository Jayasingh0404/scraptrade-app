-- ScrapTrade Hub — MVP Database Schema (SQLite)

DROP TABLE IF EXISTS password_resets;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS reliability_history;
DROP TABLE IF EXISTS disputes;
DROP TABLE IF EXISTS deliveries;
DROP TABLE IF EXISTS pickups;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS inspections;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS reverse_bids;
DROP TABLE IF EXISTS buyer_requests;
DROP TABLE IF EXISTS bids;
DROP TABLE IF EXISTS listing_images;
DROP TABLE IF EXISTS listings;
DROP TABLE IF EXISTS deposits;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    password_hash TEXT,
    role TEXT NOT NULL CHECK(role IN ('seller','buyer','admin')),
    business_name TEXT,
    business_address TEXT,
    location TEXT,
    gst_number TEXT,
    kyc_status TEXT NOT NULL DEFAULT 'pending' CHECK(kyc_status IN ('pending','verified','rejected')),
    seller_type TEXT CHECK(seller_type IN ('normal','verified_deposit')),
    reliability_score INTEGER NOT NULL DEFAULT 80,
    successful_deals INTEGER NOT NULL DEFAULT 0,
    disputes_count INTEGER NOT NULL DEFAULT 0,
    google_id TEXT UNIQUE,
    avatar_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    token TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER NOT NULL REFERENCES users(id),
    deposit_amount REAL NOT NULL DEFAULT 0,
    current_balance REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER NOT NULL REFERENCES users(id),
    material_type TEXT NOT NULL,
    category TEXT NOT NULL,
    grade TEXT,
    estimated_quantity REAL NOT NULL,
    unit TEXT NOT NULL DEFAULT 'kg',
    expected_price REAL NOT NULL,
    location TEXT NOT NULL,
    description TEXT,
    image_url TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','reserved','sold','cancelled','suspended')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE listing_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    image_url TEXT NOT NULL
);

CREATE TABLE bids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    buyer_id INTEGER NOT NULL REFERENCES users(id),
    bid_price REAL NOT NULL,
    quantity REAL NOT NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','withdrawn','accepted','rejected')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Buyer -> Seller Reverse Bidding: a buyer posts what they need, sellers bid to fulfil it.
CREATE TABLE buyer_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER NOT NULL REFERENCES users(id),
    material_type TEXT NOT NULL,
    category TEXT NOT NULL,
    grade TEXT,
    required_quantity REAL NOT NULL,
    unit TEXT NOT NULL DEFAULT 'kg',
    location TEXT NOT NULL,
    max_price REAL NOT NULL,
    delivery_preference TEXT NOT NULL DEFAULT 'pickup' CHECK(delivery_preference IN ('pickup','delivery')),
    description TEXT,
    image_url TEXT,
    expiry_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','fulfilled','cancelled','expired')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE reverse_bids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES buyer_requests(id),
    seller_id INTEGER NOT NULL REFERENCES users(id),
    offered_price REAL NOT NULL,
    available_quantity REAL NOT NULL,
    grade TEXT,
    delivery_option TEXT NOT NULL DEFAULT 'pickup' CHECK(delivery_option IN ('pickup','delivery')),
    message TEXT,
    expiry_date TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','withdrawn','accepted','rejected','expired')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_type TEXT NOT NULL DEFAULT 'forward' CHECK(order_type IN ('forward','reverse')),
    -- Forward marketplace linkage (seller lists, buyer bids)
    listing_id INTEGER REFERENCES listings(id),
    bid_id INTEGER REFERENCES bids(id),
    -- Reverse bidding linkage (buyer requests, seller bids)
    request_id INTEGER REFERENCES buyer_requests(id),
    reverse_bid_id INTEGER REFERENCES reverse_bids(id),
    buyer_id INTEGER NOT NULL REFERENCES users(id),
    seller_id INTEGER NOT NULL REFERENCES users(id),
    material_type TEXT NOT NULL,
    category TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'kg',
    estimated_quantity REAL NOT NULL,
    final_quantity REAL,
    agreed_price REAL NOT NULL,
    total_amount REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_inspection' CHECK(status IN (
        'pending_inspection','inspection_passed','inspection_failed',
        'payment_pending','payment_held','logistics_assigned',
        'pickup_in_progress','in_transit','delivered','completed',
        'cancelled','disputed'
    )),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (
        (order_type = 'forward' AND listing_id IS NOT NULL)
        OR (order_type = 'reverse' AND request_id IS NOT NULL)
    )
);

CREATE TABLE inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    inspector_notes TEXT,
    quality_verified TEXT,
    estimated_quantity REAL,
    result TEXT NOT NULL DEFAULT 'requested' CHECK(result IN ('requested','passed','failed','conditional')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    total_amount REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','held','released','refunded')),
    amount_held REAL NOT NULL DEFAULT 0,
    amount_released REAL NOT NULL DEFAULT 0,
    amount_refunded REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE pickups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    final_weight REAL,
    pickup_status TEXT NOT NULL DEFAULT 'scheduled' CHECK(pickup_status IN ('scheduled','weighed','loaded','in_transit')),
    scheduled_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    delivery_status TEXT NOT NULL DEFAULT 'pending' CHECK(delivery_status IN ('pending','delivered','confirmed','issue_raised')),
    buyer_confirmation INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE disputes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    raised_by INTEGER NOT NULL REFERENCES users(id),
    issue_type TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','rejected')),
    resolution TEXT,
    responsible_party TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);

CREATE TABLE reliability_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    previous_score INTEGER NOT NULL,
    new_score INTEGER NOT NULL,
    reason TEXT NOT NULL,
    related_order_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    order_id INTEGER,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    read_status INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_buyer_requests_status ON buyer_requests(status);
CREATE INDEX idx_reverse_bids_request ON reverse_bids(request_id);
CREATE INDEX idx_reverse_bids_seller ON reverse_bids(seller_id);
CREATE INDEX idx_orders_request ON orders(request_id);
