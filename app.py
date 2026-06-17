# rack·list — Server Inventory
# Maintainer: Alfio Salanitri <https://www.alfiosalanitri.it>
# License: MIT

import os
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, abort
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-key-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(DATA_DIR, "inventory.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Admin credentials — set via environment variables or docker-compose
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = generate_password_hash(os.environ.get("ADMIN_PASSWORD", "admin"))

db = SQLAlchemy(app)

STATUSES = {
    "online": "Online",
    "maintenance": "Maintenance",
    "offline": "Offline",
    "decommissioned": "Decommissioned",
}


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
class Server(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    ip_address = db.Column(db.String(64), nullable=False)
    os_version = db.Column(db.String(120), default="")
    client = db.Column(db.String(120), default="")
    role = db.Column(db.String(120), default="")
    location = db.Column(db.String(120), default="")
    provider = db.Column(db.String(120), default="")
    ssh_port = db.Column(db.String(16), default="")
    status = db.Column(db.String(32), default="online")
    description = db.Column(db.Text, default="")
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def status_label(self):
        return STATUSES.get(self.status, self.status)


with app.app_context():
    db.create_all()


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            flash("Log in to manage servers.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    return {
        "logged_in": session.get("logged_in", False),
        "statuses": STATUSES,
        "current_year": datetime.utcnow().year,
    }


# --------------------------------------------------------------------------- #
# Public routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()

    query = Server.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Server.name.ilike(like),
                Server.ip_address.ilike(like),
                Server.client.ilike(like),
                Server.os_version.ilike(like),
                Server.role.ilike(like),
                Server.location.ilike(like),
                Server.description.ilike(like),
            )
        )
    if status in STATUSES:
        query = query.filter(Server.status == status)

    servers = query.order_by(Server.name.asc()).all()

    counts = {key: Server.query.filter_by(status=key).count() for key in STATUSES}
    counts["total"] = Server.query.count()

    return render_template(
        "index.html",
        servers=servers,
        q=q,
        active_status=status,
        counts=counts,
    )


# --------------------------------------------------------------------------- #
# Login / logout
# --------------------------------------------------------------------------- #
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("admin"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["logged_in"] = True
            session["username"] = username
            flash("Logged in.", "success")
            nxt = request.args.get("next", "")
            # Guard against open-redirect: only allow relative paths on this host
            if not nxt or not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("admin")
            return redirect(nxt)
        flash("Invalid credentials.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------- #
# Admin area: list + CRUD
# --------------------------------------------------------------------------- #
@app.route("/admin")
@login_required
def admin():
    servers = Server.query.order_by(Server.name.asc()).all()
    return render_template("admin.html", servers=servers)


def _read_form(server):
    """Populate a Server object from form data. Returns a list of validation errors."""
    errors = []
    server.name = request.form.get("name", "").strip()
    server.ip_address = request.form.get("ip_address", "").strip()
    server.os_version = request.form.get("os_version", "").strip()
    server.client = request.form.get("client", "").strip()
    server.role = request.form.get("role", "").strip()
    server.location = request.form.get("location", "").strip()
    server.provider = request.form.get("provider", "").strip()
    server.ssh_port = request.form.get("ssh_port", "").strip()
    server.status = request.form.get("status", "online").strip()
    server.description = request.form.get("description", "").strip()
    server.notes = request.form.get("notes", "").strip()

    if not server.name:
        errors.append("Server name is required.")
    if not server.ip_address:
        errors.append("IP address is required.")
    if server.status not in STATUSES:
        server.status = "online"
    return errors


@app.route("/admin/new", methods=["GET", "POST"])
@login_required
def server_new():
    server = Server()
    if request.method == "POST":
        errors = _read_form(server)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("server_form.html", server=server, mode="new")
        db.session.add(server)
        db.session.commit()
        flash(f"Server '{server.name}' added.", "success")
        return redirect(url_for("admin"))
    return render_template("server_form.html", server=server, mode="new")


@app.route("/admin/<int:server_id>/edit", methods=["GET", "POST"])
@login_required
def server_edit(server_id):
    server = db.session.get(Server, server_id)
    if server is None:
        abort(404)
    if request.method == "POST":
        errors = _read_form(server)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("server_form.html", server=server, mode="edit")
        db.session.commit()
        flash(f"Server '{server.name}' updated.", "success")
        return redirect(url_for("admin"))
    return render_template("server_form.html", server=server, mode="edit")


@app.route("/admin/<int:server_id>/delete", methods=["POST"])
@login_required
def server_delete(server_id):
    server = db.session.get(Server, server_id)
    if server is None:
        abort(404)
    name = server.name
    db.session.delete(server)
    db.session.commit()
    flash(f"Server '{name}' deleted.", "success")
    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
