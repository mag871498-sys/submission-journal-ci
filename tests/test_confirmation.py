import json
import sqlite3

from service import create_app


def test_normal_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBMIT_DB", str(tmp_path / "journal.sqlite"))
    monkeypatch.setenv("CONFIRM_MODE", "normal")
    client = create_app().test_client()
    result = client.post("/submissions", json={"group_code": "SE-17", "submission_key": "first-ref"})
    assert result.status_code == 201
    assert len(result.json["confirmation"]) == 12


def test_offline_confirmation_does_not_undo_insert(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "journal.sqlite"
    monkeypatch.setenv("SUBMIT_DB", str(db_path))
    monkeypatch.setenv("CONFIRM_MODE", "offline")
    client = create_app().test_client()
    payload = {"group_code": "SE-17", "submission_key": "keep-after-error"}
    result = client.post("/submissions", json=payload)
    assert result.status_code == 503
    number = result.json["id"]

    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [log["event"] for log in logs] == [
        "submission_saved", "confirmation_failed", "submission_response",
    ]
    assert {log["request_id"] for log in logs} == {result.headers["X-Request-Id"]}
    assert client.get("/health").status_code == 200
    assert client.get(f"/submissions/{number}").json == {"id": number, **payload}
    repeat = client.post("/submissions", json=payload)
    assert (repeat.status_code, repeat.json) == (200, {"id": number})
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT id FROM submissions").fetchall() == [(number,)]
