"""Wysyłka maili przez SMTP Gmaila (to samo hasło aplikacji co IMAP) i sprawdzanie, czy mail już wyszedł."""
import imaplib
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

MONTH_HEADER = "X-GPK-Water-Month"


def send_mail(user: str, password: str, to: list[str], cc: list[str], subject: str, body: str, month: str,
              host: str = "smtp.gmail.com", port: int = 465) -> str:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, ", ".join(to), subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="gpk-water.local")
    msg[MONTH_HEADER] = month
    msg.set_content(body)
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=60) as s:
        s.login(user, password)
        s.send_message(msg, from_addr=user, to_addrs=to + cc)
    return msg["Message-ID"]


def find_folder(imap: imaplib.IMAP4_SSL, flag: str):
    """Folder Gmaila po atrybucie special-use (np. \\All) - nazwy są zlokalizowane."""
    typ, data = imap.list()
    for raw in data or []:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        m = re.match(r'\((?P<attrs>[^)]*)\)\s+"(?P<sep>[^"]*)"\s+(?P<name>.+)$', line)
        if m and flag.lower() in m["attrs"].lower().split():
            return m["name"]
    return None


def already_sent(user: str, password: str, month: str, host: str = "imap.gmail.com") -> bool:
    """True, jeśli w Gmailu jest już mail wysłany przez dodatek za dany miesiąc (ochrona przed dublem po awarii)."""
    imap = imaplib.IMAP4_SSL(host)
    try:
        imap.login(user, password)
        folder = find_folder(imap, "\\All") or "INBOX"
        if imap.select(folder, readonly=True)[0] != "OK":
            return False
        typ, data = imap.uid("SEARCH", None, "HEADER", MONTH_HEADER, month)
        return typ == "OK" and bool(data and data[0])
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
