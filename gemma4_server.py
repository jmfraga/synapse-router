#!/usr/bin/env python3
"""Minimal OpenAI-compatible server for Gemma 4 31B via mlx-vlm."""

import json
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template

MODEL_ID = "mlx-community/gemma-4-31b-it-4bit"
HOST = "0.0.0.0"
PORT = 8092

print(f"Loading {MODEL_ID}...")
model, processor = load(MODEL_ID)
print(f"✓ Model loaded on port {PORT}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress logs

    def _send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send_json(200, {
                "object": "list",
                "data": [{"id": MODEL_ID, "object": "model", "owned_by": "mlx-community"}],
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        messages = body.get("messages", [])
        max_tokens = body.get("max_tokens", 1500)

        # Extract last user message
        prompt_text = ""
        for msg in messages:
            if msg["role"] == "user":
                prompt_text = msg["content"]

        formatted = apply_chat_template(processor, config=model.config, prompt=prompt_text)

        t0 = time.time()
        result = generate(model, processor, prompt=formatted, max_tokens=max_tokens, verbose=False)
        elapsed = time.time() - t0

        text = result.text if hasattr(result, "text") else str(result)
        gen_tokens = result.generation_tokens if hasattr(result, "generation_tokens") else 0
        prompt_tokens = result.prompt_tokens if hasattr(result, "prompt_tokens") else 0

        self._send_json(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop" if gen_tokens < max_tokens else "length",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": gen_tokens,
                "total_tokens": prompt_tokens + gen_tokens,
            },
        })


if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), Handler)
    print(f"Serving on {HOST}:{PORT}")
    server.serve_forever()
