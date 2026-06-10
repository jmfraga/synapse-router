#!/usr/bin/env python3
"""Proxy server for all Gemma 4 MLX models — single provider, multiple backends."""

import json
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

HOST, PORT = "0.0.0.0", 8094

# Model -> backend mapping
BACKENDS = {
    "gemma-4-31b-it": "http://localhost:8092",
    "gemma-4-26b-a4b-it": "http://localhost:8095",
    "gemma-4-e4b-it": "http://localhost:8093",
}

MODELS = [
    {"id": "gemma-4-31b-it", "object": "model", "owned_by": "mlx-community"},
    {"id": "gemma-4-26b-a4b-it", "object": "model", "owned_by": "mlx-community"},
    {"id": "gemma-4-e4b-it", "object": "model", "owned_by": "mlx-community"},
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._json(200, {"object": "list", "data": MODELS})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        data = json.loads(body)
        model = data.get("model", "")

        # Find backend
        backend = None
        for key, url in BACKENDS.items():
            if key in model:
                backend = url
                break

        if not backend:
            self._json(400, {"error": f"Unknown model: {model}. Available: {list(BACKENDS.keys())}"})
            return

        # Forward request to backend
        try:
            req = urllib.request.Request(
                f"{backend}/v1/chat/completions",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read())
                self._json(200, result)
        except Exception as e:
            self._json(502, {"error": f"Backend error ({backend}): {str(e)}"})


if __name__ == "__main__":
    print(f"Gemma 4 proxy on :{PORT} -> {list(BACKENDS.keys())}")
    HTTPServer((HOST, PORT), Handler).serve_forever()
