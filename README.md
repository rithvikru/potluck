# Tramazing Potluck

A plain old-school Flask website for neighborhood potlucks. People can register, log in, post recipes with optional thumbnails, edit or delete their own recipes, browse every recipe, and leave comments on each dish.

## Features

- User registration and login
- Password hashing with Werkzeug
- SQLite database storage
- Recipe posting, editing, viewing, and deletion
- Comments on recipe pages
- Minimal retro-style presentation using Times New Roman and simple HTML tables

## Run It

```bash
uv sync
uv run python main.py
```

Then open `http://127.0.0.1:5000`.

## Useful Commands

```bash
uv run pytest
uv run flask --app app init-db
```
