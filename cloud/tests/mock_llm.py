"""Tiny OpenAI-compatible model server for end-to-end tests (stdlib only).

    python mock_llm.py 9000

Every chat completion answers "Hello from the mock model." and reports
usage {prompt_tokens: 1200, completion_tokens: 300}, streamed or not.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = "Hello from the mock model."
USAGE = {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._json(200, {"data": [{"id": "mock-1"}]})
        self._json(404, {"error": "nope"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        if not self.headers.get("Authorization", "").startswith("Bearer "):
            return self._json(401, {"error": {"message": "no key"}})
        if not req.get("stream"):
            return self._json(200, {
                "id": "m", "object": "chat.completion", "model": req.get("model"),
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": REPLY}}],
                "usage": USAGE})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        base = {"id": "m", "object": "chat.completion.chunk", "model": req.get("model")}
        for i, piece in enumerate(REPLY.split(" ")):
            text = piece if i == 0 else " " + piece
            chunk = dict(base, choices=[{"index": 0, "delta": {"content": text}, "finish_reason": None}])
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        done = dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}])
        self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())
        if (req.get("stream_options") or {}).get("include_usage"):
            self.wfile.write(f"data: {json.dumps(dict(base, choices=[], usage=USAGE))}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 9000), H).serve_forever()
