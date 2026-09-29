"""토스 1분봉 리플레이 서버 — 실제로 받아둔 1분봉(JSON)을 요청마다 1분씩 앞으로 돌려준다.
장이 닫힌 뒤 '그날 실제 시세'로 jev trade 를 다시 녹화할 때 쓴다. 주문은 받지 않는다(모의 전용).
  python3 examples/replay_toss.py <candles.json> <port> [시작 HH:MM]   (파일의 마지막 날, 그 시각부터)
"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

rows = sorted(json.load(open(sys.argv[1])), key=lambda r: r["timestamp"])
start = sys.argv[3] if len(sys.argv) > 3 else "09:30"
day = rows[-1]["timestamp"][:10]
idx = next(i for i, r in enumerate(rows) if r["timestamp"][:10] == day and r["timestamp"][11:16] >= start)
STATE = {"i": idx - 1}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        if urlparse(self.path).path == "/oauth2/token":
            return self.send(200, {"access_token": "replay", "token_type": "Bearer", "expires_in": 86400})
        self.send(404, {})

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/api/v1/candles":
            STATE["i"] = min(STATE["i"] + 1, len(rows) - 1)
            cnt = int(q.get("count", ["30"])[0])
            win = rows[max(0, STATE["i"] - cnt + 1): STATE["i"] + 1]
            return self.send(200, {"result": {"candles": list(reversed(win)), "nextBefore": None}})
        self.send(404, {})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2])), H).serve_forever()
