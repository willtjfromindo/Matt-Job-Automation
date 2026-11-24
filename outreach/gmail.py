"""Gmail API: refresh the access token, send, and read messages. Plain HTTP, no Google SDK."""

import base64
import html
import mimetypes
import time
from email.message import EmailMessage
from pathlib import Path
from email.utils import formataddr, make_msgid

import httpx

from . import crypto

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"


def as_html(body: str) -> str:
    """The body as Gmail writes it when you type an email yourself: one <div> per line.

    Gmail shows plain-text emails in a narrow column with odd line breaks, so the HTML
    version is what people see; the plain text stays as a fallback."""
    lines = body.strip("\n").split("\n")
    return '<div dir="ltr">' + "".join(
        f"<div>{html.escape(line)}</div>" if line.strip() else "<div><br></div>" for line in lines
    ) + "</div>"


class NeedsReauth(RuntimeError):
    """The refresh token was revoked or expired: the sender must sign in again."""


class GmailError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Gmail:
    def __init__(self, conn, settings, http: httpx.Client | None = None,
                 token_url: str = TOKEN_URL, api: str = API):
        self.conn = conn
        self.settings = settings
        self.http = http or httpx.Client(timeout=60)
        self.token_url = token_url
        self.api = api
        self._access_token: str | None = None
        self._expires_at = 0.0

    # ---------- auth ----------

    def _refresh_token(self) -> str:
        row = self.conn.execute(
            "select encrypted_refresh_token, status from google_tokens where email = %s",
            (self.settings.sender_email,),
        ).fetchone()
        if not row or row["status"] != "ok":
            raise NeedsReauth(f"No working Google sign-in for {self.settings.sender_email}")
        return crypto.decrypt(row["encrypted_refresh_token"], self.settings.token_encryption_key)

    def access_token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        r = self.http.post(self.token_url, data={
            "client_id": self.settings.google_client_id,
            "client_secret": self.settings.google_client_secret,
            "refresh_token": self._refresh_token(),
            "grant_type": "refresh_token",
        })
        try:
            error_code = r.json().get("error") if r.status_code >= 400 else None
        except ValueError:
            error_code = None
        if r.status_code in (400, 401) and error_code in ("invalid_grant", "unauthorized_client"):
            self.conn.execute(
                "update google_tokens set status = 'needs_reauth', updated_at = now() where email = %s",
                (self.settings.sender_email,))
            self.conn.commit()
            raise NeedsReauth("Google sign-in expired or was revoked")
        if r.status_code >= 400:
            raise GmailError(f"token refresh failed: {r.status_code} {r.text[:200]}")
        body = r.json()
        self._access_token = body["access_token"]
        self._expires_at = time.time() + int(body.get("expires_in", 3600))
        return self._access_token

    def _request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(4):
            r = self.http.request(method, self.api + path,
                                  headers={"Authorization": f"Bearer {self.access_token()}"}, **kwargs)
            if r.status_code == 401 and attempt == 0:
                self._access_token = None   # token expired early: refresh once
                continue
            if r.status_code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt * 5)
                continue
            if r.status_code >= 400:
                raise GmailError(f"Gmail {method} {path}: {r.status_code} {r.text[:300]}",
                                 r.status_code)
            return r.json() if r.content else {}
        raise GmailError(f"Gmail {method} {path}: gave up after retries")

    # ---------- sending ----------

    def send(self, to: str, subject: str, body: str, thread_id: str | None = None,
             in_reply_to: str | None = None, attachments: list[str] | None = None) -> dict:
        """Send an email (HTML, with a plain-text copy), with optional file attachments.
        Returns {id, threadId, rfc_message_id}."""
        msg = EmailMessage()
        sender = self.settings.sender_email
        msg["From"] = formataddr((self.settings.sender_name, sender)) if self.settings.sender_name else sender
        msg["To"] = to
        msg["Subject"] = subject
        rfc_id = make_msgid(domain=sender.split("@", 1)[1] if "@" in sender else None)
        msg["Message-ID"] = rfc_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        msg.add_alternative(as_html(body), subtype="html")
        for path in attachments or []:
            kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
            maintype, subtype = kind.split("/", 1)
            msg.add_attachment(Path(path).read_bytes(), maintype=maintype, subtype=subtype,
                               filename=Path(path).name)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        sent = self._request("POST", "/messages/send", json=payload)
        # Gmail may replace our Message-ID; read back the real one for threading follow-ups.
        try:
            meta = self.get_message(sent["id"], headers=["Message-ID"])
            rfc_id = header(meta, "Message-ID") or rfc_id
        except GmailError:
            pass
        return {"id": sent["id"], "threadId": sent.get("threadId"), "rfc_message_id": rfc_id}

    # ---------- reading ----------

    def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
        ids, page = [], None
        while len(ids) < max_results:
            params = {"q": query, "maxResults": min(100, max_results - len(ids))}
            if page:
                params["pageToken"] = page
            body = self._request("GET", "/messages", params=params)
            ids += [m["id"] for m in body.get("messages", [])]
            page = body.get("nextPageToken")
            if not page:
                break
        return ids

    def get_message(self, message_id: str, headers: list[str]) -> dict:
        params = [("format", "metadata")] + [("metadataHeaders", h) for h in headers]
        return self._request("GET", f"/messages/{message_id}", params=params)


def header(message: dict, name: str) -> str | None:
    for h in message.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None
