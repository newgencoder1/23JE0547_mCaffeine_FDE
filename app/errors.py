"""Friendly errors for users, detailed timestamped logs for engineers.

* ApiError is raised by our own code for expected refusals (401/403/404/409/422).
* Anything unexpected becomes a generic 500 with a short reference id. The full
  stack trace goes to the log (visible in the host's log viewer) — never to the user.
"""
from flask import g, jsonify, request
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, status, message, fields=None, extra=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.fields = fields or {}
        self.extra = extra or {}


def _payload(status, message, fields=None, extra=None):
    body = {"error": message, "request_id": g.get("request_id")}
    if fields:
        body["fields"] = fields
    if extra:
        body.update(extra)
    return jsonify(body), status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(err):
        # Expected refusals are logged at INFO so the Monday-morning debug is easy:
        # "who got refused, on which PO, and why".
        app.logger.info(
            "refused %s %s -> %s: %s", request.method, request.path, err.status, err.message
        )
        return _payload(err.status, err.message, err.fields, err.extra)

    @app.errorhandler(413)
    def handle_too_large(_err):
        return _payload(413, "That file is larger than 5 MB. Please upload a smaller PDF.")

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        messages = {
            404: "Not found.",
            405: "That action is not allowed on this address.",
        }
        return _payload(err.code, messages.get(err.code, err.name))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # logger.exception records the full stack trace in the server log only.
        app.logger.exception("unhandled error on %s %s", request.method, request.path)
        return _payload(
            500,
            "Something went wrong on our side. Please try again; if it keeps happening, "
            "share this reference with the support team.",
        )
