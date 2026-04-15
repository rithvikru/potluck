import io
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app


@pytest.fixture
def app(tmp_path: Path):
    database_path = tmp_path / "test-potluck.sqlite"
    upload_folder = tmp_path / "uploads"
    flask_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-key",
            "DATABASE": str(database_path),
            "UPLOAD_FOLDER": str(upload_folder),
        }
    )
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, username="alice", password="secret123"):
    return client.post(
        "/register",
        data={
            "username": username,
            "password": password,
            "confirm_password": password,
        },
        follow_redirects=True,
    )


def login(client, username="alice", password="secret123"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def test_homepage_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Tramazing Potluck" in response.data


def test_register_login_post_and_comment_flow(client):
    register_response = register(client)
    assert b"Registration complete" in register_response.data

    login_response = login(client)
    assert b"You are now logged in." in login_response.data

    create_response = client.post(
        "/recipes/new",
        data={
            "title": "Church Basement Chili",
            "description": "A hearty chili for the whole block.",
            "thumbnail": (io.BytesIO(b"fake image bytes"), "chili.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Recipe posted." in create_response.data
    assert b"Church Basement Chili" in create_response.data
    assert b"uploads/" in create_response.data

    comment_response = client.post(
        "/recipes/1/comments",
        data={"body": "Making this for Saturday night."},
        follow_redirects=True,
    )
    assert b"Comment added." in comment_response.data
    assert b"Making this for Saturday night." in comment_response.data


def test_recipe_owner_can_edit_and_delete(client):
    register(client, username="cook")
    login(client, username="cook")

    client.post(
        "/recipes/new",
        data={
            "title": "Potato Salad",
            "description": "Classic picnic side dish.",
        },
        follow_redirects=True,
    )

    edit_response = client.post(
        "/recipes/1/edit",
        data={
            "title": "Potato Salad Deluxe",
            "description": "Classic picnic side dish with more flavor.",
            "thumbnail": (io.BytesIO(b"more fake image bytes"), "potato-salad.gif"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Recipe updated." in edit_response.data
    assert b"Potato Salad Deluxe" in edit_response.data
    assert b"uploads/" in edit_response.data

    delete_response = client.post("/recipes/1/delete", follow_redirects=True)
    assert b"Recipe deleted." in delete_response.data
    assert b"Potato Salad Deluxe" not in delete_response.data


def test_existing_database_drops_recipe_text_fields(tmp_path: Path):
    database_path = tmp_path / "legacy.sqlite"
    upload_folder = tmp_path / "uploads"
    legacy_db = sqlite3.connect(database_path)
    legacy_db.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            ingredients TEXT NOT NULL DEFAULT '',
            instructions TEXT NOT NULL DEFAULT '',
            thumbnail_filename TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );

        CREATE TABLE comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (recipe_id) REFERENCES recipes (id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
        """
    )
    legacy_db.commit()
    legacy_db.close()

    migrated_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-key",
            "DATABASE": str(database_path),
            "UPLOAD_FOLDER": str(upload_folder),
        }
    )

    with migrated_app.app_context():
        db = sqlite3.connect(database_path)
        db.row_factory = sqlite3.Row
        recipe_columns = [
            column["name"] for column in db.execute("PRAGMA table_info(recipes)").fetchall()
        ]
        db.close()

    assert recipe_columns == [
        "id",
        "user_id",
        "title",
        "description",
        "thumbnail_filename",
        "created_at",
    ]
