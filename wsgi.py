"""Server entry point with the background mail check: `gunicorn --workers 1 wsgi:app`"""
from app import create_app, scheduler

app = create_app()
scheduler.start(app)
