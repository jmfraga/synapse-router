#!/usr/bin/env python3
"""Minimal OpenAI-compatible server for Gemma 4 E4B via mlx-vlm."""
import json, time, uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template

MODEL_ID = "mlx-community/gemma-4-e4b-it-4bit"
HOST, PORT = "0.0.0.0", 8093

print(f"Loading {MODEL_ID}...")
model, processor = load(MODEL_ID)
print(f"✓ E4B loaded on port {PORT}")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/v1/models": self._json(200, {"object":"list","data":[{"id":MODEL_ID,"object":"model","owned_by":"mlx-community"}]})
        else: self._json(404, {"error":"not found"})
    def do_POST(self):
        if self.path != "/v1/chat/completions": self._json(404,{"error":"not found"}); return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))))
        prompt_text = next((m["content"] for m in reversed(body.get("messages",[])) if m["role"]=="user"), "")
        formatted = apply_chat_template(processor, config=model.config, prompt=prompt_text)
        t0 = time.time()
        result = generate(model, processor, prompt=formatted, max_tokens=body.get("max_tokens",1500), verbose=False)
        text = result.text if hasattr(result,"text") else str(result)
        gen_tok = result.generation_tokens if hasattr(result,"generation_tokens") else 0
        pt = result.prompt_tokens if hasattr(result,"prompt_tokens") else 0
        self._json(200, {"id":f"chatcmpl-{uuid.uuid4().hex[:12]}","object":"chat.completion","created":int(time.time()),"model":MODEL_ID,"choices":[{"index":0,"message":{"role":"assistant","content":text},"finish_reason":"stop" if gen_tok<body.get("max_tokens",1500) else "length"}],"usage":{"prompt_tokens":pt,"completion_tokens":gen_tok,"total_tokens":pt+gen_tok}})

if __name__ == "__main__":
    HTTPServer((HOST,PORT),Handler).serve_forever()
