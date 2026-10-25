import hmac

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

bp = Blueprint("auth", __name__)


@bp.route("/prijava", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "").encode()
        if hmac.compare_digest(password, current_app.config["APP_PASSWORD"].encode()):
            session.clear()  # new session, new CSRF token
            session.permanent = True
            session["logged_in"] = True
            return redirect(url_for("bills.index"))
        error = "Pogrešna lozinka."
    return render_template("login.html", error=error), 401 if error else 200


@bp.post("/odjava")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
