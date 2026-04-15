import os
import sqlite3
from uuid import uuid4
from functools import wraps

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


ALLOWED_IMAGE_EXTENSIONS = {"gif", "jpeg", "jpg", "png", "webp"}


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "potluck-development-key"),
        DATABASE=os.path.join(app.instance_path, "potluck.sqlite"),
        UPLOAD_FOLDER=os.path.join(app.root_path, "static", "uploads"),
    )

    if test_config is not None:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    app.teardown_appcontext(close_db)

    @app.before_request
    def load_logged_in_user():
        user_id = session.get("user_id")
        if user_id is None:
            g.user = None
            return

        g.user = get_db().execute(
            "SELECT id, username, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    @app.route("/")
    def index():
        recipes = get_db().execute(
            """
            SELECT
                recipes.id,
                recipes.title,
                recipes.description,
                recipes.thumbnail_filename,
                recipes.created_at,
                users.username,
                COUNT(comments.id) AS comment_count
            FROM recipes
            JOIN users ON recipes.user_id = users.id
            LEFT JOIN comments ON comments.recipe_id = recipes.id
            GROUP BY recipes.id
            ORDER BY recipes.created_at DESC, recipes.id DESC
            """
        ).fetchall()
        return render_template("index.html", recipes=recipes)

    @app.route("/register", methods=("GET", "POST"))
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            error = None

            if not username:
                error = "Username is required."
            elif len(username) < 3:
                error = "Username must be at least 3 characters long."
            elif not password:
                error = "Password is required."
            elif len(password) < 6:
                error = "Password must be at least 6 characters long."
            elif password != confirm_password:
                error = "Passwords do not match."

            db = get_db()
            if error is None:
                existing_user = db.execute(
                    "SELECT id FROM users WHERE username = ?",
                    (username,),
                ).fetchone()
                if existing_user is not None:
                    error = "That username is already taken."

            if error is None:
                db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                db.commit()
                flash("Registration complete. Please log in.")
                return redirect(url_for("login"))

            flash(error)

        return render_template("register.html")

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            error = "Incorrect username or password."

            user = get_db().execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            ).fetchone()

            if user is not None and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["id"]
                flash("You are now logged in.")
                return redirect(url_for("index"))

            flash(error)

        return render_template("login.html")

    @app.get("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.")
        return redirect(url_for("index"))

    @app.route("/recipes/new", methods=("GET", "POST"))
    @login_required
    def create_recipe():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            thumbnail_file = request.files.get("thumbnail")
            error = None

            if not title:
                error = "Recipe title is required."
            elif not description:
                error = "A short description is required."

            thumbnail_filename = None
            if error is None:
                thumbnail_filename, error = save_thumbnail(thumbnail_file)

            if error is None:
                db = get_db()
                cursor = db.execute(
                    """
                    INSERT INTO recipes (user_id, title, description, thumbnail_filename)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        g.user["id"],
                        title,
                        description,
                        thumbnail_filename,
                    ),
                )
                db.commit()
                flash("Recipe posted.")
                return redirect(url_for("recipe_detail", recipe_id=cursor.lastrowid))

            flash(error)

        return render_template("new_recipe.html")

    @app.route("/recipes/<int:recipe_id>")
    def recipe_detail(recipe_id):
        recipe = get_recipe(recipe_id)
        comments = get_db().execute(
            """
            SELECT comments.id, comments.body, comments.created_at, users.username
            FROM comments
            JOIN users ON comments.user_id = users.id
            WHERE comments.recipe_id = ?
            ORDER BY comments.created_at ASC, comments.id ASC
            """,
            (recipe_id,),
        ).fetchall()
        return render_template("recipe_detail.html", recipe=recipe, comments=comments)

    @app.route("/recipes/<int:recipe_id>/edit", methods=("GET", "POST"))
    @login_required
    def edit_recipe(recipe_id):
        recipe = get_recipe(recipe_id, require_author=True)

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            thumbnail_file = request.files.get("thumbnail")
            error = None

            if not title:
                error = "Recipe title is required."
            elif not description:
                error = "A short description is required."

            thumbnail_filename = recipe["thumbnail_filename"]
            old_thumbnail_filename = recipe["thumbnail_filename"]
            if error is None and thumbnail_file and thumbnail_file.filename:
                thumbnail_filename, error = save_thumbnail(thumbnail_file)

            if error is None:
                db = get_db()
                db.execute(
                    """
                    UPDATE recipes
                    SET title = ?, description = ?, thumbnail_filename = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        description,
                        thumbnail_filename,
                        recipe_id,
                    ),
                )
                db.commit()
                if thumbnail_filename != old_thumbnail_filename:
                    delete_thumbnail(old_thumbnail_filename)
                flash("Recipe updated.")
                return redirect(url_for("recipe_detail", recipe_id=recipe_id))

            flash(error)

        return render_template("edit_recipe.html", recipe=recipe)

    @app.post("/recipes/<int:recipe_id>/delete")
    @login_required
    def delete_recipe(recipe_id):
        recipe = get_recipe(recipe_id, require_author=True)
        db = get_db()
        db.execute("DELETE FROM comments WHERE recipe_id = ?", (recipe_id,))
        db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
        db.commit()
        delete_thumbnail(recipe["thumbnail_filename"])
        flash("Recipe deleted.")
        return redirect(url_for("index"))

    @app.post("/recipes/<int:recipe_id>/comments")
    @login_required
    def add_comment(recipe_id):
        get_recipe(recipe_id)
        body = request.form.get("body", "").strip()

        if not body:
            flash("Comment text is required.")
            return redirect(url_for("recipe_detail", recipe_id=recipe_id))

        db = get_db()
        db.execute(
            "INSERT INTO comments (recipe_id, user_id, body) VALUES (?, ?, ?)",
            (recipe_id, g.user["id"], body),
        )
        db.commit()
        flash("Comment added.")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))

    @app.cli.command("init-db")
    def init_db_command():
        init_db()
        print("Initialized the potluck database.")

    with app.app_context():
        init_db()

    return app


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")

    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as schema_file:
        db.executescript(schema_file.read().decode("utf-8"))
    migrate_recipe_table(db)
    db.commit()


def migrate_recipe_table(db):
    recipe_columns = [
        column["name"] for column in db.execute("PRAGMA table_info(recipes)").fetchall()
    ]
    expected_columns = [
        "id",
        "user_id",
        "title",
        "description",
        "thumbnail_filename",
        "created_at",
    ]

    if recipe_columns == expected_columns:
        return

    db.execute("PRAGMA foreign_keys = OFF")
    db.execute(
        """
        CREATE TABLE recipes_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            thumbnail_filename TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        INSERT INTO recipes_new (id, user_id, title, description, thumbnail_filename, created_at)
        SELECT id, user_id, title, description, thumbnail_filename, created_at
        FROM recipes
        """
    )
    db.execute("DROP TABLE recipes")
    db.execute("ALTER TABLE recipes_new RENAME TO recipes")
    db.execute("PRAGMA foreign_keys = ON")


def get_recipe(recipe_id, require_author=False):
    recipe = get_db().execute(
        """
        SELECT recipes.*, users.username
        FROM recipes
        JOIN users ON recipes.user_id = users.id
        WHERE recipes.id = ?
        """,
        (recipe_id,),
    ).fetchone()

    if recipe is None:
        abort(404)

    if require_author and g.user["id"] != recipe["user_id"]:
        abort(403)

    return recipe


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.get("user") is None:
            flash("Please log in first.")
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def save_thumbnail(thumbnail_file):
    if thumbnail_file is None or not thumbnail_file.filename:
        return None, None

    original_name = secure_filename(thumbnail_file.filename)
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return None, "Thumbnail must be a GIF, JPG, JPEG, PNG, or WEBP image."

    filename = f"{uuid4().hex}.{extension}"
    thumbnail_file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
    return filename, None


def delete_thumbnail(filename):
    if not filename:
        return

    thumbnail_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    try:
        os.remove(thumbnail_path)
    except FileNotFoundError:
        pass


app = create_app()
