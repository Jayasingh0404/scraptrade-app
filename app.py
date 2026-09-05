import os
import secrets
import json
import urllib.request
import urllib.parse
import urllib.error
from functools import wraps
from datetime import datetime, date, timedelta

from flask import (Flask, render_template, request, redirect, url_for,
                    session, flash, g, abort, send_from_directory, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from database import get_db, init_db, seed_db, ensure_schema, DB_PATH

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS



STATUS_BADGE_MAP = {
    "active": "active", "completed": "completed", "delivered": "transit",
    "in_transit": "transit", "pickup_in_progress": "transit", "logistics_assigned": "transit",
    "payment_held": "held", "payment_pending": "pending", "pending_inspection": "pending",
    "inspection_passed": "held", "inspection_failed": "cancelled", "cancelled": "cancelled",
    "disputed": "disputed", "reserved": "pending", "sold": "completed", "suspended": "cancelled",
    "verified": "active", "rejected": "cancelled", "pending_kyc": "pending",
    "open": "disputed", "resolved": "completed",
}


@app.template_filter("badge")
def badge_filter(status):
    cls = STATUS_BADGE_MAP.get(status, "neutral")
    label = status.replace("_", " ").title()
    return f'<span class="badge badge-{cls}">{label}</span>'


@app.template_filter("money")
def money_filter(value):
    try:
        return f"\u20b9{float(value):,.0f}"
    except (TypeError, ValueError):
        return value


# ---------------------------------------------------------------------------
# DB / auth helpers
# ---------------------------------------------------------------------------

@app.before_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id:
        db = get_db()
        g.user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        db.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Please log in to continue.", "error")
                return redirect(url_for("login"))
            if g.user["role"] != role:
                flash("You don't have access to that page.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def log_reliability_change(db, user_id, delta, reason, order_id=None):
    user = db.execute("SELECT reliability_score FROM users WHERE id=?", (user_id,)).fetchone()
    prev = user["reliability_score"]
    new = max(0, min(100, prev + delta))
    db.execute("UPDATE users SET reliability_score=? WHERE id=?", (new, user_id))
    db.execute(
        """INSERT INTO reliability_history (user_id, previous_score, new_score, reason, related_order_id)
           VALUES (?,?,?,?,?)""",
        (user_id, prev, new, reason, order_id),
    )


def notify(db, user_id, title, message, order_id=None):
    db.execute(
        "INSERT INTO notifications (user_id, order_id, title, message) VALUES (?,?,?,?)",
        (user_id, order_id, title, message),
    )


def expire_stale_requests(db):
    """Lazily flip past-expiry buyer requests / reverse bids to 'expired'."""
    db.execute("UPDATE buyer_requests SET status='expired' WHERE status='open' AND expiry_date < date('now')")
    db.execute(
        "UPDATE reverse_bids SET status='expired' WHERE status='active' AND expiry_date IS NOT NULL AND expiry_date < date('now')"
    )
    db.commit()


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    db = get_db()
    listings = db.execute(
        """SELECT l.*, u.business_name, u.reliability_score,
                  (SELECT COUNT(*) FROM bids b WHERE b.listing_id = l.id) as bid_count
           FROM listings l JOIN users u ON l.seller_id = u.id
           WHERE l.status = 'active' ORDER BY l.created_at DESC LIMIT 6"""
    ).fetchall()
    stats = {
        "listings": db.execute("SELECT COUNT(*) c FROM listings WHERE status='active'").fetchone()["c"],
        "sellers": db.execute("SELECT COUNT(*) c FROM users WHERE role='seller'").fetchone()["c"],
        "buyers": db.execute("SELECT COUNT(*) c FROM users WHERE role='buyer'").fetchone()["c"],
        "completed": db.execute("SELECT COUNT(*) c FROM orders WHERE status='completed'").fetchone()["c"],
    }
    db.close()
    return render_template("index.html", listings=listings, stats=stats)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        role = request.form["role"]
        name = request.form["full_name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form["password"]
        business = request.form.get("business_name", "").strip() or None
        location = request.form.get("location", "").strip() or None
        gst = request.form.get("gst_number", "").strip() or None
        seller_type = request.form.get("seller_type") if role == "seller" else None

        if not name or not email or not password:
            flash("Name, email and password are required.", "error")
            return render_template("signup.html")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            flash("An account with this email already exists.", "error")
            db.close()
            return render_template("signup.html")

        cur = db.cursor()
        cur.execute(
            """INSERT INTO users (full_name, email, phone, password_hash, role, business_name,
               location, gst_number, kyc_status, seller_type)
               VALUES (?,?,?,?,?,?,?,?, 'pending', ?)""",
            (name, email, phone, generate_password_hash(password), role, business,
             location, gst, seller_type),
        )
        user_id = cur.lastrowid
        if role == "seller" and seller_type == "verified_deposit":
            cur.execute(
                "INSERT INTO deposits (seller_id, deposit_amount, current_balance, status) VALUES (?,0,0,'pending')",
                (user_id,),
            )
        db.commit()
        db.close()

        session["user_id"] = user_id
        flash("Account created. Your KYC verification is pending review.", "success")
        return redirect(url_for("dashboard"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        db.close()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")
        session["user_id"] = user["id"]
        flash(f"Welcome back, {user['full_name']}.", "success")
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You've been logged out.", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Forgot Password / Password Reset System
# ---------------------------------------------------------------------------

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    reset_link = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            flash("Please enter your registered email address.", "error")
            return render_template("forgot_password.html")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user:
            token = secrets.token_urlsafe(32)
            # Token expires in 1 hour
            expires_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            # Invalidate any existing unused tokens for this email
            db.execute("UPDATE password_resets SET used=1 WHERE email=? AND used=0", (email,))
            db.execute(
                "INSERT INTO password_resets (email, token, expires_at) VALUES (?,?,?)",
                (email, token, expires_at),
            )
            db.commit()
            
            # Generate the password reset link
            reset_link = url_for("reset_password", token=token, _external=True)
            flash(
                f"Password reset link generated for {email}. In a production environment, this link is emailed.",
                "success",
            )
        else:
            # Security best practice: don't reveal whether the user exists or not, but give positive feedback
            flash("If an account exists with that email, a password reset link has been created.", "info")
        db.close()
        return render_template("forgot_password.html", reset_link=reset_link, submitted_email=email)

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    db = get_db()
    reset_entry = db.execute(
        "SELECT * FROM password_resets WHERE token=? AND used=0", (token,)
    ).fetchone()

    if not reset_entry:
        db.close()
        flash("Invalid or expired password reset link. Please request a new one.", "error")
        return redirect(url_for("forgot_password"))

    # Check expiration
    expires_at = datetime.strptime(reset_entry["expires_at"], "%Y-%m-%d %H:%M:%S")
    if datetime.now() > expires_at:
        db.execute("UPDATE password_resets SET used=1 WHERE id=?", (reset_entry["id"],))
        db.commit()
        db.close()
        flash("This password reset link has expired. Please request a new one.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            db.close()
            return render_template("reset_password.html", token=token)

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            db.close()
            return render_template("reset_password.html", token=token)

        new_hash = generate_password_hash(password)
        db.execute("UPDATE users SET password_hash=? WHERE email=?", (new_hash, reset_entry["email"]))
        db.execute("UPDATE password_resets SET used=1 WHERE id=?", (reset_entry["id"],))
        db.commit()
        db.close()

        flash("Your password has been successfully reset. Please log in with your new password.", "success")
        return redirect(url_for("login"))

    db.close()
    return render_template("reset_password.html", token=token, email=reset_entry["email"])


# ---------------------------------------------------------------------------
# Google Authentication (OAuth 2.0 / OpenID Connect & Interactive Dev Flow)
# ---------------------------------------------------------------------------

def exchange_google_code_for_user(code, redirect_uri):
    """Exchanges Google authorization code for access token and retrieves user profile."""
    client_id = app.config.get("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = app.config.get("GOOGLE_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET", "")
    
    if not client_id or not client_secret:
        return None, "Google OAuth client credentials are not configured on the server."

    token_url = "https://oauth2.googleapis.com/token"
    token_params = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    encoded_data = urllib.parse.urlencode(token_params).encode("utf-8")
    req = urllib.request.Request(
        token_url,
        data=encoded_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "ScrapTrade-OAuth/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_response = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_text = e.read().decode("utf-8", errors="ignore")
        return None, f"Google token exchange failed ({e.code}): {err_text}"
    except Exception as e:
        return None, f"Network error connecting to Google authentication: {str(e)}"

    access_token = token_response.get("access_token")
    if not access_token:
        return None, "Google did not provide an access token in the response."

    # Fetch user profile using OpenID Connect userinfo endpoint
    userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    user_req = urllib.request.Request(
        userinfo_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "ScrapTrade-OAuth/1.0",
        },
    )

    try:
        with urllib.request.urlopen(user_req, timeout=10) as resp:
            user_profile = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None, f"Failed to retrieve Google profile: {str(e)}"

    return user_profile, None


def process_google_user(email, full_name, google_id, avatar_url=None):
    """Logs in an existing user or stores pending user state for role onboarding."""
    if not email:
        return False, None, "Google account does not contain a verified email."

    email = email.strip().lower()
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE email=? OR (google_id IS NOT NULL AND google_id=?)",
        (email, google_id),
    ).fetchone()

    if user:
        # Existing account: update linked google_id / avatar if missing and log in
        session["user_id"] = user["id"]
        db.execute(
            "UPDATE users SET google_id=COALESCE(google_id, ?), avatar_url=COALESCE(avatar_url, ?) WHERE id=?",
            (google_id, avatar_url, user["id"]),
        )
        db.commit()
        db.close()
        return True, user, None

    # New user: store details in session for onboarding
    session["google_pending_user"] = {
        "email": email,
        "full_name": full_name or "Google User",
        "google_id": google_id,
        "avatar_url": avatar_url,
    }
    db.close()
    return False, None, None


@app.route("/auth/google")
def google_auth():
    """Initiates Google OAuth 2.0 authorization redirect or opens local dev login."""
    google_client_id = app.config.get("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID", "")
    google_client_secret = app.config.get("GOOGLE_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET", "")
    
    if google_client_id and google_client_secret:
        # Generate cryptographically secure CSRF state token
        state = secrets.token_urlsafe(32)
        session["oauth_state"] = state
        
        redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI") or url_for("google_callback", _external=True)
        query_params = {
            "client_id": google_client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": redirect_uri,
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        oauth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(query_params)}"
        return redirect(oauth_url)
    else:
        # Render interactive Google Sign-In helper for development
        return render_template("google_signin_dev.html")


@app.route("/auth/google/callback")
def google_callback():
    """Handles Google OAuth 2.0 authorization callback."""
    # 1. Check for errors from Google consent flow
    error = request.args.get("error")
    if error:
        if error == "access_denied":
            flash("Google sign-in was cancelled.", "info")
        else:
            flash(f"Google sign-in error: {error}", "error")
        return redirect(url_for("login"))

    # 2. Verify CSRF state token
    received_state = request.args.get("state")
    saved_state = session.pop("oauth_state", None)
    if not received_state or not saved_state or received_state != saved_state:
        flash("Authentication session expired or security verification failed. Please try again.", "error")
        return redirect(url_for("login"))

    # 3. Retrieve authorization code
    code = request.args.get("code")
    if not code:
        flash("Authorization code missing from Google response.", "error")
        return redirect(url_for("login"))

    # 4. Exchange code for access token and user info
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI") or url_for("google_callback", _external=True)
    user_info, err = exchange_google_code_for_user(code, redirect_uri)
    if err:
        flash(err, "error")
        return redirect(url_for("login"))

    email = user_info.get("email")
    full_name = user_info.get("name") or user_info.get("given_name", "Google User")
    google_id = user_info.get("sub")
    avatar_url = user_info.get("picture")

    # 5. Process user login / onboarding
    is_existing, user, proc_err = process_google_user(email, full_name, google_id, avatar_url)
    if proc_err:
        flash(proc_err, "error")
        return redirect(url_for("login"))

    if is_existing:
        flash(f"Welcome back, {user['full_name']}! Signed in with Google.", "success")
        return redirect(url_for("dashboard"))
    else:
        return redirect(url_for("google_select_role"))


@app.route("/auth/google/mock-login", methods=["POST"])
def google_mock_login():
    """Provides high-fidelity Google Sign-In for development and automated testing."""
    email = request.form.get("email", "").strip().lower()
    full_name = request.form.get("full_name", "").strip() or "Google User"
    google_id = request.form.get("google_id", "").strip() or f"google_{secrets.token_hex(8)}"
    avatar_url = request.form.get("avatar_url", "").strip()

    if not email:
        flash("Email is required for Google Sign-In.", "error")
        return redirect(url_for("login"))

    is_existing, user, proc_err = process_google_user(email, full_name, google_id, avatar_url)
    if proc_err:
        flash(proc_err, "error")
        return redirect(url_for("login"))

    if is_existing:
        flash(f"Signed in with Google as {user['full_name']}.", "success")
        return redirect(url_for("dashboard"))
    else:
        return redirect(url_for("google_select_role"))


@app.route("/auth/google/select-role", methods=["GET", "POST"])
def google_select_role():
    pending = session.get("google_pending_user")
    if not pending:
        flash("No pending Google login session found. Please sign in again.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        role = request.form.get("role", "buyer")
        business_name = request.form.get("business_name", "").strip() or None
        location = request.form.get("location", "").strip() or None
        phone = request.form.get("phone", "").strip() or None
        gst_number = request.form.get("gst_number", "").strip() or None
        seller_type = request.form.get("seller_type") if role == "seller" else None

        db = get_db()
        cur = db.cursor()
        cur.execute(
            """INSERT INTO users (full_name, email, phone, password_hash, role, business_name,
               location, gst_number, kyc_status, seller_type, google_id, avatar_url)
               VALUES (?,?,?,?,?,?,?,?, 'verified', ?, ?, ?)""",
            (
                pending["full_name"],
                pending["email"],
                phone,
                generate_password_hash(secrets.token_urlsafe(16)),  # random password for google accounts
                role,
                business_name,
                location,
                gst_number,
                seller_type,
                pending["google_id"],
                pending["avatar_url"],
            ),
        )
        user_id = cur.lastrowid
        if role == "seller" and seller_type == "verified_deposit":
            cur.execute(
                "INSERT INTO deposits (seller_id, deposit_amount, current_balance, status) VALUES (?,25000,25000,'active')",
                (user_id,),
            )
        db.commit()
        db.close()

        # Clear pending and log in
        session.pop("google_pending_user", None)
        session["user_id"] = user_id
        flash(f"Welcome to ScrapTrade, {pending['full_name']}! Your Google account is now linked.", "success")
        return redirect(url_for("dashboard"))

    return render_template("google_role_select.html", user_info=pending)



@app.route("/dashboard")
@login_required
def dashboard():
    if g.user["role"] == "seller":
        return redirect(url_for("seller_dashboard"))
    if g.user["role"] == "buyer":
        return redirect(url_for("buyer_dashboard"))
    if g.user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    abort(403)


# ---------------------------------------------------------------------------
# Marketplace browsing (buyers, but visible to all)
# ---------------------------------------------------------------------------

@app.route("/listings")
def browse_listings():
    db = get_db()
    query = "SELECT l.*, u.business_name, u.reliability_score FROM listings l JOIN users u ON l.seller_id=u.id WHERE l.status='active'"
    params = []
    material = request.args.get("material", "").strip()
    location = request.args.get("location", "").strip()
    max_price = request.args.get("max_price", "").strip()

    if material:
        query += " AND (l.material_type LIKE ? OR l.category LIKE ?)"
        params += [f"%{material}%", f"%{material}%"]
    if location:
        query += " AND l.location LIKE ?"
        params.append(f"%{location}%")
    if max_price:
        try:
            query += " AND l.expected_price <= ?"
            params.append(float(max_price))
        except ValueError:
            pass
    query += " ORDER BY l.created_at DESC"

    listings = db.execute(query, params).fetchall()
    db.close()
    return render_template("browse_listings.html", listings=listings,
                            filters={"material": material, "location": location, "max_price": max_price})


@app.route("/listings/<int:listing_id>", methods=["GET", "POST"])
@login_required
def listing_detail(listing_id):
    db = get_db()
    listing = db.execute(
        """SELECT l.*, u.business_name, u.reliability_score, u.location as seller_location, u.id as seller_user_id
           FROM listings l JOIN users u ON l.seller_id = u.id WHERE l.id=?""", (listing_id,)
    ).fetchone()
    if listing is None:
        db.close()
        abort(404)

    if request.method == "POST":
        if g.user["role"] != "buyer":
            flash("Only buyers can place bids.", "error")
        elif listing["status"] != "active":
            flash("This listing is no longer accepting bids.", "error")
        else:
            bid_price = float(request.form["bid_price"])
            quantity = float(request.form["quantity"])
            message = request.form.get("message", "").strip()
            db.execute(
                """INSERT INTO bids (listing_id, buyer_id, bid_price, quantity, message, status)
                   VALUES (?,?,?,?,?, 'active')""",
                (listing_id, g.user["id"], bid_price, quantity, message),
            )
            notify(db, listing["seller_id"], "New bid received",
                   f"{g.user['business_name'] or g.user['full_name']} bid \u20b9{bid_price}/unit on your listing.",
                   None)
            db.commit()
            flash("Your bid has been submitted.", "success")
        db.close()
        return redirect(url_for("listing_detail", listing_id=listing_id))

    bids = db.execute(
        """SELECT b.*, u.business_name, u.full_name, u.reliability_score
           FROM bids b JOIN users u ON b.buyer_id = u.id
           WHERE b.listing_id=? ORDER BY b.bid_price DESC""", (listing_id,)
    ).fetchall()
    db.close()
    return render_template("listing_detail.html", listing=listing, bids=bids)


# ---------------------------------------------------------------------------
# Seller area
# ---------------------------------------------------------------------------

@app.route("/seller/dashboard")
@role_required("seller")
def seller_dashboard():
    db = get_db()
    listings = db.execute(
        """SELECT l.*, (SELECT COUNT(*) FROM bids b WHERE b.listing_id=l.id AND b.status='active') as bid_count
           FROM listings l WHERE l.seller_id=? ORDER BY l.created_at DESC""", (g.user["id"],)
    ).fetchall()
    orders = db.execute(
        "SELECT * FROM orders WHERE seller_id=? ORDER BY created_at DESC", (g.user["id"],)
    ).fetchall()
    deposit = db.execute("SELECT * FROM deposits WHERE seller_id=?", (g.user["id"],)).fetchone()
    my_active_request_bids = db.execute(
        """SELECT COUNT(*) c FROM reverse_bids WHERE seller_id=? AND status='active'""", (g.user["id"],)
    ).fetchone()["c"]
    db.close()
    active_count = sum(1 for l in listings if l["status"] == "active")
    completed_count = sum(1 for o in orders if o["status"] == "completed")
    return render_template("seller_dashboard.html", listings=listings, orders=orders,
                            deposit=deposit, active_count=active_count, completed_count=completed_count,
                            my_active_request_bids=my_active_request_bids)


@app.route("/seller/listings/new", methods=["GET", "POST"])
@role_required("seller")
def new_listing():
    if request.method == "POST":
        image_url = None
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{int(datetime.now().timestamp())}_{file.filename}")
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                image_url = f"/static/uploads/{filename}"

        db = get_db()
        db.execute(
            """INSERT INTO listings (seller_id, material_type, category, grade, estimated_quantity,
               unit, expected_price, location, description, image_url, status)
               VALUES (?,?,?,?,?,?,?,?,?,?, 'active')""",
            (g.user["id"], request.form["material_type"], request.form["category"],
             request.form.get("grade", ""), float(request.form["estimated_quantity"]),
             request.form.get("unit", "kg"), float(request.form["expected_price"]),
             request.form["location"], request.form.get("description", ""), image_url),
        )
        db.commit()
        db.close()
        flash("Listing published successfully with verified details.", "success")
        return redirect(url_for("seller_dashboard"))
    return render_template("new_listing.html")


@app.route("/seller/listings/<int:listing_id>/accept-bid/<int:bid_id>", methods=["POST"])
@role_required("seller")
def accept_bid(listing_id, bid_id):
    db = get_db()
    listing = db.execute("SELECT * FROM listings WHERE id=? AND seller_id=?",
                          (listing_id, g.user["id"])).fetchone()
    bid = db.execute("SELECT * FROM bids WHERE id=? AND listing_id=?", (bid_id, listing_id)).fetchone()
    if listing is None or bid is None:
        db.close()
        abort(404)

    db.execute("UPDATE bids SET status='accepted' WHERE id=?", (bid_id,))
    db.execute("UPDATE bids SET status='rejected' WHERE listing_id=? AND id != ? AND status='active'",
               (listing_id, bid_id))
    db.execute("UPDATE listings SET status='reserved' WHERE id=?", (listing_id,))

    cur = db.cursor()
    total = bid["bid_price"] * bid["quantity"]
    cur.execute(
        """INSERT INTO orders (order_type, listing_id, bid_id, buyer_id, seller_id,
           material_type, category, unit, estimated_quantity, agreed_price, total_amount, status)
           VALUES ('forward', ?,?,?,?,?,?,?,?,?,?, 'pending_inspection')""",
        (listing_id, bid_id, bid["buyer_id"], g.user["id"],
         listing["material_type"], listing["category"], listing["unit"],
         bid["quantity"], bid["bid_price"], total),
    )
    order_id = cur.lastrowid
    cur.execute("INSERT INTO inspections (order_id, result) VALUES (?, 'requested')", (order_id,))
    notify(db, bid["buyer_id"], "Your bid was accepted",
           f"Order #{order_id} created. Inspection will be scheduled next.", order_id)
    db.commit()
    db.close()
    flash("Bid accepted. Order created and inspection requested.", "success")
    return redirect(url_for("order_detail", order_id=order_id))


# ---------------------------------------------------------------------------
# Buyer area
# ---------------------------------------------------------------------------

@app.route("/buyer/dashboard")
@role_required("buyer")
def buyer_dashboard():
    db = get_db()
    my_bids = db.execute(
        """SELECT b.*, l.material_type, l.expected_price, l.status as listing_status
           FROM bids b JOIN listings l ON b.listing_id = l.id
           WHERE b.buyer_id=? ORDER BY b.created_at DESC""", (g.user["id"],)
    ).fetchall()
    orders = db.execute(
        "SELECT * FROM orders WHERE buyer_id=? ORDER BY created_at DESC", (g.user["id"],)
    ).fetchall()
    open_requests_count = db.execute(
        "SELECT COUNT(*) c FROM buyer_requests WHERE buyer_id=? AND status='open'", (g.user["id"],)
    ).fetchone()["c"]
    db.close()
    active_orders = sum(1 for o in orders if o["status"] not in ("completed", "cancelled"))
    completed_count = sum(1 for o in orders if o["status"] == "completed")
    return render_template("buyer_dashboard.html", bids=my_bids, orders=orders,
                            active_orders=active_orders, completed_count=completed_count,
                            open_requests_count=open_requests_count)


# ---------------------------------------------------------------------------
# Buyer -> Seller Reverse Bidding
#   Buyer posts a purchase request; verified sellers discover it and bid;
#   buyer compares bids and accepts one, which creates an Order that flows
#   through the exact same inspection/payment/logistics/dispute pipeline
#   used by the forward (seller-listing) marketplace.
# ---------------------------------------------------------------------------

@app.route("/requests/new", methods=["GET", "POST"])
@role_required("buyer")
def new_request():
    if request.method == "POST":
        material_type = request.form.get("material_type", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        expiry = request.form.get("expiry_date", "").strip()
        try:
            required_quantity = float(request.form["required_quantity"])
            max_price = float(request.form["max_price"])
        except (KeyError, ValueError):
            flash("Please enter valid numbers for quantity and price.", "error")
            return render_template("new_request.html")

        if not material_type or not category or not location:
            flash("Material type, category and location are required.", "error")
            return render_template("new_request.html")
        if required_quantity <= 0 or max_price <= 0:
            flash("Quantity and price must be greater than zero.", "error")
            return render_template("new_request.html")
        if not expiry or expiry < date.today().isoformat():
            flash("Expiry date must be a valid date in the future.", "error")
            return render_template("new_request.html")

        image_url = None
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"req_{int(datetime.now().timestamp())}_{file.filename}")
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                image_url = f"/static/uploads/{filename}"

        db = get_db()
        db.execute(
            """INSERT INTO buyer_requests (buyer_id, material_type, category, grade, required_quantity,
               unit, location, max_price, delivery_preference, description, image_url, expiry_date, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'open')""",
            (g.user["id"], material_type, category, request.form.get("grade", "").strip(),
             required_quantity, request.form.get("unit", "kg"), location, max_price,
             request.form.get("delivery_preference", "pickup"),
             request.form.get("description", "").strip(), image_url, expiry),
        )
        db.commit()
        db.close()
        flash("Buying request posted. Verified sellers can now discover and bid on it.", "success")
        return redirect(url_for("my_requests"))

    return render_template("new_request.html", min_date=date.today().isoformat())


@app.route("/requests")
@role_required("seller")
def browse_requests():
    db = get_db()
    expire_stale_requests(db)
    query = """SELECT r.*, u.business_name, u.full_name, u.reliability_score,
                      (SELECT COUNT(*) FROM reverse_bids rb WHERE rb.request_id=r.id AND rb.status='active') as bid_count
               FROM buyer_requests r JOIN users u ON r.buyer_id = u.id
               WHERE r.status='open'"""
    params = []
    material = request.args.get("material", "").strip()
    location = request.args.get("location", "").strip()
    if material:
        query += " AND (r.material_type LIKE ? OR r.category LIKE ?)"
        params += [f"%{material}%", f"%{material}%"]
    if location:
        query += " AND r.location LIKE ?"
        params.append(f"%{location}%")
    query += " ORDER BY r.created_at DESC"

    requests_list = db.execute(query, params).fetchall()
    my_active_ids = {
        row["request_id"] for row in db.execute(
            "SELECT request_id FROM reverse_bids WHERE seller_id=? AND status='active'", (g.user["id"],)
        ).fetchall()
    }
    db.close()
    return render_template("browse_requests.html", requests=requests_list,
                            filters={"material": material, "location": location},
                            my_active_ids=my_active_ids, eligible=(g.user["kyc_status"] == "verified"))


@app.route("/requests/mine")
@role_required("buyer")
def my_requests():
    db = get_db()
    expire_stale_requests(db)
    rows = db.execute(
        """SELECT r.*, (SELECT COUNT(*) FROM reverse_bids rb WHERE rb.request_id=r.id AND rb.status='active') as bid_count
           FROM buyer_requests r WHERE r.buyer_id=? ORDER BY r.created_at DESC""", (g.user["id"],)
    ).fetchall()
    db.close()
    return render_template("my_requests.html", requests=rows)


@app.route("/requests/<int:request_id>/cancel", methods=["POST"])
@role_required("buyer")
def cancel_request(request_id):
    db = get_db()
    req = db.execute("SELECT * FROM buyer_requests WHERE id=? AND buyer_id=?",
                      (request_id, g.user["id"])).fetchone()
    if req is None:
        db.close()
        abort(404)
    if req["status"] != "open":
        flash("Only open requests can be cancelled.", "error")
    else:
        db.execute("UPDATE buyer_requests SET status='cancelled' WHERE id=?", (request_id,))
        active_bids = db.execute(
            "SELECT seller_id FROM reverse_bids WHERE request_id=? AND status='active'", (request_id,)
        ).fetchall()
        db.execute("UPDATE reverse_bids SET status='withdrawn' WHERE request_id=? AND status='active'",
                   (request_id,))
        for b in active_bids:
            notify(db, b["seller_id"], "Buying request cancelled",
                   f"The buyer cancelled the request for '{req['material_type']}'. Your bid has been withdrawn.")
        db.commit()
        flash("Request cancelled.", "success")
    db.close()
    return redirect(url_for("my_requests"))


@app.route("/requests/<int:request_id>", methods=["GET", "POST"])
@login_required
def request_detail(request_id):
    db = get_db()
    expire_stale_requests(db)
    req = db.execute(
        """SELECT r.*, u.business_name, u.full_name, u.reliability_score, u.location as buyer_location
           FROM buyer_requests r JOIN users u ON r.buyer_id = u.id WHERE r.id=?""", (request_id,)
    ).fetchone()
    if req is None:
        db.close()
        abort(404)

    is_owner = g.user["id"] == req["buyer_id"]
    if g.user["role"] == "buyer" and not is_owner:
        # Buyers only get visibility into their own requests (per-buyer privacy).
        db.close()
        abort(403)

    if request.method == "POST":
        if g.user["role"] != "seller":
            flash("Only sellers can submit bids on buyer requests.", "error")
        elif req["buyer_id"] == g.user["id"]:
            flash("You cannot bid on your own request.", "error")
        elif g.user["kyc_status"] != "verified":
            flash("Only KYC-verified sellers can submit bids. Complete verification first.", "error")
        elif req["status"] != "open":
            flash("This request is no longer accepting bids (closed or expired).", "error")
        else:
            existing = db.execute(
                "SELECT id FROM reverse_bids WHERE request_id=? AND seller_id=? AND status='active'",
                (request_id, g.user["id"]),
            ).fetchone()
            if existing:
                flash("You already have an active bid on this request. Withdraw it first to rebid.", "error")
            else:
                try:
                    offered_price = float(request.form["offered_price"])
                    available_quantity = float(request.form["available_quantity"])
                except (KeyError, ValueError):
                    flash("Please enter valid numbers for price and quantity.", "error")
                    db.close()
                    return redirect(url_for("request_detail", request_id=request_id))
                bid_expiry = request.form.get("expiry_date", "").strip() or None
                db.execute(
                    """INSERT INTO reverse_bids (request_id, seller_id, offered_price, available_quantity,
                       grade, delivery_option, message, expiry_date, status)
                       VALUES (?,?,?,?,?,?,?,?, 'active')""",
                    (request_id, g.user["id"], offered_price, available_quantity,
                     request.form.get("grade", "").strip(), request.form.get("delivery_option", "pickup"),
                     request.form.get("message", "").strip(), bid_expiry),
                )
                notify(db, req["buyer_id"], "New bid on your request",
                       f"{g.user['business_name'] or g.user['full_name']} bid {money_filter(offered_price)}/{req['unit']} "
                       f"on your '{req['material_type']}' request.")
                db.commit()
                flash("Your bid has been submitted.", "success")
        db.close()
        return redirect(url_for("request_detail", request_id=request_id))

    my_bid = None
    if g.user["role"] == "seller":
        my_bid = db.execute(
            "SELECT * FROM reverse_bids WHERE request_id=? AND seller_id=? ORDER BY id DESC LIMIT 1",
            (request_id, g.user["id"]),
        ).fetchone()
    bid_count = db.execute(
        "SELECT COUNT(*) c FROM reverse_bids WHERE request_id=? AND status='active'", (request_id,)
    ).fetchone()["c"]
    db.close()
    return render_template("request_detail.html", req=req, my_bid=my_bid, bid_count=bid_count,
                            is_owner=is_owner,
                            can_bid=(g.user["role"] == "seller" and g.user["kyc_status"] == "verified"))


@app.route("/requests/<int:request_id>/compare")
@role_required("buyer")
def compare_bids(request_id):
    db = get_db()
    expire_stale_requests(db)
    req = db.execute("SELECT * FROM buyer_requests WHERE id=?", (request_id,)).fetchone()
    if req is None:
        db.close()
        abort(404)
    if req["buyer_id"] != g.user["id"]:
        db.close()
        abort(403)
    bids = db.execute(
        """SELECT rb.*, u.business_name, u.full_name, u.reliability_score, u.kyc_status,
                  u.successful_deals, u.disputes_count, u.seller_type
           FROM reverse_bids rb JOIN users u ON rb.seller_id = u.id
           WHERE rb.request_id=?
           ORDER BY CASE rb.status WHEN 'active' THEN 0 ELSE 1 END, rb.offered_price ASC""",
        (request_id,),
    ).fetchall()
    db.close()
    return render_template("compare_bids.html", req=req, bids=bids)


@app.route("/requests/<int:request_id>/bids/<int:bid_id>/accept", methods=["POST"])
@role_required("buyer")
def accept_reverse_bid(request_id, bid_id):
    db = get_db()
    req = db.execute("SELECT * FROM buyer_requests WHERE id=? AND buyer_id=?",
                      (request_id, g.user["id"])).fetchone()
    bid = db.execute("SELECT * FROM reverse_bids WHERE id=? AND request_id=?",
                      (bid_id, request_id)).fetchone()
    if req is None or bid is None:
        db.close()
        abort(404)
    if req["status"] != "open":
        flash("This request is no longer open.", "error")
        db.close()
        return redirect(url_for("compare_bids", request_id=request_id))
    if bid["status"] != "active":
        flash("This bid is no longer active and cannot be accepted.", "error")
        db.close()
        return redirect(url_for("compare_bids", request_id=request_id))

    db.execute("UPDATE reverse_bids SET status='accepted' WHERE id=?", (bid_id,))
    rejected_sellers = db.execute(
        "SELECT seller_id FROM reverse_bids WHERE request_id=? AND id != ? AND status='active'",
        (request_id, bid_id),
    ).fetchall()
    db.execute("UPDATE reverse_bids SET status='rejected' WHERE request_id=? AND id != ? AND status='active'",
               (request_id, bid_id))
    db.execute("UPDATE buyer_requests SET status='fulfilled' WHERE id=?", (request_id,))

    cur = db.cursor()
    total = bid["offered_price"] * bid["available_quantity"]
    cur.execute(
        """INSERT INTO orders (order_type, request_id, reverse_bid_id, buyer_id, seller_id,
           material_type, category, unit, estimated_quantity, agreed_price, total_amount, status)
           VALUES ('reverse', ?,?,?,?,?,?,?,?,?,?, 'pending_inspection')""",
        (request_id, bid_id, g.user["id"], bid["seller_id"],
         req["material_type"], req["category"], req["unit"],
         bid["available_quantity"], bid["offered_price"], total),
    )
    order_id = cur.lastrowid
    cur.execute("INSERT INTO inspections (order_id, result) VALUES (?, 'requested')", (order_id,))

    notify(db, bid["seller_id"], "Your bid was accepted",
           f"Order #{order_id} created for '{req['material_type']}'. Inspection will be scheduled next.", order_id)
    notify(db, g.user["id"], "Order created from your buying request",
           f"Order #{order_id} created for '{req['material_type']}'. Inspection will be scheduled next.", order_id)
    for r in rejected_sellers:
        notify(db, r["seller_id"], "Bid not selected",
               f"Another seller was selected for the '{req['material_type']}' request.")

    db.commit()
    db.close()
    flash("Bid accepted. Order created and inspection requested.", "success")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/requests/<int:request_id>/bids/<int:bid_id>/reject", methods=["POST"])
@role_required("buyer")
def reject_reverse_bid(request_id, bid_id):
    db = get_db()
    req = db.execute("SELECT * FROM buyer_requests WHERE id=? AND buyer_id=?",
                      (request_id, g.user["id"])).fetchone()
    bid = db.execute("SELECT * FROM reverse_bids WHERE id=? AND request_id=?",
                      (bid_id, request_id)).fetchone()
    if req is None or bid is None:
        db.close()
        abort(404)
    if bid["status"] != "active":
        flash("This bid is no longer active.", "error")
        db.close()
        return redirect(url_for("compare_bids", request_id=request_id))
    db.execute("UPDATE reverse_bids SET status='rejected' WHERE id=?", (bid_id,))
    notify(db, bid["seller_id"], "Bid rejected",
           f"Your bid on the '{req['material_type']}' request was not accepted.")
    db.commit()
    db.close()
    flash("Bid rejected.", "success")
    return redirect(url_for("compare_bids", request_id=request_id))


@app.route("/bids/mine")
@role_required("seller")
def my_bids():
    db = get_db()
    expire_stale_requests(db)
    rows = db.execute(
        """SELECT rb.*, r.material_type, r.category, r.location as request_location,
                  r.status as request_status, r.required_quantity, r.unit, r.max_price
           FROM reverse_bids rb JOIN buyer_requests r ON rb.request_id = r.id
           WHERE rb.seller_id=? ORDER BY rb.created_at DESC""", (g.user["id"],)
    ).fetchall()
    db.close()
    return render_template("my_bids.html", bids=rows)


@app.route("/bids/<int:bid_id>/withdraw", methods=["POST"])
@role_required("seller")
def withdraw_reverse_bid(bid_id):
    db = get_db()
    bid = db.execute("SELECT * FROM reverse_bids WHERE id=? AND seller_id=?",
                      (bid_id, g.user["id"])).fetchone()
    if bid is None:
        db.close()
        abort(404)
    if bid["status"] != "active":
        flash("Only active bids can be withdrawn.", "error")
    else:
        db.execute("UPDATE reverse_bids SET status='withdrawn' WHERE id=?", (bid_id,))
        db.commit()
        flash("Bid withdrawn. You can submit a new bid on this request if it's still open.", "success")
    db.close()
    return redirect(url_for("my_bids"))


# ---------------------------------------------------------------------------
# Order detail + workflow actions (buyer + seller shared view)
# ---------------------------------------------------------------------------

@app.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    db = get_db()
    order = db.execute(
        """SELECT o.*,
                  bu.full_name as buyer_name, bu.business_name as buyer_business,
                  se.full_name as seller_name, se.business_name as seller_business
           FROM orders o
           JOIN users bu ON o.buyer_id = bu.id
           JOIN users se ON o.seller_id = se.id
           WHERE o.id=?""", (order_id,)
    ).fetchone()
    if order is None:
        db.close()
        abort(404)
    if g.user["id"] not in (order["buyer_id"], order["seller_id"]) and g.user["role"] != "admin":
        db.close()
        abort(403)

    inspection = db.execute("SELECT * FROM inspections WHERE order_id=? ORDER BY id DESC LIMIT 1", (order_id,)).fetchone()
    payment = db.execute("SELECT * FROM payments WHERE order_id=?", (order_id,)).fetchone()
    pickup = db.execute("SELECT * FROM pickups WHERE order_id=?", (order_id,)).fetchone()
    delivery = db.execute("SELECT * FROM deliveries WHERE order_id=?", (order_id,)).fetchone()
    dispute = db.execute("SELECT * FROM disputes WHERE order_id=? ORDER BY id DESC LIMIT 1", (order_id,)).fetchone()
    db.close()
    return render_template("order_detail.html", order=order, inspection=inspection, payment=payment,
                            pickup=pickup, delivery=delivery, dispute=dispute)





@app.route("/orders/<int:order_id>/pay", methods=["POST"])
@login_required
def order_pay(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if order is None or order["buyer_id"] != g.user["id"]:
        db.close()
        abort(403)
    if order["status"] != "inspection_passed":
        flash("Payment can only be made after inspection has passed.", "error")
        db.close()
        return redirect(url_for("order_detail", order_id=order_id))

    db.execute(
        """INSERT INTO payments (order_id, total_amount, status, amount_held)
           VALUES (?,?, 'held', ?)""", (order_id, order["total_amount"], order["total_amount"]))
    db.execute("UPDATE orders SET status='payment_held' WHERE id=?", (order_id,))
    db.execute("INSERT INTO pickups (order_id, pickup_status) VALUES (?, 'scheduled')", (order_id,))
    notify(db, order["seller_id"], "Payment held by platform",
           f"Buyer has paid for order #{order_id}. Funds are held until delivery is confirmed. Pickup will be scheduled.",
           order_id)
    db.commit()
    db.close()
    flash("Payment submitted and held securely by the platform. Logistics will be assigned next.", "success")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/confirm-delivery", methods=["POST"])
@login_required
def confirm_delivery(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if order is None or order["buyer_id"] != g.user["id"]:
        db.close()
        abort(403)
    if order["status"] != "delivered":
        flash("Delivery must be marked delivered before it can be confirmed.", "error")
        db.close()
        return redirect(url_for("order_detail", order_id=order_id))

    db.execute("UPDATE deliveries SET delivery_status='confirmed', buyer_confirmation=1 WHERE order_id=?", (order_id,))
    db.execute("UPDATE orders SET status='completed' WHERE id=?", (order_id,))
    if order["order_type"] == "forward" and order["listing_id"]:
        db.execute("UPDATE listings SET status='sold' WHERE id=?", (order["listing_id"],))
    payment = db.execute("SELECT * FROM payments WHERE order_id=?", (order_id,)).fetchone()
    db.execute("UPDATE payments SET status='released', amount_released=? WHERE order_id=?",
               (payment["amount_held"], order_id))
    db.execute("UPDATE users SET successful_deals = successful_deals + 1 WHERE id IN (?,?)",
               (order["buyer_id"], order["seller_id"]))
    log_reliability_change(db, order["seller_id"], 2, "Order completed successfully", order_id)
    log_reliability_change(db, order["buyer_id"], 1, "Order completed successfully", order_id)
    notify(db, order["seller_id"], "Payment released",
           f"Delivery confirmed for order #{order_id}. Payment has been released to you.", order_id)
    db.commit()
    db.close()
    flash("Delivery confirmed. Payment released to seller. Transaction complete.", "success")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/raise-issue", methods=["POST"])
@login_required
def raise_issue(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if order is None or order["buyer_id"] != g.user["id"]:
        db.close()
        abort(403)
    issue_type = request.form["issue_type"]
    description = request.form.get("description", "")
    db.execute(
        """INSERT INTO disputes (order_id, raised_by, issue_type, description, status)
           VALUES (?,?,?,?, 'open')""", (order_id, g.user["id"], issue_type, description))
    db.execute("UPDATE orders SET status='disputed' WHERE id=?", (order_id,))
    db.execute("UPDATE deliveries SET delivery_status='issue_raised' WHERE order_id=?", (order_id,))
    db.commit()
    db.close()
    flash("Issue raised. The platform admin will review evidence and resolve this dispute.", "success")
    return redirect(url_for("order_detail", order_id=order_id))


# ---------------------------------------------------------------------------
# Admin area — operates inspection, logistics, payments release oversight, disputes
# ---------------------------------------------------------------------------

@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    db = get_db()
    stats = {
        "users": db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        "sellers": db.execute("SELECT COUNT(*) c FROM users WHERE role='seller'").fetchone()["c"],
        "buyers": db.execute("SELECT COUNT(*) c FROM users WHERE role='buyer'").fetchone()["c"],
        "listings": db.execute("SELECT COUNT(*) c FROM listings WHERE status='active'").fetchone()["c"],
        "orders": db.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"],
        "completed": db.execute("SELECT COUNT(*) c FROM orders WHERE status='completed'").fetchone()["c"],
        "disputes": db.execute("SELECT COUNT(*) c FROM disputes WHERE status='open'").fetchone()["c"],
        "gmv": db.execute("SELECT COALESCE(SUM(total_amount),0) s FROM orders WHERE status='completed'").fetchone()["s"],
    }
    pending_inspections = db.execute(
        "SELECT * FROM orders WHERE status='pending_inspection' ORDER BY created_at"
    ).fetchall()
    pending_logistics = db.execute(
        "SELECT * FROM orders WHERE status='payment_held' ORDER BY created_at"
    ).fetchall()
    open_disputes = db.execute(
        """SELECT d.*, o.total_amount FROM disputes d JOIN orders o ON d.order_id=o.id
           WHERE d.status='open' ORDER BY d.created_at"""
    ).fetchall()
    db.close()
    return render_template("admin_dashboard.html", stats=stats, pending_inspections=pending_inspections,
                            pending_logistics=pending_logistics, open_disputes=open_disputes)


@app.route("/admin/orders/<int:order_id>/inspect", methods=["POST"])
@role_required("admin")
def admin_inspect(order_id):
    result = request.form["result"]
    notes = request.form.get("notes", "")
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    db.execute(
        """INSERT INTO inspections (order_id, inspector_notes, quality_verified, estimated_quantity, result)
           VALUES (?,?,?,?,?)""",
        (order_id, notes, "Verified" if result == "passed" else "Not verified", order["estimated_quantity"], result),
    )
    new_status = "inspection_passed" if result == "passed" else "inspection_failed"
    db.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
    if result != "passed":
        if order["order_type"] == "forward" and order["listing_id"]:
            db.execute("UPDATE listings SET status='active' WHERE id=?", (order["listing_id"],))
        elif order["order_type"] == "reverse" and order["request_id"]:
            db.execute("UPDATE buyer_requests SET status='open' WHERE id=?", (order["request_id"],))
            if order["reverse_bid_id"]:
                db.execute("UPDATE reverse_bids SET status='active' WHERE id=?", (order["reverse_bid_id"],))
    notify(db, order["buyer_id"], "Inspection completed",
           f"Order #{order_id} inspection result: {result}.", order_id)
    db.commit()
    db.close()
    flash(f"Inspection recorded as '{result}'.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/orders/<int:order_id>/assign-logistics", methods=["POST"])
@role_required("admin")
def admin_assign_logistics(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    db.execute("UPDATE orders SET status='logistics_assigned' WHERE id=?", (order_id,))
    db.execute("UPDATE pickups SET pickup_status='scheduled', scheduled_at=? WHERE order_id=?",
               (datetime.utcnow().isoformat(), order_id))
    notify(db, order["seller_id"], "Pickup scheduled",
           f"Logistics assigned for order #{order_id}. Pickup team will arrive soon.", order_id)
    notify(db, order["buyer_id"], "Pickup scheduled",
           f"Logistics assigned for order #{order_id}.", order_id)
    db.commit()
    db.close()
    flash("Logistics assigned and pickup scheduled.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/orders/<int:order_id>/record-pickup", methods=["POST"])
@role_required("admin")
def admin_record_pickup(order_id):
    final_weight = float(request.form["final_weight"])
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    db.execute("UPDATE pickups SET final_weight=?, pickup_status='loaded' WHERE order_id=?",
               (final_weight, order_id))
    db.execute("UPDATE orders SET final_quantity=?, status='in_transit' WHERE id=?",
               (final_weight, order_id))
    db.execute("INSERT INTO deliveries (order_id, delivery_status) VALUES (?, 'pending')", (order_id,))
    tolerance = 0.05 * order["estimated_quantity"]
    mismatch = abs(final_weight - order["estimated_quantity"]) > tolerance
    if mismatch:
        notify(db, order["buyer_id"], "Weight mismatch at pickup",
               f"Order #{order_id}: estimated {order['estimated_quantity']}, actual {final_weight}. Please review.",
               order_id)
    db.commit()
    db.close()
    flash("Pickup and final weight recorded. Shipment marked in transit."
          + (" Note: quantity mismatch exceeds tolerance — buyer notified." if mismatch else ""),
          "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/orders/<int:order_id>/mark-delivered", methods=["POST"])
@role_required("admin")
def admin_mark_delivered(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    db.execute("UPDATE deliveries SET delivery_status='delivered' WHERE order_id=?", (order_id,))
    db.execute("UPDATE orders SET status='delivered' WHERE id=?", (order_id,))
    notify(db, order["buyer_id"], "Material delivered",
           f"Order #{order_id} has been delivered. Please confirm or raise an issue.", order_id)
    db.commit()
    db.close()
    flash("Order marked as delivered. Buyer can now confirm.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/disputes/<int:dispute_id>/resolve", methods=["POST"])
@role_required("admin")
def admin_resolve_dispute(dispute_id):
    resolution = request.form["resolution"]
    responsible = request.form["responsible_party"]
    db = get_db()
    dispute = db.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
    order = db.execute("SELECT * FROM orders WHERE id=?", (dispute["order_id"],)).fetchone()

    db.execute(
        """UPDATE disputes SET status='resolved', resolution=?, responsible_party=?, resolved_at=?
           WHERE id=?""", (resolution, responsible, datetime.utcnow().isoformat(), dispute_id))

    if resolution == "refund":
        db.execute("UPDATE payments SET status='refunded', amount_refunded=amount_held WHERE order_id=?",
                   (order["id"],))
        db.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order["id"],))
    else:
        db.execute("UPDATE orders SET status='completed' WHERE id=?", (order["id"],))
        payment = db.execute("SELECT * FROM payments WHERE order_id=?", (order["id"],)).fetchone()
        db.execute("UPDATE payments SET status='released', amount_released=? WHERE order_id=?",
                   (payment["amount_held"], order["id"]))

    if responsible == "seller":
        log_reliability_change(db, order["seller_id"], -8, f"Dispute resolved against seller: {dispute['issue_type']}", order["id"])
        db.execute("UPDATE users SET disputes_count = disputes_count + 1 WHERE id=?", (order["seller_id"],))
    elif responsible == "buyer":
        log_reliability_change(db, order["buyer_id"], -5, f"Dispute resolved against buyer: {dispute['issue_type']}", order["id"])
        db.execute("UPDATE users SET disputes_count = disputes_count + 1 WHERE id=?", (order["buyer_id"],))

    notify(db, order["buyer_id"], "Dispute resolved", f"Resolution: {resolution}.", order["id"])
    notify(db, order["seller_id"], "Dispute resolved", f"Resolution: {resolution}.", order["id"])
    db.commit()
    db.close()
    flash("Dispute resolved.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users")
@role_required("admin")
def admin_users():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    db.close()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/<int:user_id>/kyc/<status>", methods=["POST"])
@role_required("admin")
def admin_set_kyc(user_id, status):
    if status not in ("verified", "rejected", "pending"):
        abort(400)
    db = get_db()
    db.execute("UPDATE users SET kyc_status=? WHERE id=?", (status, user_id))
    notify(db, user_id, "KYC status updated", f"Your KYC status is now: {status}.")
    db.commit()
    db.close()
    flash("KYC status updated.", "success")
    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@app.route("/notifications")
@login_required
def notifications():
    db = get_db()
    items = db.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (g.user["id"],)
    ).fetchall()
    db.execute("UPDATE notifications SET read_status=1 WHERE user_id=?", (g.user["id"],))
    db.commit()
    db.close()
    return render_template("notifications.html", items=items)


@app.context_processor
def inject_unread_count():
    if g.get("user"):
        db = get_db()
        count = db.execute(
            "SELECT COUNT(*) c FROM notifications WHERE user_id=? AND read_status=0", (g.user["id"],)
        ).fetchone()["c"]
        db.close()
        return {"unread_notifications": count}
    return {"unread_notifications": 0}


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        init_db()
        seed_db()
    else:
        ensure_schema()
    app.run(host="0.0.0.0", port=8000, debug=True)
