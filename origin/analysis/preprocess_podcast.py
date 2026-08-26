# -*- coding: utf-8 -*-
"""Phase A/B: 팟캐스트 자막 정제 + 질문 후보 추출
- [음악] 등 태그 제거, 광고 세그먼트 윈도우 제거
- 구두점이 없는 ASR 특성상 문장 분할 대신 질문 지표 어미 주변 윈도우 추출
"""
import re
from pathlib import Path

SRC = Path(r"C:\Projects\my_skills\origin\podcast")
OUT = Path(r"C:\Projects\my_skills\origin\analysis\podcast_clean")
OUT.mkdir(parents=True, exist_ok=True)

# 광고·프로모션 시드 키워드 → 주변 윈도우 삭제
AD_SEEDS = ["적중", "빅터 ", "퓨어체크", "목용용품", "프라에 온", "쓰리샷", "K본부",
            "뉴스 데스크를 나온", "풀리가 되", "구독과 이메일", "이벤트"]
TAG = re.compile(r"\[[^\]]{1,12}\]")

def clean(text: str) -> str:
    t = TAG.sub(" ", text)
    # 공백 정규화
    t = re.sub(r"\s+", " ", t)
    # 광고 시드 주변 ±250자 제거 (시드 여러 개면 반복)
    for seed in AD_SEEDS:
        while True:
            i = t.find(seed)
            if i < 0:
                break
            s = max(0, i - 250)
            e = min(len(t), i + len(seed) + 350)
            t = t[:s] + " " + t[e:]
            t = re.sub(r"\s+", " ", t)
    return t.strip()

# 질문 지표: 의문 종결 / 의문사 패턴
Q_PATTERNS = [
    r"[가-힣]{1,20}까[요]?",          # ~할까, ~습니까, ~까요
    r"[가-힣]{1,15}나[요]?",           # ~한나, ~있나
    r"[가-힣]{0,12}냐[고]?",           # ~하냐, ~냐고
    r"(?:무엇|뭐|누구|어디|언제|왜|어떻게|어떤|몇)[가-힣]{0,25}",
    r"[가-힣]{1,15}인가[요]?",
    r"[가-힣]{1,15}는가",
    r"[가-힣]{1,10}지[요]?[,\s]",      # ~하지(요), (의문 용법만 잡히도록 컨텍스트에서 필터링)
]
Q_RE = re.compile("|".join(Q_PATTERNS))

# 명확한 비의문 오탐 필터
FALSE_HINTS = ("알겠", "모르겠다 하", "아는 것 같", )

def extract_questions(t: str):
    out, seen = [], set()
    for m in Q_RE.finditer(t):
        s = max(0, m.start() - 70)
        ctx = t[s:m.end() + 40].strip()
        cand = m.group(0).strip()
        key = cand[:12]
        if key in seen:
            continue
        seen.add(key)
        out.append(ctx)
    return out

summary = []
for f in sorted(SRC.glob("*.txt")):
    raw = f.read_text(encoding="utf-8", errors="ignore")
    c = clean(raw)
    stem = re.sub(r"_자막\.txt$", "", f.stem).replace(".txt", "")
    (OUT / f"{stem}_clean.txt").write_text(c, encoding="utf-8")
    qs = extract_questions(c)
    qfile = OUT / f"{stem}_questions.txt"
    qfile.write_text("\n\n".join(f"[{i+1}] {q}" for i, q in enumerate(qs)), encoding="utf-8")
    summary.append((f.stem[:28], len(raw), len(c), len(qs)))

print(f"{'episode':30} {'raw':>7} {'clean':>7} {'질문후보':>5}")
for name, r, c, q in summary:
    print(f"{name:30} {r:7,} {c:7,} {q:5}")
tot_q = sum(s[3] for s in summary)
print(f"\n총 질문 후보: {tot_q}개")
