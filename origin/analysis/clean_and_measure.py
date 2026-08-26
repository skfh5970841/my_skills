# -*- coding: utf-8 -*-
"""
채사장 책 2권 OCR 정제 + 문체 정량 실측
입력: origin/의 OCR 마크다운 (표 아티팩트 포함)
출력: analysis/cleaned_*.txt (정제 본문), analysis/metrics.json, analysis/metrics_report.md

정제 전략:
- 표 셀을 행 단위로 이어붙임(공백 없이 — 한국어 공백이 이미 불신뢰적이므로)
- 구분자 라인(| --- |), 페이지 번호, 장식 노이즈, 삽화 오인식 블록 제거
- 문장 분리는 . ? ! 기준 (OCR에서 살아남는 신뢰 신호)

측정은 공백 비의존적으로:
- 문장 길이: 공백·문장부호 제외 글자 수
- 전환어/어휘: 부분열 매칭 (공백 무관)
"""
import re
import json
import unicodedata
from pathlib import Path

ORIGIN = Path(r"C:\Projects\my_skills\origin")
OUT = ORIGIN / "analysis"
OUT.mkdir(exist_ok=True)

BOOKS = {
    "jidaenolpyeop1": "지적 대화를 위한 넓고 얕은 지식 1 - 채사장.md",
    "simin": "시민의 교양-채사장.md",
}

HANGUL = re.compile(r"[가-힣]")

# 노이즈 패턴: 페이지 꼬리(책 제목 반복), 숫자만, ASCII 파편 등
FOOTER_PAT = re.compile(r"지적\s*대\s*화를?\s*위한\s*넓고\s*얄?[은아]*\s*지식|지적대화를위한넓고얕은지식")
PAGE_NUM = re.compile(r"^\s*\d{1,4}\s*$")


def normalize(s: str) -> str:
    # NFC 정규화 (OCR에서 자모 분리 케이스 방어)
    return unicodedata.normalize("NFC", s)


def clean_line_noise(line: str) -> bool:
    """라인 자체가 노이즈면 True (제거 대상)"""
    t = line.strip()
    if not t:
        return True
    if PAGE_NUM.match(t):
        return True
    if FOOTER_PAT.search(t.replace(" ", "")) and len(HANGUL.findall(t)) < 20:
        return True
    hangul = len(HANGUL.findall(t))
    # 문장부호를 포함한 짧은 파편은 경계 보존 가치가 있으므로 유지
    if re.search(r"[.!?]", t) and hangul <= 4:
        return False
    if hangul == 0:
        return True  # 숫자·기호·ASCII 파편 라인
    if hangul <= 1 and len(t) <= 3:
        return True  # 「 」, 0 같은 순수 파편
    return False


def extract_table_rows(text: str):
    """마크다운 표 행들을 읽기 순서대로 재구성.
    반환: [(row_index_in_file, joined_text)]"""
    rows = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            # separator row 스킵
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                i += 1
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            # 셀 내용 결합: 공백 없이 (단어 경계 정보는 이미 유실됨)
            joined = "".join(c for c in cells if c)
            rows.append(joined)
        else:
            if not clean_line_noise(line):
                rows.append(stripped)
        i += 1
    return rows


def is_garbage_block(joined: str) -> bool:
    """삽화 오인식 등 한글 비율이 낮은 블록 제거 (문장부호 보유 파편은 유지)"""
    if not joined:
        return True
    hangul = len(HANGUL.findall(joined))
    has_term = bool(re.search(r"[.!?]", joined))
    if hangul == 0 and not has_term:
        return True
    if hangul > 0 and hangul / max(len(joined), 1) < 0.45 and not has_term:
        return True
    if hangul == 0 and has_term and len(joined) <= 2:
        return False  # "다." 같은 경계 파편
    if hangul < 6 and not has_term:  # 너무 짧은 파편
        return True
    return False


def clean_book(path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    rows = extract_table_rows(text)
    cleaned = []
    for r in rows:
        r = normalize(r)
        r = FOOTER_PAT.sub("", r)
        if is_garbage_block(r):
            continue
        # 남은 잔여 기호 정리
        r = re.sub(r"[|＿_]{2,}", "", r)
        cleaned.append(r)
    return cleaned


# ---------- 측정 ----------

SENT_SPLIT = re.compile(r"[.!?]+")

TRANSITIONS = [
    "그리고", "하지만", "우선", "결국", "그렇다면", "그런데", "다만",
    "다음으로", "어쩌면", "예를 들어", "물론", "즉", "그러나", "그래서",
    "반대로", "왜냐하면", "흥미로운 것은", "흥미로운건", "사실", "다시 말해",
    "다시 말하면", "한편", "반면", "그러므로", "따라서", "게다가", "오히려",
]

READER_INCLUSION = ["당신", "우리", "여러분"]
ENUM_MARKERS = ["첫 번째", "두 번째", "세 번째", "첫째", "둘째", "셋째",
                "첫번째", "두번째", "세번째"]
QUOTE_MARKS = ['"', '"', "'", "'", '"']


def measure(name: str, sentences):
    total = len(sentences)
    lengths = []
    q_count = 0
    quote_count = 0
    text_all = "".join(sentences)
    no_space = text_all.replace(" ", "")

    for s in sentences:
        chars = len(re.sub(r"[\s.!?,'\"'\"()-]", "", s))
        if chars > 0:
            lengths.append(chars)
        if re.search(r"[?！]\s*$", s.strip()):
            q_count += 1
        if any(m in s for m in QUOTE_MARKS):
            quote_count += 1

    lengths_sorted = sorted(lengths)
    def pct(p):
        if not lengths_sorted:
            return 0
        idx = min(int(len(lengths_sorted) * p), len(lengths_sorted) - 1)
        return lengths_sorted[idx]
    avg = sum(lengths) / max(len(lengths), 1)

    per_10k = lambda c: round(c / max(len(no_space), 1) * 10000, 2)

    trans_counts = {}
    for t in TRANSITIONS:
        key_nospace = t.replace(" ", "")
        c = no_space.count(key_nospace)
        trans_counts[t] = {"count": c, "per_10k": per_10k(c)}

    metrics = {
        "corpus": name,
        "sentences": total,
        "chars_no_space": len(no_space),
        "sent_len_chars": {
            "mean": round(avg, 1),
            "p25": pct(0.25),
            "median": pct(0.5),
            "p75": pct(0.75),
            "p90": pct(0.9),
            "short_le15": round(sum(1 for l in lengths if l <= 15) / max(total, 1) * 100, 1),
            "short_le25": round(sum(1 for l in lengths if l <= 25) / max(total, 1) * 100, 1),
            "long_ge60": round(sum(1 for l in lengths if l >= 60) / max(total, 1) * 100, 1),
        },
        "question_ratio_pct": round(q_count / max(total, 1) * 100, 2),
        "quote_ratio_pct": round(quote_count / max(total, 1) * 100, 2),
        # 문장 말미 종결 분포 (공백 제거 상태에서 마지막 3글자 기준)
        "endings": {
            "da_다": round(sum(1 for s in sentences if s.replace(" ", "").rstrip(".!?").endswith("다")) / max(total, 1) * 100, 1),
            "rhetorical_question_markers_per10k": {
                m: per_10k(no_space.count(m)) for m in ["인가", "는가", "ㄴ가", "것인가", "어떤가"]
            },
        },
        "transitions": dict(sorted(trans_counts.items(), key=lambda kv: -kv[1]["count"])),
        "reader_terms_per10k": {t: per_10k(no_space.count(t)) for t in READER_INCLUSION},
        "enum_markers_count": {m: no_space.count(m.replace(" ", "")) for m in ENUM_MARKERS},
    }
    return metrics


def main():
    all_metrics = {}
    for key, fname in BOOKS.items():
        src = ORIGIN / fname
        print(f"[clean] {fname}")
        rows = clean_book(src)
        out_txt = OUT / f"cleaned_{key}.txt"
        out_txt.write_text("\n".join(rows), encoding="utf-8")

        big = "\n".join(rows).replace("\n", "")
        # 문장 분할: 종결부호를 보존하는 방식
        raw_sents = re.findall(r"[^.!?]*[.!?]+|[^.!?]+$", big)
        sents = [s.strip() for s in raw_sents if len(re.sub(r"[\s.!?]", "", s)) >= 2]
        m = measure(key, sents)
        all_metrics[key] = m
        print(f"  -> sentences={m['sentences']}, mean_len={m['sent_len_chars']['mean']}")

    (OUT / "metrics.json").write_text(
        json.dumps(all_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print("done ->", OUT / "metrics.json")


if __name__ == "__main__":
    main()
