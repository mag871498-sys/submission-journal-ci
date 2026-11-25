import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=4, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def prepare(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY,
                submission_key TEXT UNIQUE NOT NULL,
                group_code TEXT NOT NULL
            )
        """)


def enter(path, group, key):
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            "SELECT id, group_code FROM submissions WHERE submission_key = ?", (key,)
        ).fetchone()
        if previous is None:
            number = db.execute(
                "INSERT INTO submissions (submission_key, group_code) VALUES (?, ?)", (key, group)
            ).lastrowid
            fresh, owner = True, group
        else:
            number, owner = previous
            fresh = False
        db.commit()
    return number, owner, fresh


def read(path, number):
    with connect(path) as db:
        row = db.execute(
            "SELECT id, group_code, submission_key FROM submissions WHERE id = ?", (number,)
        ).fetchone()
    return None if row is None else dict(row)
