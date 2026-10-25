import json
import os
import time
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
CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  month TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
  created TEXT, sent_at TEXT, main TEXT, sub TEXT, to_addr TEXT,
  error TEXT, attempts INTEGER DEFAULT 0, last_try REAL, notified INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notified (
  key TEXT PRIMARY KEY, at REAL, kind TEXT, title TEXT, message TEXT, sent INTEGER DEFAULT 1
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

    # --- dziennik powiadomień (też ochrona przed powtórkami)
    def was_notified(self, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM notified WHERE key=?", (key,)).fetchone() is not None

    def log_notification(self, key: str, kind: str, title: str, message: str, sent: bool = True):
        self.db.execute("INSERT OR REPLACE INTO notified(key,at,kind,title,message,sent) VALUES(?,?,?,?,?,?)",
                        (key, time.time(), kind, title, message, int(bool(sent))))
        self.db.commit()

    def notifications(self, limit: int = 40) -> list[dict]:
        cur = self.db.execute("SELECT key,at,kind,title,message,sent FROM notified ORDER BY at DESC LIMIT ?", (limit,))
        return [dict(zip(("key", "at", "kind", "title", "message", "sent"), r)) for r in cur.fetchall()]

    def notified_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM notified").fetchone()[0]

    # --- wysyłki odczytów do GPK
    def submissions(self, month: str | None = None) -> list[dict]:
        q = "SELECT id,month,kind,status,created,sent_at,main,sub,to_addr,error,attempts,last_try,notified FROM submissions"
        args: tuple = ()
        if month:
            q += " WHERE month=?"
            args = (month,)
        cols = ["id", "month", "kind", "status", "created", "sent_at", "main", "sub", "to_addr", "error", "attempts", "last_try", "notified"]
        return [dict(zip(cols, r)) for r in self.db.execute(q + " ORDER BY id DESC", args).fetchall()]

    def add_submission(self, month, kind, status, created, **kw) -> int:
        cur = self.db.execute("INSERT INTO submissions(month,kind,status,created) VALUES (?,?,?,?)", (month, kind, status, created))
        self.db.commit()
        if kw:
            self.update_submission(cur.lastrowid, **kw)
        return cur.lastrowid

    def update_submission(self, sid: int, **kw):
        allowed = {"status", "sent_at", "main", "sub", "to_addr", "error", "attempts", "last_try", "notified"}
        kw = {k: v for k, v in kw.items() if k in allowed}
        if kw:
            self.db.execute(f"UPDATE submissions SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), sid))
            self.db.commit()
