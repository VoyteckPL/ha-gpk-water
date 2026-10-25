"""Pobieranie faktur z Gmaila przez IMAP (hasło aplikacji Google)."""
import email
import imaplib
import logging
import os
import re
from email.header import decode_header

from .parser import NotWaterInvoice, ParseError, parse_invoice_pdf

log = logging.getLogger("gpk.mail")

FAILED_DIR = "/share/gpk_water_failed"


def _save_failed(uid: str, name: str, payload: bytes):
    try:
        os.makedirs(FAILED_DIR, exist_ok=True)
        safe = re.sub(r"[^\w.\-]", "_", name or "faktura.pdf")
        path = os.path.join(FAILED_DIR, f"{uid}_{safe}")
        with open(path, "wb") as f:
            f.write(payload)
        log.info("zapisano nieudany PDF: %s", path)
    except OSError as e:
        log.warning("nie udało się zapisać PDF do %s: %s", FAILED_DIR, e)


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
                except NotWaterInvoice as e:
                    log.info("mail %s (%s): pomijam - %s", uid, _fname(part), e)
                    store.mark_mail(uid, "not_invoice", _fname(part))
                    continue
                except (ParseError, Exception) as e:  # noqa: BLE001
                    log.warning("mail %s (%s): nie sparsowano: %s", uid, _fname(part), e)
                    store.mark_mail(uid, "failed", f"{_fname(part)}: {e}")
                    _save_failed(uid, _fname(part), payload)
                    stats["failed"] += 1
                    continue
                for w in inv["warnings"]:
                    log.warning("faktura %s: %s", inv["number"], w)
                store.save_pdf(inv["number"], payload)
                if store.add_invoice(inv, uid):
                    stats["new"] += 1
                else:
                    stats["dup"] += 1
                ok = True
            if ok:
                store.mark_mail(uid, "ok")
        # faktury z bazy, których PDF-a jeszcze nie mamy na dysku (import sprzed wersji 0.2)
        for number, uid in store.invoices_missing_pdf():
            typ, md = imap.uid("FETCH", uid.encode(), "(RFC822)")
            if typ != "OK" or not md or not md[0]:
                continue
            msg = email.message_from_bytes(md[0][1])
            for p in msg.walk():
                if p.get_content_maintype() != "multipart" and (_fname(p).lower().endswith(".pdf") or p.get_content_type() == "application/pdf"):
                    try:
                        if parse_invoice_pdf(p.get_payload(decode=True))["number"] == number:
                            store.save_pdf(number, p.get_payload(decode=True))
                            stats["pdf_backfilled"] = stats.get("pdf_backfilled", 0) + 1
                    except Exception:  # noqa: BLE001
                        pass
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    return stats
