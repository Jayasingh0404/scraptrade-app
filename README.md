# ScrapTrade Hub — Production-Ready B2B & Circular Economy Scrap Marketplace

A full-featured, end-to-end B2B and consumer scrap trading marketplace: sellers list scrap lots with material photos, buyers place bids, or buyers post procurement requests for verified sellers to fulfill (reverse bidding). The platform orchestrates the complete lifecycle: KYC verification, inspection, held escrow-style payments, logistics dispatch with weighbridge tolerance checks, delivery confirmation, dispute arbitration, and dynamic reliability scoring.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Jayasingh0404/Scraptrade)

---

## 🌟 Key Features

### 1. Dual Trading Mechanisms
- **Forward Marketplace (Seller $\to$ Buyer):** Sellers publish scrap lots (Grade, Category, Quantity, Unit, Price, Location, Photos). Buyers filter by category/location/price and submit bids.
- **Reverse Bidding (Buyer $\to$ Seller):** Recyclers and procurement managers post specific material requirements with target volumes and price caps. Verified sellers discover and bid to fulfill; buyers compare bids side-by-side in a comparative matrix and award the winning offer.

### 2. Authentication & Security
- **Email & Password Authentication:** Secure password hashing via Werkzeug (`scrypt`/`pbkdf2`).
- **Google Sign-In / OAuth 2.0:** Integrated Google authentication flow supporting both production GCP OAuth client credentials and instant 1-click Google accounts for development.
- **Forgot Password System:** Secure time-limited password reset tokens (1-hour expiration, single-use enforcement, email preview and simulated notification).
- **Role-Based Access Control (RBAC):** Dedicated permissions and guarded views for **Sellers**, **Buyers**, and **Admins**.

### 3. End-to-End Fulfillment Pipeline
```
Deal Accepted ➔ Admin Inspection ➔ Buyer Confirms & Pays (Held) ➔
Logistics Assigned ➔ Pickup & Weighbridge Verification ➔ In Transit ➔
Delivered ➔ Buyer Confirmation / Dispute ➔ Escrow Payment Released ➔
Reliability Score Dynamically Updated
```
- **Escrow-Style Held Payments:** Buyer funds are held in platform custody upon deal confirmation and only released when delivery and weight verification are confirmed.
- **Weighbridge Tolerance Checks:** Pickup weights are recorded; variances $>5\%$ trigger automatic mismatch notifications.
- **Dispute Resolution Desk:** Buyers can raise disputes; admins arbitrate with fault attribution, adjusting reliability scores accordingly.
- **Dynamic Reliability Scoring ($0-100$):** Every completed order and dispute decision dynamically updates public reputation scores.

### 4. Media & File Uploads
- Direct image and specification sheet uploads for scrap listings and buyer procurement requests with MIME and size validation.

---

## 🚀 Quick Start

### Option A: Local Python Environment
```bash
# 1. Clone repository & enter directory
git clone https://github.com/Jayasingh0404/ScrapTrade.git
cd ScrapTrade

# 2. (Optional) Create & activate virtual environment
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize and seed database
python3 database.py

# 5. Run the server
python3 app.py
```
Open **http://127.0.0.1:8000** in your browser.

---

### Option B: Docker & Docker Compose
```bash
# Build and start the containerized service
docker compose up --build
```
The app will be accessible at **http://localhost:8000**.

---

## 👥 Demo User Personas

All accounts come pre-configured with realistic transaction history and data:

| Role | Email | Password | Details |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin@scraptrade.hub` | `admin123` | Platform oversight, dispute arbitration, inspection approval |
| **Seller** | `ramesh@scrap.in` | `password123` | Verified Deposit Seller (Pune, MH), 94/100 Reliability |
| **Seller** | `anita@scrap.in` | `password123` | Normal Seller (Pimpri, MH), 76/100 Reliability |
| **Buyer** | `suresh@buyer.in` | `password123` | Suresh Metals Pvt Ltd, 91/100 Reliability |
| **Buyer** | `greencycle@buyer.in` | `password123` | GreenCycle Industries, 85/100 Reliability |

*Tip: You can also use **Sign in with Google** to instantly sign in with one click or link your Google profile.*

---

## 🧪 Automated Testing

Run the full automated test suite covering Authentication, Google Sign-In, Forgot Password, Listing Creation, Bidding, and Order Workflow:

```bash
python3 -m pytest tests/ -v
```

---

## ⚙️ Configuration & Environment Variables

Copy `.env.example` to `.env` to configure optional custom settings:
```bash
cp .env.example .env
```
- `SECRET_KEY`: Session encryption key.
- `GOOGLE_CLIENT_ID`: Google OAuth 2.0 Web Client ID.
- `GOOGLE_CLIENT_SECRET`: Google OAuth 2.0 Client Secret.
- `PORT`: Server port (default `8000`).

---

## 📦 Project Structure

```
scraptrade-app/
├── app.py                     # Main Flask application & routes (Auth, Bidding, Orders, Admin)
├── database.py                # Database connection, migrations & seeder
├── schema.sql                 # Complete relational schema (SQLite / PostgreSQL compatible)
├── requirements.txt           # Python package dependencies
├── Dockerfile                 # Multi-stage production container definition
├── docker-compose.yml         # Container orchestration configuration
├── .env.example               # Environment variables template
├── static/
│   └── uploads/               # Uploaded material photos and specification sheets
├── templates/
│   ├── base.html              # Core navigation layout & responsive header
│   ├── index.html             # Landing page with value proposition and stats
│   ├── login.html             # Login view with Google Sign-In & Forgot Password links
│   ├── signup.html            # Registration view with role selection
│   ├── forgot_password.html   # Password reset request view
│   ├── reset_password.html    # Password reset submission view
│   ├── google_signin_dev.html # Google Identity Services interface
│   ├── google_role_select.html# Google user role onboarding
│   ├── browse_listings.html   # Marketplace catalog with filtering
│   ├── listing_detail.html    # Listing view with photo & live bidding form
│   ├── new_listing.html       # Scrap listing creator with photo upload
│   ├── browse_requests.html   # Reverse bidding procurement board
│   ├── request_detail.html    # Procurement request details with bids
│   ├── compare_bids.html      # Side-by-side comparative bidding matrix
│   ├── new_request.html       # Procurement request form
│   ├── seller_dashboard.html  # Seller control center
│   ├── buyer_dashboard.html   # Buyer procurement & bids tracker
│   ├── admin_dashboard.html   # Platform GMV, inspection & dispute control
│   ├── order_detail.html      # 8-stage visual fulfillment progress tracker
│   └── notifications.html     # Notification feed
└── tests/
    ├── conftest.py            # Test isolation fixture & in-memory DB
    └── test_auth_and_features.py # Automated integration tests
```

---

## 🔗 Connecting to GitHub

To push this codebase to your GitHub repository:
```bash
git init
git add .
git commit -m "feat: complete ScrapTrade full-stack platform with Google login and forgot password"
git branch -M main
git remote add origin https://github.com/Jayasingh0404/ScrapTrade.git
git push -u origin main
```


To reset all demo data at any time: delete `instance/scraptrade.db` and
re-run `python3 database.py`.

## What's implemented (MVP scope)

**Auth & roles** — signup/login/logout, seller/buyer/admin roles, KYC status
field, seller type (Normal / Verified Deposit).

**Marketplace (forward flow)** — sellers create listings (material, grade,
quantity, price, location, description); buyers search/filter by material,
location, and price; buyers bid, sellers accept the best offer.

**Reverse bidding (buyer → seller)** — buyers post what they need; verified
sellers discover and bid to fulfil it; buyer compares and accepts. See the
dedicated section below.

**End-to-end order workflow** — shared by both the forward and reverse
flows, exactly the phase sequence from the project spec:

```
Order Created → Inspection (admin) → Buyer Confirms & Pays (held) →
Logistics Assigned → Pickup & Final Weight Check → In Transit →
Delivered → Buyer Confirms / Raises Issue → Payment Released →
Reliability Score Updated
```

- **Inspection:** admin records pass/fail with notes.
- **Payment hold:** buyer "pays"; funds are marked `held` by the platform,
  not released to the seller yet.
- **Logistics & pickup:** admin assigns logistics and records the actual
  pickup weight; a >5% variance from the estimated quantity flags a mismatch
  notification to the buyer (tolerance-check logic from the spec).
- **Delivery:** admin marks delivered; buyer then confirms (releases payment,
  bumps both parties' reliability scores, generates transaction history) or
  raises an issue.
- **Disputes:** buyer raises an issue with a type + description; admin
  reviews and resolves as refund or payment release, assigning fault to
  buyer/seller/logistics, which adjusts reliability scores accordingly.

**Reliability scoring** — every completed order and every resolved dispute
writes to `reliability_history`, and the running score shown on dashboards
updates live.

**Admin panel** — platform-wide stats (GMV, users, disputes), inspection
queue, logistics queue, dispute resolution, and user/KYC management. Works
identically for orders created from either the forward or reverse flow.

**Notifications** — in-app notifications fire on key events (bid received,
inspection result, payment held, pickup scheduled, delivered, payment
released, dispute resolved, bid accepted/rejected, request cancelled).

---

## Buyer → Seller Reverse Bidding

Buyers can post what they need instead of waiting for a matching listing;
verified sellers discover the request and bid to fulfil it.

### Flow

1. **Buyer posts a request** ("Post Buying Request") — material, category,
   grade, required quantity, location, max price, pickup/delivery
   preference, expiry date, description.
2. **Verified sellers browse requests** ("Buyer Requests") and open one to
   see full detail.
3. **Seller submits a bid** — offered price, available quantity, grade,
   delivery option, optional expiry, optional message. One active bid per
   seller per request; sellers can withdraw and rebid.
4. **Buyer reviews all bids** ("My Requests" → a request → "Compare Bids")
   — a side-by-side table showing each seller's price, quantity/grade,
   KYC status, reliability score, completed-deal count, and dispute count,
   with Accept / Reject on each active bid.
5. **On acceptance:** an `Order` is created (agreed price and quantity
   locked from the winning bid), all other active bids on that request are
   auto-rejected, the request is marked `fulfilled`, and both buyer and
   seller are notified. The order then flows through the **same**
   inspection → payment-hold → logistics → pickup → delivery →
   completion pipeline used by the forward marketplace — nothing about
   that pipeline was duplicated or forked.

### New pages

| Page | Route | Who |
|---|---|---|
| Post Buying Request | `/requests/new` | Buyer |
| My Requests | `/requests/mine` | Buyer |
| Buyer Requests (browse) | `/requests` | Seller |
| Request detail (view / bid) | `/requests/<id>` | Buyer (owner) & Seller |
| Compare Bids | `/requests/<id>/compare` | Buyer (owner only) |
| My Bids | `/bids/mine` | Seller |

Both roles see quick-access cards on their dashboards ("Open Buying
Requests" for buyers, "Active Bids on Requests" for sellers), and every
order table now shows whether an order came from "My Listing" / "Marketplace
Bid" (forward) or "Buyer Request" / "My Request" (reverse).

### Rules enforced

- **Buyers cannot bid on their own requests** — blocked both by role
  (`role_required("seller")`-equivalent check on submission) and by an
  explicit `request["buyer_id"] == g.user["id"]` guard.
- **No duplicate active bids** — a seller with an existing `active` bid on a
  request must withdraw it before submitting another.
- **Only verified sellers can bid** — gated on `kyc_status == 'verified'`;
  unverified sellers can browse and view requests but the bid form is
  replaced with a notice.
- **Expired requests reject new bids** — `expiry_date` is checked against
  today on every relevant page load; anything past its expiry is lazily
  flipped to `status='expired'` (a request must also be `status='open'` to
  accept bids).
- **Accepted bids can't be modified** — accepting a bid immediately marks it
  `accepted`, rejects every other active bid on that request, and marks the
  request `fulfilled`; the accept/reject/withdraw routes all re-check
  `status == 'active'` before acting, so a second accept attempt is refused.
- **Scoped access** — a buyer can only view/manage their own requests
  (viewing another buyer's request returns 403); only the owning buyer can
  open `Compare Bids` or accept/reject bids on a request; order detail pages
  (shared with the forward flow) already restrict access to the order's
  buyer, seller, or an admin.

### Data model additions

- `buyer_requests` — one row per posted purchase request.
- `reverse_bids` — one row per seller bid against a request.
- `orders` — extended (not replaced) to support both flows: added
  `order_type` (`forward`/`reverse`), `request_id`, `reverse_bid_id`, and
  denormalized `material_type` / `category` / `unit` columns so order
  history no longer depends on a listing existing at all. A `CHECK`
  constraint enforces that a `forward` order always has a `listing_id` and a
  `reverse` order always has a `request_id`. Every downstream table
  (`inspections`, `payments`, `pickups`, `deliveries`, `disputes`,
  `reliability_history`, `notifications`) is keyed only by `order_id` and
  required **no changes** — it was already order-type-agnostic.

---

## What's intentionally deferred (Phase 2, per the roadmap)

- Market intelligence layer (price trends, demand analytics, best-deal
  recommendations)
- Live GPS tracking (currently status-based, not map-based)
- Security deposit deduction workflows
- Trade Passport / financing integration
- File/image upload for listings, buyer requests, and inspection evidence

## Project structure

```
scraptrade-app/
├── app.py                  # All routes + business logic (forward + reverse flows)
├── database.py             # SQLite connection, schema init, seed data
├── schema.sql               # Full MVP database schema (11 tables)
├── requirements.txt
├── templates/
│   ├── base.html                 # Nav, flash messages, layout
│   ├── index.html                 # Landing page
│   ├── login.html / signup.html
│   ├── browse_listings.html       # Forward: marketplace browse
│   ├── listing_detail.html        # Forward: listing + bidding
│   ├── new_listing.html           # Forward: seller creates listing
│   ├── new_request.html           # Reverse: "Post Buying Request"
│   ├── browse_requests.html       # Reverse: "Browse Buyer Requests"
│   ├── request_detail.html        # Reverse: view request + seller bid form
│   ├── compare_bids.html          # Reverse: "Compare Bids" (buyer)
│   ├── my_requests.html           # Reverse: "My Requests" (buyer)
│   ├── my_bids.html               # Reverse: "My Bids" (seller)
│   ├── seller_dashboard.html / buyer_dashboard.html
│   ├── order_detail.html          # Shared order lifecycle view (both flows)
│   ├── admin_dashboard.html / admin_users.html
│   └── notifications.html
├── static/css/style.css     # Status badges + card styling
└── instance/scraptrade.db   # SQLite database (created on first run)
```

## Testing the reverse-bidding flow manually

1. Log in as `suresh@buyer.in` (password `password123`) → **Post Buying
   Request** → fill in material/quantity/price/expiry → submit. It appears
   under **My Requests**.
2. Log out, log in as `ramesh@scrap.in` → **Buyer Requests** → open the
   request you just posted → submit a bid.
3. Log in as a second seller (`anita@scrap.in`) and submit a competing bid
   on the same request.
4. Log back in as `suresh@buyer.in` → **My Requests** → the request now
   shows bid count → **Compare Bids** → review both offers side by side
   (price, quantity, seller KYC/reliability) → **Accept** the better one.
5. This creates an Order and redirects to its detail page. Log in as
   `admin@scraptrade.hub` → **Admin Dashboard** → pass inspection for that
   order → the order becomes payable.
6. Back as the buyer, pay (holds funds) → back as admin, assign logistics,
   record pickup weight, mark delivered → back as the buyer, confirm
   delivery. Payment releases, both parties' reliability scores update, and
   the order shows `Completed`.
7. To see the guard rails: try bidding twice as the same seller (blocked),
   try bidding as the buyer who owns the request (blocked), or try opening
   the seeded expired request "Mixed Paper Waste" as a seller (bidding is
   blocked because it's past its expiry date).

To reset all demo data at any time: delete `instance/scraptrade.db` and
re-run `python3 database.py`.

## Migrating this to the full production stack

The database schema (`schema.sql`) and route logic in `app.py` map directly
onto the PostgreSQL schema and REST API design in the main project
documentation. To move to the full stack described there:

1. Recreate `schema.sql`'s tables as Prisma/SQLAlchemy models against
   PostgreSQL — the entity relationships are unchanged.
2. Re-implement each Flask route in `app.py` as a FastAPI/NestJS endpoint
   returning JSON instead of rendered HTML.
3. Rebuild the Jinja2 templates as Next.js pages/components consuming that
   API.
4. Swap Flask sessions for JWT-based auth.

Everything else — the workflow phases, status transitions, tolerance-check
logic, and reliability-scoring rules — carries over unchanged.
