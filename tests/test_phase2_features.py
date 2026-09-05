import pytest
from database import get_db

def login(client, email, password):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)

def test_market_intelligence_page(client):
    res = client.get('/market-intelligence')
    assert res.status_code == 200
    assert b"Market Intelligence" in res.data
    assert b"Copper" in res.data
    assert b"Benchmark" in res.data

def test_trade_passport_page(client):
    # Ramesh is user ID 2 (seller)
    res = client.get('/trade-passport/2')
    assert res.status_code == 200
    assert b"Trade Passport" in res.data
    assert b"KYC Verified" in res.data
    assert b"Trust Grade" in res.data

def test_seller_deposit_vault(client, app):
    login(client, 'ramesh@scrap.in', 'password123')
    res = client.get('/seller/deposit')
    assert res.status_code == 200
    assert b"Security Deposit" in res.data
    assert b"Escrow Security Account" in res.data
    
    # Test top-up
    top_res = client.post('/seller/deposit', data={'amount': '5000'}, follow_redirects=True)
    assert top_res.status_code == 200
    assert b"deposited successfully" in top_res.data

def test_counter_bid_flow(client, app):
    # Buyer bids on Ramesh's listing
    login(client, 'suresh@buyer.in', 'password123')
    bid_res = client.post('/listings/1', data={'bid_price': '400', 'quantity': '10', 'message': 'Offering 400'}, follow_redirects=True)
    assert bid_res.status_code == 200

    # Retrieve created bid ID from DB
    with app.app_context():
        db = get_db()
        bid = db.execute("SELECT id FROM bids WHERE listing_id = 1 AND buyer_id = 4 ORDER BY id DESC LIMIT 1").fetchone()
        assert bid is not None
        bid_id = bid['id']

    # Seller logs in and submits counter-offer
    login(client, 'ramesh@scrap.in', 'password123')
    counter_res = client.post(f'/seller/listings/1/counter-bid/{bid_id}', data={
        'counter_price': '430',
        'counter_message': 'Best I can do is 430/kg'
    }, follow_redirects=True)
    assert counter_res.status_code == 200

    # Buyer logs in and accepts counter-offer
    login(client, 'suresh@buyer.in', 'password123')
    dash = client.get('/buyer/dashboard')
    assert b"Seller Counter-Offers Requiring Your Review" in dash.data
    assert b"Best I can do is 430/kg" in dash.data

    accept_res = client.post(f'/buyer/bids/{bid_id}/accept-counter', follow_redirects=True)
    assert accept_res.status_code == 200
    assert b"Order #" in accept_res.data
