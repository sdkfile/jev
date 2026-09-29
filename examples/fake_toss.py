"""토스증권 Open API 가짜 서버 — 스펙(1.2.17) 모양 그대로. 테스트 전용.
가격은 5틱 오르다 5틱 내리기를 반복한다. 주문은 기록만 한다."""
import json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

STATE = {"tick": 0, "orders": [], "qty": 0, "tokens": 0}

def price_at(i):
    """20틱 주기: 앞 10틱은 매 틱 +0.8% 로 오르고 거래량이 불어난다, 뒤 10틱은 매 틱 -0.8% 로 빠진다."""
    cyc = i % 20
    step = cyc if cyc < 10 else 20 - cyc
    return round(70000 * (1.008 ** step))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def authed(self):
        if self.headers.get("Authorization") != "Bearer fake-token":
            self.send(401, {"error": {"code": "token-invalid"}}); return False
        return True
    def do_POST(self):
        u = urlparse(self.path); n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n).decode()
        if u.path == "/oauth2/token":
            STATE["tokens"] += 1
            return self.send(200, {"access_token": "fake-token", "token_type": "Bearer", "expires_in": 86400})
        if not self.authed(): return
        if u.path == "/api/v1/orders":
            if not self.headers.get("X-Tossinvest-Account"):
                return self.send(400, {"error": {"code": "account-required"}})
            body = json.loads(raw); STATE["orders"].append(body)
            STATE["qty"] += int(body["quantity"]) * (1 if body["side"] == "BUY" else -1)
            return self.send(200, {"result": {"orderId": "ord" + str(len(STATE["orders"])).zfill(20), "clientOrderId": body.get("clientOrderId")}})
        self.send(404, {})
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/__state":
            return self.send(200, STATE)
        if not self.authed(): return
        if u.path == "/api/v1/candles":
            STATE["tick"] += 1; t = STATE["tick"]; cnt = int(q.get("count", ["30"])[0])
            rows = []
            for k in range(cnt):  # 최신순
                i = t - k; p = price_at(i)
                rows.append({"timestamp": f"2026-09-29T10:{(i % 60):02d}:00+09:00", "openPrice": str(p - 100), "highPrice": str(p + 100),
                             "lowPrice": str(p - 200), "closePrice": str(p), "volume": str(100000 + (i % 5) * 50000), "currency": "KRW"})
            return self.send(200, {"result": {"candles": rows, "nextBefore": None}})
        if u.path == "/api/v1/accounts":
            return self.send(200, {"result": [{"accountNo": "00000000000", "accountSeq": 1, "accountType": "BROKERAGE"}]})
        if u.path == "/api/v1/holdings":
            items = [{"symbol": q["symbol"][0], "quantity": str(STATE["qty"])}] if STATE["qty"] else []
            return self.send(200, {"result": {"items": items}})
        if u.path == "/__state":
            return self.send(200, STATE)
        self.send(404, {})

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
