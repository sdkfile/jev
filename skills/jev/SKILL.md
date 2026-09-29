---
name: jev
description: Use when an agent needs a fast yes/no, category, or 0-N score with a confidence (triage mail, check if a comment wants a link, rate urgency) — Jev (TypeSafe) answers in ~0.3–0.6 s for a fraction of a cent, no text generation. Also runs a paper-trading demo on Toss Securities 1-minute candles.
---

# jev — hand small judgements to Jev

Jev ([TypeSafe AI](https://typesafe.ai/blog/introducing-system-one-models-and-jev)) is a decision
model. It does not write text: it answers **yes/no (`noul`)**, **picks a category (`choice`)** or
**gives a score (`score`)**, each with a probability. One call takes about 0.3–0.6 s.

Use it instead of asking a chat model "is this an ad email?" — because the answer is a probability,
code can set a threshold ("auto-handle above 0.9, otherwise ask the human").

All paths below are relative to this skill directory.

## Before the first run

```bash
python3 scripts/jev.py check
```

It must end with `READY`. It checks Python ≥ 3.9, finds a key and makes one real Jev call.
Keys are read from the environment, then `.env` next to this skill, then `~/.hermes/.env`.
The simplest key is `OPENROUTER_API_KEY` (routes to `typesafe/jev-1.13`). If a line fails,
show the user the `→` hint.

## Ask

```bash
python3 scripts/jev.py ask "<text to judge>" \
  --noul   'ad=This is a paid brand collaboration offer' \
  --choice 'kind=What is this mail|ad:collab offer,invoice:billing,spam:spam,other:other' \
  --score  'urgency=How urgently does it need a reply|not urgent;normal;reply today' \
  --compact
```

- JSON from stdin: `echo '{"comment":"..."}' | python3 scripts/jev.py ask - --noul '...' --compact`
- File: `python3 scripts/jev.py ask @mail.txt --choice '...'`
- Output (`--compact`): `{"answers": {...}, "latency_ms": N, "cost_usd": ...}`.
  `noul` → probability of yes. `choice` → `choice` + `probabilities`. `score` → float in 0..(levels-1).
- `--pretty` prints a human-readable version for the user.

Instructions may be in Korean or English. Several questions in one call are cheaper than several calls.

## Rules

- **Do not use it for writing, arithmetic, counting or date comparison** — the official docs say
  version 1.13 is weak there. Use it for judgement only.
- Report the probability, not just the label. Below ~0.7 say it is unsure and let the human decide.
- One-off platform notifications (e-sign, marketplace alerts) can look like ad offers to Jev —
  if the user wires it into a filter, suggest a low threshold and human review first.

## Trading demo (`trade`)

```bash
python3 scripts/jev.py trade 005930                 # paper trading, Samsung Electronics
```

Toss Securities Open API 1-minute candles → Jev decides up / down / unsure → paper buy/sell.
Needs `TOSSINVEST_CLIENT_ID` and `TOSSINVEST_CLIENT_SECRET`. **Default is paper trading.**
Real orders need `--live` + `--max-krw` + `TOSSINVEST_ACCOUNT` all together.
**Never add `--live` without the user explicitly asking for real orders and a KRW limit.**
This is not investment advice — nothing shows 1-minute direction calls make money.
