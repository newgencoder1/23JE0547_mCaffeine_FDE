"""Serves the three HTML pages. They are static files; all data and all rules
come from the JSON API, so hiding a button in the UI is never the protection."""
from flask import Blueprint, current_app

bp = Blueprint("pages", __name__)


def _page(name):
    return current_app.send_static_file(name)


@bp.get("/")
def index():
    return _page("index.html")


@bp.get("/login")
def login_page():
    return _page("login.html")


@bp.get("/po/<int:po_id>")
def po_page(po_id):  # po_id is read by po.js from the URL
    return _page("po.html")
