import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
  number TEXT PRIMARY KEY,
  issue_date TEXT NOT NULL,
  data TEXT NOT NULL,
  email_uid TEXT,
  imported_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS seen_mail (
  uid TEXT PRIMARY KEY,
  status TEXT,
  note TEXT
);
"""


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def has_invoice(self, number: str) -> bool:
        return self.db.execute("SELECT 1 FROM invoices WHERE number=?", (number,)).fetchone() is not None

    def add_invoice(self, inv: dict, uid: str | None) -> bool:
        if self.has_invoice(inv["number"]):
            return False
        self.db.execute(
            "INSERT INTO invoices(number, issue_date, data, email_uid) VALUES (?,?,?,?)",
            (inv["number"], inv["issue_date"], json.dumps(inv, ensure_ascii=False), uid),
        )
        self.db.commit()
        return True

    def invoices(self) -> list[dict]:
        rows = self.db.execute("SELECT data FROM invoices ORDER BY issue_date, number").fetchall()
        return [json.loads(r[0]) for r in rows]

    def mail_seen(self, uid: str) -> bool:
        return self.db.execute("SELECT 1 FROM seen_mail WHERE uid=?", (uid,)).fetchone() is not None

    def mark_mail(self, uid: str, status: str, note: str = ""):
        self.db.execute("INSERT OR REPLACE INTO seen_mail(uid,status,note) VALUES (?,?,?)", (uid, status, note))
        self.db.commit()
