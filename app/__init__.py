"""Flask app factory. Run: `flask --app app run`"""
import hmac
import secrets
from datetime import timedelta

from flask import Flask, abort, redirect, request, session, url_for

from . import config

PUBLIC_ENDPOINTS = {"auth.login", "static"}


def create_app(**overrides) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=config.SECRET_KEY,
        APP_PASSWORD=config.APP_PASSWORD,
        DB_PATH=config.DB_PATH,
        PDF_DIR=config.PDF_DIR,
        GMAIL_LABEL=config.GMAIL_LABEL,
        MAX_AMOUNT=config.MAX_AMOUNT,
        ENV_PATH=config.ENV_PATH,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # "Zapamti me"; renewed on every request, so it expires after 90 days without use
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
    )
    app.config.update(overrides)
    if not (app.config["SECRET_KEY"] and app.config["APP_PASSWORD"]):
        raise RuntimeError("Podesi SECRET_KEY i APP_PASSWORD u .env")

    from .routes import auth, bills, settings
    app.register_blueprint(auth.bp)
    app.register_blueprint(bills.bp)
    app.register_blueprint(settings.bp)
    app.teardown_appcontext(bills.close_db)
    app.jinja_env.filters.update(rsd=bills.format_rsd, dmy=bills.format_date, dmyhm=bills.format_datetime, account=bills.format_account)

    @app.context_processor
    def csrf():
        def csrf_token() -> str:
            return session.setdefault("csrf", secrets.token_urlsafe(32))
        return {"csrf_token": csrf_token}

    @app.before_request
    def guard():
        if request.method == "POST":
            sent = request.form.get("csrf", "")
            if not sent or not hmac.compare_digest(sent.encode(), session.get("csrf", "").encode()):
                abort(400)
        if request.endpoint not in PUBLIC_ENDPOINTS and not session.get("logged_in"):
            return redirect(url_for("auth.login"))

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return app
