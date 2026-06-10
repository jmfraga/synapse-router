#!/usr/bin/env python3
"""Minimal OpenAI-compatible server for Gemma 4 26B MoE via mlx-vlm."""
import json, time, uuid, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template

MODEL_PATH = "/Users/jmfraga/.cache/huggingface/hub/models--mlx-community--gemma-4-26b-a4b-it-4bit/snapshots/b86b3e222c60ae7c652380cf516cb9c55c954fea"
HOST, PORT = "0.0.0.0", 8095

print(f"Loading from {MODEL_PATH}...")
model, processor = load(MODEL_PATH)
print(f"✓ 26B MoE loaded on port {PORT}")

def strip_thinking(text):
    text = re.sub(r'<\|channel\>thought.*?(<channel\|>|$)', '', text, flags=re.DOTALL).strip()
    return text

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/v1/models": self._json(200, {"object":"list","data":[{"id":"gemma-4-26b-a4b-it","object":"model","owned_by":"mlx-community"}]})
        else: self._json(404, {"error":"not found"})
    def do_POST(self):
        if self.path != "/v1/chat/completions": self._json(404,{"error":"not found"}); return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))))
        prompt_text = next((m["content"] for m in reversed(body.get("messages",[])) if m["role"]=="user"), "")
        formatted = apply_chat_template(
            processor, config=model.config, prompt=prompt_text,
            enable_thinking=True,
        )
        max_tok = body.get("max_tokens", 2048) + 1024  # extra tokens for thinking
        result = generate(model, processor, prompt=formatted, max_tokens=max_tok, verbose=False)
        raw_text = result.text if hasattr(result,"text") else str(result)
        text = strip_thinking(raw_text)
        gen_tok = result.generation_tokens if hasattr(result,"generation_tokens") else 0
        pt = result.prompt_tokens if hasattr(result,"prompt_tokens") else 0
        self._json(200, {"id":f"chatcmpl-{uuid.uuid4().hex[:12]}","object":"chat.completion","created":int(time.time()),"model":"gemma-4-26b-a4b-it","choices":[{"index":0,"message":{"role":"assistant","content":text},"finish_reason":"stop" if gen_tok<max_tok else "length"}],"usage":{"prompt_tokens":pt,"completion_tokens":gen_tok,"total_tokens":pt+gen_tok}})

if __name__ == "__main__":
    HTTPServer((HOST,PORT),Handler).serve_forever()
