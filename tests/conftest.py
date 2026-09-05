import os
import sys
import tempfile
import pytest

# Ensure app directory is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app as flask_app
import database


@pytest.fixture
def app():
    # Create a temporary database for isolation
    db_fd, db_path = tempfile.mkstemp()
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret-key"
    database.DB_PATH = db_path
    
    with flask_app.app_context():
        database.init_db()
        database.seed_db()
        database.ensure_schema()
        
    yield flask_app
    
    os.close(db_fd)
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()
