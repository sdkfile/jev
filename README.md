# jev

[Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)(TypeSafe AI)를 터미널과 AI 에이전트(Claude Code·Codex)에서 바로 쓰는 스킬이에요.

Jev는 글을 쓰지 않는 AI 모델이에요. **예/아니오, 분류, 점수**만 내놓고 답마다 확률을 붙여요.
그래서 빨라요 — 판단 한 번에 0.3~0.6초.

- `jev ask` — 아무 글이나 JSON을 주고 질문하면 확률이 붙은 답을 받아요. 에이전트가 "이거 광고 메일이야?", "이 댓글은 링크를 원해?" 같은 작은 판단을 Jev한테 넘길 때 써요.
- `jev trade` — 토스증권 1분봉을 Jev한테 보여주고 오를지·내릴지·모르겠는지 판단시켜 사고팔아요. **기본은 모의 투자**예요.

파이썬 표준 라이브러리만 써요. 설치할 패키지가 없어요.

## 1. 키 준비

[OpenRouter](https://openrouter.ai/keys) 키 하나면 돼요. Jev는 OpenRouter에서 `typesafe/jev-1.13`으로 불러요.

```bash
export OPENROUTER_API_KEY=sk-or-...        # ~/.zshrc 에 넣어두면 매번 안 쳐도 돼요
```

키는 환경변수 → 스킬 폴더의 `.env` → `~/.hermes/.env` 순서로 찾아요.
Vercel AI Gateway 키(`AI_GATEWAY_API_KEY`)가 있으면 그쪽을 먼저 써요. 단 Vercel 무료 등급은 403이 나요.

토스 자동매매 데모까지 쓰려면(선택) 토스증권 WTS → 설정 → Open API에서 발급해요.

```bash
export TOSSINVEST_CLIENT_ID=...
export TOSSINVEST_CLIENT_SECRET=...
```

## 2. 설치

### Claude Code

```bash
claude plugin marketplace add sdkfile/jev
claude plugin install jev@jev
```

### Codex

```bash
codex plugin marketplace add sdkfile/jev
codex plugin add jev@jev
```

### 플러그인 없이 스킬만

```bash
git clone https://github.com/sdkfile/jev.git
cp -r jev/skills/jev ~/.claude/skills/     # Claude Code
cp -r jev/skills/jev ~/.agents/skills/     # Codex
cp -r jev/skills/jev ~/.hermes/skills/     # Hermes
```

## 3. 설치 확인

```bash
python3 ~/.claude/skills/jev/scripts/jev.py check
```

마지막 줄이 `READY`면 끝이에요. 실제로 Jev를 한 번 불러서 걸린 시간까지 보여줘요.

```
✓ Python 3.9
✓ Jev 경로: OpenRouter (typesafe/jev-1.13)
✓ Jev 호출 335 ms · 협업 제안일 확률 0.9
· 토스증권 키 없음 — jev ask 만 쓸 거면 괜찮아요
READY
```

## 4. 쓰는 법

### 에이전트에게 말로 시키기

- "jev로 이 메일 광고 협업 제안인지 봐줘"
- "jev로 이 댓글들 중에 자료 링크 원하는 것만 골라줘"
- "받은편지함 최근 20통 jev로 종류별로 나눠줘"

에이전트가 스킬을 읽고 `jev ask`를 불러요. 확률이 낮은 건 "애매하다"고 따로 알려줘요.

### 직접 명령으로

```bash
cd skills/jev

# 메일 분류
python3 scripts/jev.py ask "대표님, 저희 AI 툴 홍보 협업 제안드립니다. 단가 알려주세요." \
  --choice 'kind=메일 종류|ad:광고 협업,invoice:정산,spam:스팸,other:기타' \
  --noul 'reply=사람이 직접 답장해야 한다' --pretty

#   reply  →  예  (61%)
#   kind   →  ad  (100%)
#   ⏱ 0.65초

# 댓글이 링크를 원하는지 (에이전트가 쓰기 좋은 JSON)
echo '{"comment":"자료 받을 수 있을까요?"}' | \
  python3 scripts/jev.py ask - --noul 'wants_link=댓글 작성자가 자료 링크를 원한다' --compact
# {"answers": {"wants_link": {"type": "noul", "noul": 0.82}}, "latency_ms": 499, ...}
```

질문 형식은 세 가지예요.

| 옵션 | 모양 | 결과 |
|---|---|---|
| `--noul` | `이름=지시문` | 예일 확률 0~1 |
| `--choice` | `이름=지시문\|키:설명,키:설명` | 고른 키 + 키별 확률 |
| `--score` | `이름=지시문\|낮음;중간;높음` | 0~(단계-1) 점수 + 단계별 확률 |

질문 여러 개를 한 번에 넣으면 호출 한 번으로 끝나요.

## 5. 토스증권 모의투자 데모

```bash
python3 scripts/jev.py trade 005930        # 삼성전자, 5초마다 판단, 오를 확률 80% 넘으면 1주 모의 매수
```

- 기본은 모의 투자예요. 가상 현금 100만 원으로 시작하고 상태는 `~/.jev/paper-<종목>.json`에 남아요.
- 실주문은 `--live`, `--max-krw`(1회 금액 한도), `TOSSINVEST_ACCOUNT` 셋이 다 있어야 돌아가요.
- 주문마다 멱등성 키를 붙여 재시도해도 두 번 주문되지 않아요.
- 모든 판단과 주문은 `~/.jev/trade-<종목>.jsonl`에 남아요.

**투자 권유가 아니에요.** Jev 공식 문서도 1.13 버전은 계산·숫자 세기에 약하다고 적고 있고, 1분봉 방향 맞히기로 돈을 번다는 근거는 없어요. 데모와 실험용이에요.

### 장 마감 뒤에 그날 시세로 다시 돌리기

장이 닫힌 뒤에도 그날 1분봉을 받아둔 JSON으로 똑같이 돌려볼 수 있어요. 주문은 받지 않아요(모의 전용).

```bash
python3 examples/replay_toss.py examples/candles-005930-0928.json 18802 08:24 &
TOSSINVEST_BASE_URL=http://127.0.0.1:18802 TOSSINVEST_CLIENT_ID=x TOSSINVEST_CLIENT_SECRET=y \
  python3 skills/jev/scripts/jev.py trade 005930 --every 2 --min-conf 0.5 --pretty
```

토스 키 없이 끝까지 돌려보려면 가짜 토스 서버 `examples/fake_toss.py`를 써요.

## 6. 한계와 주의

- 글을 써야 하는 일, 계산·숫자 세기·날짜 비교에는 쓰지 마세요. 판단만 맡기세요.
- 확률이 낮게 나온 건 사람이 한 번 더 보세요. 실제로 전자서명·플랫폼 자동 알림 메일을 광고 제안으로 높게 읽은 적이 있어요.
- 필터로 붙일 땐 문턱을 낮게 잡고 걸러진 걸 사람이 보는 식으로 시작하세요.

## 라이선스

MIT. Jev와 TypeSafe는 TypeSafe AI의 상표예요. 이 리포는 TypeSafe와 관련 없는 개인 프로젝트예요.
