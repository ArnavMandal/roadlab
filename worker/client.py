"""No database access: workers use only Relay's HTTP protocol."""

import json
import os
import urllib.error
import urllib.request

URL = os.environ.get("RELAY_URL", "http://127.0.0.1:8080")


class HTTPError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def request(path, body=None, key=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(
        URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r) if r.status != 204 else None
    except urllib.error.HTTPError as e:
        raise HTTPError(e.code, e.read().decode()) from e
