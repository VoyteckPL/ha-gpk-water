import json
import os
import re
import sqlite3

PDF_DIR = "/data/pdfs"


def pdf_path(number: str) -> str:
    return os.path.join(PDF_DIR, re.sub(r"[^\w.\-]", "_", number) + ".pdf")

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
        self.db = sqlite3.connect(path, check_same_thread=False)
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
        return self.db.execute("SELECT 1 FROM seen_mail WHERE uid=? AND status IN ('ok','no_pdf','not_invoice')", (uid,)).fetchone() is not None

    def mark_mail(self, uid: str, status: str, note: str = ""):
        self.db.execute("INSERT OR REPLACE INTO seen_mail(uid,status,note) VALUES (?,?,?)", (uid, status, note))
        self.db.commit()

    def save_pdf(self, number: str, payload: bytes):
        os.makedirs(PDF_DIR, exist_ok=True)
        with open(pdf_path(number), "wb") as f:
            f.write(payload)

    def failed_mails(self) -> list[dict]:
        rows = self.db.execute("SELECT uid, note FROM seen_mail WHERE status='failed'").fetchall()
        return [dict(uid=r[0], note=r[1]) for r in rows]

    def invoices_missing_pdf(self) -> list[tuple[str, str]]:
        rows = self.db.execute("SELECT number, email_uid FROM invoices WHERE email_uid IS NOT NULL").fetchall()
        return [(n, u) for n, u in rows if not os.path.exists(pdf_path(n))]
