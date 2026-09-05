import pytest
from unittest.mock import patch
from database import get_db


def test_google_auth_redirect_when_credentials_present(client, monkeypatch):
    """Test that /auth/google redirects to Google OAuth endpoint when client ID and Secret are configured."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id-123.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret-xyz")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    
    response = client.get("/auth/google")
    assert response.status_code == 302
    redirect_url = response.headers["Location"]
    assert "accounts.google.com/o/oauth2/v2/auth" in redirect_url
    assert "client_id=test-client-id-123" in redirect_url
    assert "scope=openid+email+profile" in redirect_url or "scope=openid%20email%20profile" in redirect_url
    assert "state=" in redirect_url


def test_google_callback_access_denied(client):
    """Test handling user cancellation on Google consent screen."""
    with client.session_transaction() as sess:
        sess["oauth_state"] = "valid_state_123"

    response = client.get(
        "/auth/google/callback?error=access_denied&state=valid_state_123",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Google sign-in was cancelled" in response.data


def test_google_callback_csrf_state_mismatch(client):
    """Test CSRF protection rejection when state does not match."""
    with client.session_transaction() as sess:
        sess["oauth_state"] = "expected_state_abc"

    response = client.get(
        "/auth/google/callback?code=mock_code_123&state=tampered_state_xyz",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"security verification failed" in response.data or b"expired" in response.data


def test_google_callback_success_existing_user(client):
    """Test successful OAuth callback for an existing user."""
    with client.session_transaction() as sess:
        sess["oauth_state"] = "valid_test_state_100"

    mock_profile = {
        "email": "ramesh@scrap.in",
        "name": "Ramesh Traders",
        "sub": "google_sub_ramesh_123",
        "picture": "https://lh3.googleusercontent.com/a/test-avatar",
    }

    with patch("app.exchange_google_code_for_user", return_value=(mock_profile, None)):
        response = client.get(
            "/auth/google/callback?code=valid_auth_code&state=valid_test_state_100",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Welcome back, Ramesh Traders! Signed in with Google." in response.data or b"Ramesh" in response.data

    # Verify session persisted
    dash_response = client.get("/dashboard")
    assert dash_response.status_code == 302  # redirects to /seller/dashboard
    seller_dash = client.get("/seller/dashboard")
    assert seller_dash.status_code == 200
    assert b"Seller Control Center" in seller_dash.data or b"Ramesh" in seller_dash.data


def test_google_callback_success_new_user_onboarding(client):
    """Test successful OAuth callback for a new user, requiring role onboarding."""
    with client.session_transaction() as sess:
        sess["oauth_state"] = "valid_test_state_200"

    mock_profile = {
        "email": "new.buyer.google@example.com",
        "name": "Pooja Sharma",
        "sub": "google_sub_pooja_888",
        "picture": "https://lh3.googleusercontent.com/a/pooja-avatar",
    }

    with patch("app.exchange_google_code_for_user", return_value=(mock_profile, None)):
        response = client.get(
            "/auth/google/callback?code=valid_auth_code_new&state=valid_test_state_200",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Almost there, Pooja Sharma" in response.data

    # Complete role selection form
    reg_response = client.post(
        "/auth/google/select-role",
        data={
            "role": "buyer",
            "business_name": "Sharma Metal Refining",
            "location": "Ahmedabad, GJ",
            "phone": "9825001122",
        },
        follow_redirects=True,
    )
    assert reg_response.status_code == 200
    assert b"Welcome to ScrapTrade, Pooja Sharma!" in reg_response.data

    # Verify user record in database
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email='new.buyer.google@example.com'").fetchone()
    assert user is not None
    assert user["role"] == "buyer"
    assert user["google_id"] == "google_sub_pooja_888"
    assert user["avatar_url"] == "https://lh3.googleusercontent.com/a/pooja-avatar"
    assert user["kyc_status"] == "verified"
    db.close()

    # Verify dashboard access
    buyer_dash = client.get("/buyer/dashboard")
    assert buyer_dash.status_code == 200
    assert b"Sharma Metal Refining" in buyer_dash.data or b"Pooja Sharma" in buyer_dash.data

    # Verify logout
    logout_res = client.get("/logout", follow_redirects=True)
    assert logout_res.status_code == 200
    assert b"logged out" in logout_res.data

    # Verify protected route blocks unauthenticated access
    protected_res = client.get("/dashboard", follow_redirects=True)
    assert protected_res.status_code == 200
    assert b"Please log in to continue" in protected_res.data
