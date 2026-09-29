#!/usr/bin/env python3
"""jev — Jev(TypeSafe AI) 결정 모델을 터미널·에이전트에서 쓰는 CLI.

  jev ask     : 아무 텍스트/JSON 을 넣고 예·아니오/분류/점수를 받는다 (에이전트용)
  jev trade   : 토스증권 1분봉을 Jev 에게 보여주고 매수/매도/대기를 정한다
                기본은 모의(paper). 실주문은 --live 와 --max-krw 가 둘 다 있어야 한다.
  jev accounts: 토스증권 계좌 목록 (실주문 준비용)

표준 라이브러리만 쓴다. 자격증명은 환경변수로만 받는다.
  Jev  : AI_GATEWAY_API_KEY  또는 VERCEL_OIDC_TOKEN  또는 OPENROUTER_API_KEY
         (둘 다 없으면 JEV_VERCEL_PROJECT_DIR 에서 `vercel env pull` 로 OIDC 를 받아온다)
  토스 : TOSSINVEST_CLIENT_ID, TOSSINVEST_CLIENT_SECRET, (실주문) TOSSINVEST_ACCOUNT
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

def _load_dotenv() -> None:
    """키는 환경변수 → 이 스킬 폴더(또는 상위)의 .env → ~/.hermes/.env 순으로 찾는다. 이미 있는 값은 덮지 않는다."""
    here = Path(__file__).resolve().parent
    for f in (here / ".env", here.parent / ".env", Path.home() / ".hermes" / ".env"):
        if not f.is_file():
            continue
        for line in f.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[7:].strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip().strip('"').strip("'")


_load_dotenv()

# Vercel AI Gateway 키가 있으면 Vercel, 없고 OPENROUTER_API_KEY 가 있으면 OpenRouter(같은 요청 모양).
# Vercel 무료 등급은 403 "Free tier users do not have access" 로 막힌다(9/28 실측) → OpenRouter 가 기본 우회로.
_VERCEL = bool(os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("VERCEL_OIDC_TOKEN") or os.environ.get("JEV_VERCEL_PROJECT_DIR"))
_OPENROUTER = not _VERCEL and bool(os.environ.get("OPENROUTER_API_KEY"))
GATEWAY = os.environ.get("JEV_GATEWAY_URL") or ("https://openrouter.ai/api/alpha/decisions" if _OPENROUTER
                                                 else "https://ai-gateway.vercel.sh/typesafe/v1/systemone")
MODEL = os.environ.get("JEV_MODEL") or ("typesafe/jev-1.13" if _OPENROUTER else "typesafe-ai/jev")
TOSS = os.environ.get("TOSSINVEST_BASE_URL", "https://openapi.tossinvest.com")
HOME = Path(os.environ.get("JEV_HOME", Path.home() / ".jev"))


class JevError(RuntimeError):
    pass


# ---------------------------------------------------------------- http

def _http(method: str, url: str, *, headers=None, body=None, form=False, timeout=20):
    data = None
    headers = dict(headers or {})
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw[:500]
        return e.code, payload, dict(e.headers)


# ---------------------------------------------------------------- jev

def _gateway_token() -> str:
    if _OPENROUTER:
        return os.environ["OPENROUTER_API_KEY"]
    for k in ("AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    cache = HOME / "oidc.json"
    if cache.exists():
        c = json.loads(cache.read_text())
        if c.get("exp", 0) - time.time() > 300:
            return c["token"]
    proj = os.environ.get("JEV_VERCEL_PROJECT_DIR")
    if not proj:
        raise JevError("Jev 인증 없음: AI_GATEWAY_API_KEY 나 VERCEL_OIDC_TOKEN, 또는 JEV_VERCEL_PROJECT_DIR 를 설정하세요")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "v.env"
        subprocess.run(["vercel", "env", "pull", str(out), "--environment=development", "--yes"],
                       cwd=proj, check=True, capture_output=True)
        tok = next((l.split("=", 1)[1].strip().strip('"') for l in out.read_text().splitlines()
                    if l.startswith("VERCEL_OIDC_TOKEN=")), None)
    if not tok:
        raise JevError(f"{proj} 에서 VERCEL_OIDC_TOKEN 을 못 받았습니다 (vercel link 확인)")
    HOME.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"token": tok, "exp": time.time() + 11 * 3600}))
    cache.chmod(0o600)
    return tok


def systemone(state, questions: dict, retries: int = 3) -> dict:
    """Jev 한 번 호출. questions 는 TypeSafe 형식 그대로. 429·5xx 는 잠깐 쉬고 다시 시도한다."""
    for attempt in range(retries + 1):
        t0 = time.time()
        status, res, _ = _http("POST", GATEWAY, headers={"Authorization": f"Bearer {_gateway_token()}"},
                               body={"model": MODEL, "state": state, "questions": questions})
        if status == 200:
            res["_latency_ms"] = round((time.time() - t0) * 1000)
            return res
        if status in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(0.5 * 2 ** attempt)
            continue
        msg = res.get("error", {}).get("message") if isinstance(res, dict) and isinstance(res.get("error"), dict) else res
        raise JevError(f"Jev {status}: {msg}")


def parse_questions(noul, choice, score) -> dict:
    """CLI 표기 → TypeSafe questions.
    --noul  name="지시문"
    --choice name="지시문|키:설명,키:설명"
    --score name="지시문|낮음;중간;높음"
    """
    q = {}

    def split(spec):
        if "=" not in spec:
            raise JevError(f'질문 형식이 틀렸습니다: {spec!r} — 이름="지시문" 꼴로 주세요 (jev ask -h)')
        name, rest = spec.split("=", 1)
        return name.strip(), rest.strip().strip('"').strip("'")

    noul = [split(s) for s in noul or []]
    choice = [split(s) for s in choice or []]
    score = [split(s) for s in score or []]
    for name, instr in noul:
        q[name] = {"type": "noul", "instructions": instr}
    for name, rest in choice:
        if "|" not in rest or ":" not in rest:
            raise JevError(f'--choice 형식: 이름="지시문|키:설명,키:설명" — 받은 값: {rest!r}')
        instr, opts = rest.split("|", 1)
        crit = dict(o.split(":", 1) for o in opts.split(","))
        q[name] = {"type": "choice", "instructions": instr, "criteria": crit}
    for name, rest in score:
        instr, levels = rest.split("|", 1)
        q[name] = {"type": "score", "instructions": instr, "criteria": levels.split(";")}
    if not q:
        raise JevError("질문이 없습니다: --noul / --choice / --score 중 하나 이상")
    return q


def cmd_ask(a) -> int:
    state = sys.stdin.read() if a.state == "-" else (Path(a.state[1:]).read_text() if a.state.startswith("@") else a.state)
    try:
        state = json.loads(state)  # JSON 이면 구조 그대로 넘긴다
    except ValueError:
        pass
    res = systemone(state, parse_questions(a.noul, a.choice, a.score))
    out = {"answers": res["answers"], "latency_ms": res["_latency_ms"],
           "cost_usd": ((res.get("provider_metadata") or {}).get("gateway") or {}).get("cost")}
    if a.pretty:
        print(pretty_answers(out))
        return 0
    print(json.dumps(out, ensure_ascii=False, indent=None if a.compact else 2))
    return 0


def pretty_answers(out: dict) -> str:
    """사람이 읽는 한 줄씩: 질문 → 답 (확률). 화면 녹화·터미널용. 에이전트는 JSON 을 쓴다."""
    lines = []
    for name, ans in out["answers"].items():
        t = ans.get("type")
        if t == "noul":
            p = float(ans["noul"])
            lines.append(f"  {name}  →  {'예' if p >= 0.5 else '아니오'}  ({p:.0%})")
        elif t == "choice":
            probs = sorted(ans.get("probabilities", {}).items(), key=lambda kv: -float(kv[1]))
            rest = " · ".join(f"{k} {float(v):.0%}" for k, v in probs[1:])
            lines.append(f"  {name}  →  {ans['choice']}  ({float(probs[0][1]):.0%})" + (f"\n    {rest}" if rest else ""))
        elif t == "score":
            lines.append(f"  {name}  →  {ans.get('score')}")
        else:
            lines.append(f"  {name}  →  {json.dumps(ans, ensure_ascii=False)}")
    lines.append(f"  ⏱ {out['latency_ms'] / 1000:.2f}초")
    return "\n".join(lines)


# ---------------------------------------------------------------- toss

def toss_token() -> str:
    """클라이언트당 유효 토큰은 1개 — 새로 받으면 이전 것이 죽는다. 그래서 파일에 캐시해 공유한다."""
    cache = HOME / "toss-token.json"
    if cache.exists():
        c = json.loads(cache.read_text())
        if c.get("exp", 0) - time.time() > 120:
            return c["token"]
    cid, sec = os.environ.get("TOSSINVEST_CLIENT_ID"), os.environ.get("TOSSINVEST_CLIENT_SECRET")
    if not (cid and sec):
        raise JevError("토스증권 키 없음: TOSSINVEST_CLIENT_ID / TOSSINVEST_CLIENT_SECRET (WTS > 설정 > Open API)")
    status, res, _ = _http("POST", f"{TOSS}/oauth2/token", form=True,
                           body={"grant_type": "client_credentials", "client_id": cid, "client_secret": sec})
    if status != 200:
        raise JevError(f"토스 토큰 {status}: {res}")
    HOME.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"token": res["access_token"], "exp": time.time() + int(res["expires_in"])}))
    cache.chmod(0o600)
    return res["access_token"]


def toss(method, path, *, params=None, body=None, account=None):
    url = f"{TOSS}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    h = {"Authorization": f"Bearer {toss_token()}"}
    if account:
        h["X-Tossinvest-Account"] = str(account)
    status, res, _ = _http(method, url, headers=h, body=body)
    if status >= 300:
        raise JevError(f"토스 {method} {path} {status}: {res}")
    return res.get("result") if isinstance(res, dict) and "result" in res else res


def candles(symbol, count=30):
    rows = toss("GET", "/api/v1/candles", params={"symbol": symbol, "interval": "1m", "count": count})["candles"]
    return list(reversed(rows))  # API 는 최신순 → 시간순으로 뒤집는다


def cmd_accounts(a) -> int:
    for acc in toss("GET", "/api/v1/accounts"):
        print(f"accountSeq={acc['accountSeq']}  계좌번호={acc['accountNo']}  유형={acc['accountType']}")
    return 0


# ---------------------------------------------------------------- trade

DIRECTION = {
    "type": "choice",
    "instructions": "최근 1분봉을 보고 다음 몇 분 동안의 가격 방향",
    "criteria": {"up": "오를 가능성이 높다", "down": "내릴 가능성이 높다", "unclear": "판단하기 어렵다"},
}


def decide(symbol, rows) -> dict:
    state = {"symbol": symbol, "interval": "1m",
             "candles": [{"t": r["timestamp"][11:16], "o": r["openPrice"], "h": r["highPrice"],
                          "l": r["lowPrice"], "c": r["closePrice"], "v": r["volume"]} for r in rows]}
    res = systemone(state, {"direction": DIRECTION})
    ans = res["answers"]["direction"]
    return {"choice": ans["choice"], "confidence": ans.get("confidence"),
            "probabilities": ans.get("probabilities"), "latency_ms": res["_latency_ms"]}


class Book:
    """모의 계좌. 한 종목, 한 포지션만."""

    def __init__(self, path: Path, cash: float):
        self.path = path
        s = json.loads(path.read_text()) if path.exists() else {"cash": cash, "qty": 0, "avg": 0.0, "trades": 0}
        self.__dict__.update(s)

    def save(self):
        self.path.write_text(json.dumps({k: getattr(self, k) for k in ("cash", "qty", "avg", "trades")}))

    def buy(self, qty, price):
        cost = qty * price
        if cost > self.cash:
            return False
        self.avg = (self.avg * self.qty + cost) / (self.qty + qty)
        self.cash -= cost; self.qty += qty; self.trades += 1
        return True

    def sell(self, price):
        if not self.qty:
            return False
        self.cash += self.qty * price; self.qty = 0; self.avg = 0.0; self.trades += 1
        return True


def cmd_trade(a) -> int:
    if a.live and not a.max_krw:
        raise JevError("실주문은 --max-krw 로 1회 주문 한도를 꼭 정해야 합니다")
    account = os.environ.get("TOSSINVEST_ACCOUNT") if a.live else None
    if a.live and not account:
        raise JevError("실주문은 TOSSINVEST_ACCOUNT(accountSeq) 가 필요합니다 — `jev accounts` 로 확인")
    HOME.mkdir(parents=True, exist_ok=True)
    book = Book(HOME / f"paper-{a.symbol}.json", a.cash)
    log = HOME / f"trade-{a.symbol}.jsonl"
    mode = "실주문" if a.live else "모의"
    if a.pretty:
        print(f"\033[1m[{mode}투자] {a.symbol}\033[0m\n\033[2m토스증권 1분봉 → 젭\n확률 {a.min_conf:.0%} 넘으면 사고 판다\033[0m\n", flush=True)
    else:
        print(f"[{mode}] {a.symbol} {a.every}초마다 판단 · 오를/내릴 확률 {a.min_conf:.0%} 이상일 때만 주문 · 로그 {log}")

    n = 0
    while a.iterations == 0 or n < a.iterations:
        n += 1
        try:
            rows = candles(a.symbol, a.count)
            price = float(rows[-1]["closePrice"])
            d = decide(a.symbol, rows)
        except JevError as e:  # 한 번 실패로 루프를 죽이지 않는다 — 이번 판단만 건너뛴다
            print(f"{datetime.now():%H:%M:%S} 판단 건너뜀: {e}", file=sys.stderr)
            time.sleep(a.every)
            continue
        probs = d["probabilities"] or {}
        p_up, p_down = probs.get("up", 0), probs.get("down", 0)
        action = "대기"
        holding = book.qty if not a.live else _live_qty(account, a.symbol)
        if p_up >= a.min_conf and not holding:
            action = _buy(a, book, account, price)
        elif p_down >= a.min_conf and holding:
            action = _sell(a, book, account, price, holding)
        if not a.live:
            book.save()
        equity = book.cash + book.qty * price
        rec = {"at": datetime.now().isoformat(timespec="seconds"), "candle": rows[-1]["timestamp"][11:16],
               "mode": mode, "symbol": a.symbol, "price": price, **d, "action": action,
               **({} if a.live else {"cash": round(book.cash), "qty": book.qty, "equity": round(equity)})}
        with log.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        probs = " ".join(f"{k}{v:.0%}" for k, v in (d["probabilities"] or {}).items())
        tail = "" if a.live else f" | 평가 {equity:,.0f}원"
        if a.pretty:
            print(_pretty_tick(rec, d, price, action, equity, a.live), flush=True)
        else:
            print(f"{rec['at'][11:]} {price:,.0f}원 → {d['choice']} ({probs}, {d['latency_ms']}ms) → {action}{tail}")
        if a.iterations == 0 or n < a.iterations:
            time.sleep(a.every)
    return 0


_KO = {"up": "오름", "down": "내림", "unclear": "모름"}


def _pretty_tick(rec, d, price, action, equity, live) -> str:
    """세로 화면(녹화용) 두 줄: 시각·가격 / 판단·확률·주문. 매수는 초록, 매도는 빨강."""
    probs = d["probabilities"] or {}
    top = max(probs.items(), key=lambda kv: kv[1]) if probs else (d["choice"], 0)
    color = "\033[1;32m" if "매수" in action else "\033[1;31m" if "매도" in action else "\033[2m"
    line1 = f"\033[36m{rec['candle']}\033[0m  {price:,.0f}원"
    line2 = (f"  → {_KO.get(top[0], top[0])} {top[1]:.0%}  {color}{action}\033[0m"
             f"  \033[2m{d['latency_ms'] / 1000:.2f}초\033[0m")
    if not live and "대기" not in action:
        line2 += f"\n  \033[2m평가 {equity:,.0f}원\033[0m"
    return line1 + "\n" + line2


def _live_qty(account, symbol) -> int:
    items = toss("GET", "/api/v1/holdings", params={"symbol": symbol}, account=account).get("items") or []
    return int(float(items[0].get("quantity", 0))) if items else 0


def _buy(a, book, account, price) -> str:
    qty = a.qty
    if a.live:
        if qty * price > a.max_krw:
            return f"매수 건너뜀 ({qty}주 {qty*price:,.0f}원 > 한도 {a.max_krw:,.0f}원)"
        r = toss("POST", "/api/v1/orders", account=account,
                 body={"clientOrderId": f"jev-{uuid.uuid4().hex[:20]}", "symbol": a.symbol,
                       "side": "BUY", "orderType": "MARKET", "quantity": str(qty)})
        return f"매수 주문 {qty}주 (orderId {r['orderId'][:12]}…)"
    return f"모의 매수 {qty}주" if book.buy(qty, price) else "매수 불가 (모의 현금 부족)"


def _sell(a, book, account, price, holding) -> str:
    if a.live:
        r = toss("POST", "/api/v1/orders", account=account,
                 body={"clientOrderId": f"jev-{uuid.uuid4().hex[:20]}", "symbol": a.symbol,
                       "side": "SELL", "orderType": "MARKET", "quantity": str(holding)})
        return f"매도 주문 {holding}주 (orderId {r['orderId'][:12]}…)"
    q = book.qty
    return f"모의 매도 {q}주" if book.sell(price) else "대기"


def cmd_check(a) -> int:
    ok = True
    v = sys.version_info
    print(f"{'✓' if v >= (3, 9) else '✗'} Python {v.major}.{v.minor}" + ("" if v >= (3, 9) else "  → 3.9 이상이 필요해요"))
    ok &= v >= (3, 9)
    if _OPENROUTER:
        print("✓ Jev 경로: OpenRouter (typesafe/jev-1.13)")
    elif _VERCEL:
        print("✓ Jev 경로: Vercel AI Gateway")
    else:
        print("✗ Jev 키 없음  → export OPENROUTER_API_KEY=sk-or-...  (openrouter.ai/keys)")
        return 1
    try:
        r = systemone("대표님, 저희 AI 툴 홍보 협업 제안드립니다. 단가 알려주세요.",
                      parse_questions(["ad=브랜드 협업 제안이다"], None, None), retries=1)
        prob = (r.get("answers", {}).get("ad") or {}).get("noul")
        print(f"✓ Jev 호출 {r['_latency_ms']} ms · 협업 제안일 확률 {prob}")
    except Exception as e:  # noqa: BLE001
        print(f"✗ Jev 호출 실패: {e}  → 키가 맞는지, OpenRouter 크레딧이 남았는지 확인하세요")
        return 1
    toss = bool(os.environ.get("TOSSINVEST_CLIENT_ID") and os.environ.get("TOSSINVEST_CLIENT_SECRET"))
    print(("✓" if toss else "·") + " 토스증권 키 " + ("있음 (jev trade 가능)" if toss else "없음 — jev ask 만 쓸 거면 괜찮아요"))
    print("READY" if ok else "NOT READY")
    return 0 if ok else 1


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="jev", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ask", help="텍스트/JSON 에 대해 예·아니오/분류/점수를 받는다")
    s.add_argument("state", help="판단할 내용. '-' 는 stdin, '@파일' 은 파일")
    s.add_argument("--noul", action="append", metavar='NAME="지시문"')
    s.add_argument("--choice", action="append", metavar='NAME="지시문|키:설명,키:설명"')
    s.add_argument("--score", action="append", metavar='NAME="지시문|낮음;중간;높음"')
    s.add_argument("--compact", action="store_true", help="한 줄 JSON")
    s.add_argument("--pretty", action="store_true", help="사람이 읽는 형태(질문 → 답 · 확률 · 걸린 시간)")
    s.set_defaults(fn=cmd_ask)

    t = sub.add_parser("trade", help="토스증권 1분봉 → Jev 판단 → 모의/실주문")
    t.add_argument("symbol", help="종목코드 (005930) 또는 미국 티커 (AAPL)")
    t.add_argument("--every", type=float, default=5, help="판단 간격(초). 기본 5")
    t.add_argument("--count", type=int, default=30, help="Jev 에게 보여줄 1분봉 수. 기본 30")
    t.add_argument("--min-conf", type=float, default=0.8, help="오를(내릴) 확률이 이 이상일 때만 매수(매도). 기본 0.8")
    t.add_argument("--qty", type=int, default=1, help="매수 수량. 기본 1주")
    t.add_argument("--iterations", type=int, default=0, help="판단 횟수. 0 이면 멈출 때까지")
    t.add_argument("--cash", type=float, default=1_000_000, help="모의 시작 현금. 기본 100만 원")
    t.add_argument("--live", action="store_true", help="실제 주문. --max-krw 필수")
    t.add_argument("--max-krw", type=float, help="실주문 1회 금액 한도(원)")
    t.add_argument("--pretty", action="store_true", help="세로 화면 녹화용 두 줄 출력")
    t.set_defaults(fn=cmd_trade)

    c = sub.add_parser("accounts", help="토스증권 계좌 목록")
    c.set_defaults(fn=cmd_accounts)

    k = sub.add_parser("check", help="설치 확인: 파이썬·키·실제 Jev 호출 1회 → READY")
    k.set_defaults(fn=cmd_check)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except JevError as e:
        print(f"jev: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
