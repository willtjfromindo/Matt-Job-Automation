"""A tiny fake Google (token + Gmail send/list/get) for local end-to-end tests.

Run:  .venv/bin/python tests/fake_google.py 8765
Then point the worker at it with GOOGLE_TOKEN_URL=http://localhost:8765/token and
GMAIL_API_BASE=http://localhost:8765/gmail. Every "sent" email is printed and kept in memory;
GET /sent returns them as JSON.
"""

import base64
import json
import sys
from email import message_from_bytes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SENT = []


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        path = urlparse(self.path).path
        if path == "/token":
            return self._json(200, {"access_token": "fake-access", "expires_in": 3600})
        if path.endswith("/messages/send"):
            payload = json.loads(body)
            msg = message_from_bytes(base64.urlsafe_b64decode(payload["raw"]))
            n = len(SENT) + 1
            thread = payload.get("threadId") or f"thread{n}"
            SENT.append({"id": f"msg{n}", "threadId": thread, "to": msg["To"], "from": msg["From"],
                         "subject": msg["Subject"], "body": msg.get_payload()})
            print(f"SENT #{n} to {msg['To']}: {msg['Subject']}", flush=True)
            return self._json(200, {"id": f"msg{n}", "threadId": thread})
        return self._json(404, {})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/sent":
            return self._json(200, SENT)
        if path.endswith("/messages"):
            return self._json(200, {"messages": []})
        if "/messages/" in path:
            mid = path.rsplit("/", 1)[1]
            return self._json(200, {"id": mid, "payload": {"headers": [
                {"name": "Message-ID", "value": f"<{mid}@fake.google>"}]}})
        return self._json(404, {})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"fake google on :{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
