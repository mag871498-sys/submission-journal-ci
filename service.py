import json
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

from flask import Flask, Response, g, request
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, generate_latest

import ledger
from release import VERSION, acknowledgement

GROUP = re.compile(r"SE-[0-9]{2}")


def create_app():
    app = Flask(__name__)
    database = os.getenv("SUBMIT_DB", "journal.sqlite")
    mode = os.getenv("CONFIRM_MODE", "normal")
    ledger.prepare(database)
    registry = CollectorRegistry()
    metric = Counter(
        "submission_responses_total", "Final responses to POST submissions",
        ("version", "status"), registry=registry,
    )

    def journal(event, status):
        entry = dict(
            time=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            version=VERSION, request_id=g.trace, event=event, status=status,
        )
        if g.number is not None:
            entry["submission_id"] = g.number
        print(json.dumps(entry, separators=(",", ":")), flush=True)

    @app.before_request
    def attach_trace():
        g.trace, g.number = uuid4().hex, None

    @app.after_request
    def finish(response):
        response.headers["X-Request-Id"] = g.trace
        if request.endpoint == "add_submission" and request.method == "POST":
            metric.labels(VERSION, str(response.status_code)).inc()
            journal("submission_response", response.status_code)
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "version": VERSION}

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)

    @app.post("/submissions")
    def add_submission():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return {"error": "A JSON object is required"}, 400
        group = body.get("group_code")
        key = body.get("submission_key")
        if not isinstance(group, str) or not GROUP.fullmatch(group):
            return {"error": "Expected SE- followed by two digits"}, 400
        if not isinstance(key, str) or not key.strip() or len(key) > 64:
            return {"error": "Use a non-empty submission key of up to 64 characters"}, 400
        number, owner, fresh = ledger.enter(database, group, key)
        g.number = number
        if owner != group:
            return {"error": "Group does not match this submission"}, 409
        if not fresh:
            return {"id": number}, 200
        journal("submission_saved", 201)

        result, status = acknowledgement(number, key, mode)
        if status == 503:
            journal("confirmation_failed", status)
        elif "confirmation" in result:
            journal("confirmation_sent", status)
        return result, status

    @app.get("/submissions/<int:number>")
    def get_submission(number):
        record = ledger.read(database, number)
        if record is None:
            return {"error": "No submission with that id"}, 404
        return record

    return app
