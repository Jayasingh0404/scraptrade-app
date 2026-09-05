import pytest
from database import get_db


def test_index_page(client):
    """Test that public home page renders and returns 200."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"ScrapTrade" in response.data or b"Scrap" in response.data


def test_login_success(client):
    """Test standard login for seller."""
    response = client.post(
        "/login",
        data={"email": "ramesh@scrap.in", "password": "password123"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Welcome back" in response.data or b"Ramesh" in response.data


def test_login_invalid_credentials(client):
    """Test login with wrong password."""
    response = client.post(
        "/login",
        data={"email": "ramesh@scrap.in", "password": "wrongpassword"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_forgot_password_flow(client):
    """Test complete forgot password and reset token flow."""
    # 1. Request reset link
    response = client.post(
        "/forgot-password",
        data={"email": "suresh@buyer.in"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Password reset link generated" in response.data

    # Extract generated token from database
    db = get_db()
    reset_entry = db.execute(
        "SELECT * FROM password_resets WHERE email='suresh@buyer.in' AND used=0 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert reset_entry is not None
    token = reset_entry["token"]
    db.close()

    # 2. Open reset page
    response = client.get(f"/reset-password/{token}")
    assert response.status_code == 200
    assert b"Set New Password" in response.data

    # 3. Submit new password
    response = client.post(
        f"/reset-password/{token}",
        data={"password": "newpassword123", "confirm_password": "newpassword123"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"successfully reset" in response.data

    # 4. Verify login with new password
    login_res = client.post(
        "/login",
        data={"email": "suresh@buyer.in", "password": "newpassword123"},
        follow_redirects=True,
    )
    assert login_res.status_code == 200
    assert b"Welcome back" in login_res.data or b"Suresh" in login_res.data


def test_google_mock_sign_in_existing_user(client):
    """Test Google sign-in linking to existing account."""
    response = client.post(
        "/auth/google/mock-login",
        data={
            "email": "ramesh@scrap.in",
            "full_name": "Ramesh Traders",
            "google_id": "goog_test_12345",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Signed in with Google" in response.data


def test_google_mock_sign_in_new_user_role_select(client):
    """Test Google sign-in for new user with role selection."""
    # Step 1: Trigger Google sign in
    response = client.post(
        "/auth/google/mock-login",
        data={
            "email": "new.buyer@gmail.com",
            "full_name": "New Google Buyer",
            "google_id": "goog_new_user_999",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Almost there" in response.data or b"role" in response.data.decode("utf-8").lower()

    # Step 2: Complete role selection
    reg_response = client.post(
        "/auth/google/select-role",
        data={
            "role": "buyer",
            "business_name": "Google Eco Buyers",
            "location": "Bengaluru, KA",
            "phone": "9988776655",
        },
        follow_redirects=True,
    )
    assert reg_response.status_code == 200
    assert b"Welcome to ScrapTrade" in reg_response.data


def test_seller_create_listing_and_buyer_bid(client):
    """Test listing creation by seller and bidding by buyer."""
    # Log in as seller
    client.post("/login", data={"email": "ramesh@scrap.in", "password": "password123"})
    
    # Create listing
    create_res = client.post(
        "/seller/listings/new",
        data={
            "material_type": "Brass Scrap",
            "category": "Metal",
            "grade": "Honey Grade",
            "estimated_quantity": "250",
            "unit": "kg",
            "expected_price": "450",
            "location": "Pune, MH",
            "description": "Clean brass valves and fittings",
        },
        follow_redirects=True,
    )
    assert create_res.status_code == 200
    assert b"Listing published" in create_res.data or b"Brass Scrap" in create_res.data

    # Log in as buyer and place bid
    client.get("/logout")
    client.post("/login", data={"email": "suresh@buyer.in", "password": "password123"})
    
    db = get_db()
    listing = db.execute("SELECT id FROM listings WHERE material_type='Brass Scrap'").fetchone()
    listing_id = listing["id"]
    db.close()

    bid_res = client.post(
        f"/listings/{listing_id}",
        data={"bid_price": "460", "quantity": "250", "message": "Ready to buy immediately"},
        follow_redirects=True,
    )
    assert bid_res.status_code == 200
    assert b"submitted" in bid_res.data
