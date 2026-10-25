"""Pobieranie faktur z Gmaila przez IMAP (hasło aplikacji Google)."""
import email
import imaplib
import logging
from email.header import decode_header

from .parser import ParseError, parse_invoice_pdf

log = logging.getLogger("gpk.mail")


def _fname(part) -> str:
    raw = part.get_filename() or ""
    out = ""
    for chunk, enc in decode_header(raw):
        out += chunk.decode(enc or "utf-8", "replace") if isinstance(chunk, bytes) else chunk
    return out


def sync(store, host: str, user: str, password: str, sender: str, since: str, folder: str = '"[Gmail]/All Mail"') -> dict:
    """Przechodzi po mailach od nadawcy, parsuje nowe PDF-y. Zwraca statystyki."""
    stats = dict(mails=0, new=0, dup=0, failed=0, skipped=0)
    imap = imaplib.IMAP4_SSL(host)
    try:
        imap.login(user, password)
        typ, _ = imap.select(folder, readonly=True)
        if typ != "OK":  # skrzynka w innym języku / bez All Mail
            imap.select("INBOX", readonly=True)
        typ, data = imap.uid("SEARCH", None, f'(FROM "{sender}" SINCE {since})')
        uids = data[0].split() if typ == "OK" and data and data[0] else []
        for raw_uid in uids:
            uid = raw_uid.decode()
            if store.mail_seen(uid):
                stats["skipped"] += 1
                continue
            stats["mails"] += 1
            typ, msg_data = imap.uid("FETCH", raw_uid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            pdfs = [p for p in msg.walk() if p.get_content_maintype() != "multipart"
                    and (_fname(p).lower().endswith(".pdf") or p.get_content_type() == "application/pdf")]
            if not pdfs:
                store.mark_mail(uid, "no_pdf")
                continue
            ok = False
            for part in pdfs:
                payload = part.get_payload(decode=True)
                try:
                    inv = parse_invoice_pdf(payload)
                except (ParseError, Exception) as e:  # noqa: BLE001
                    log.warning("mail %s (%s): nie sparsowano: %s", uid, _fname(part), e)
                    store.mark_mail(uid, "failed", f"{_fname(part)}: {e}")
                    stats["failed"] += 1
                    continue
                for w in inv["warnings"]:
                    log.warning("faktura %s: %s", inv["number"], w)
                if store.add_invoice(inv, uid):
                    stats["new"] += 1
                else:
                    stats["dup"] += 1
                ok = True
            if ok:
                store.mark_mail(uid, "ok")
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    return stats
