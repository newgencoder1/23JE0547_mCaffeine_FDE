"""Entry point. Production: gunicorn wsgi:app   Local: python wsgi.py"""
from dotenv import load_dotenv

load_dotenv()  # reads .env when running locally; does nothing on Render

from app import create_app  # noqa: E402  (must import after env is loaded)

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
