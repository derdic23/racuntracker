FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY cli.py wsgi.py ./

ENV DATA_DIR=/app/data PYTHONUNBUFFERED=1
# Owner of ./data on the host (the first user on Ubuntu)
USER 1000:1000
EXPOSE 5000
# One worker: the background mail check runs once per process
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120", "--no-control-socket", "wsgi:app"]
