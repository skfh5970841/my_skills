# -*- coding: utf-8 -*-
"""run_trigger_eval.py — chaesajang 계열 description 트리거 평가 (jq 없는 환경용)

방법론: https://agentskills.io/skill-creation/optimizing-descriptions
사용: python run_trigger_eval.py [RUNS] [TARGET_SKILL]
  RUNS         질의당 반복 횟수 (기본 1. 가이드 권장은 3)
  TARGET_SKILL 기본 chaesajang-style. 'any'면 계열 4종 중 무엇이든 트리거되면 성공으로 판정.

요구: claude CLI에 API 크레딧이 있어야 한다 ("Credit balance is too low" 시 실행 불가).
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
QUERIES = json.loads((HERE / "eval_queries.json").read_text(encoding="utf-8"))["queries"]

FAMILY = ["chaesajang-style", "chaesajang-advisor",
          "chaesajang-dialogue", "chaesajang-style-youtube-scripter"]


def find_skill_calls(obj, found):
    """JSON 구조를 재귀 순회하며 Skill 도구 호출의 input.skill 수집"""
    if isinstance(obj, dict):
        if obj.get("name") == "Skill" or obj.get("type") == "tool_use" and "skill" in str(obj.get("input", {})):
            inp = obj.get("input")
            if isinstance(inp, dict) and inp.get("skill"):
                found.append(inp["skill"])
        for v in obj.values():
            find_skill_calls(v, found)
    elif isinstance(obj, list):
        for v in obj:
            find_skill_calls(v, found)


def check_triggered(query: str):
    try:
        r = subprocess.run(
            ["claude", "-p", query, "--output-format", "json", "--max-turns", "1"],
            capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="ignore")
    except subprocess.TimeoutExpired:
        return None, "timeout"
    out = r.stdout.strip()
    if not out:
        return None, f"no-output stderr={r.stderr[:120]}"
    # JSON 복원: result 필드 안에 이스케이프된 JSON이 있을 수 있어 원문에서도 탐색
    skills = []
    try:
        data = json.loads(out)
        find_skill_calls(data, skills)
    except json.JSONDecodeError:
        pass
    for s in FAMILY:
        if s in out and ("Skill" in out or "skill" in out):
            if s not in skills:
                skills.append(s)
    return skills, None


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    target = sys.argv[2] if len(sys.argv) > 2 else "chaesajang-style"
    print(f"총 {len(QUERIES)}질의 × {runs}회 / target={target}\n")
    results = []
    for q in QUERIES:
        triggers = 0
        err = None
        for _ in range(runs):
            skills, e = check_triggered(q["query"])
            if e:
                err = e
                break
            hit = any(s in FAMILY for s in skills) if target == "any" else target in skills
            triggers += 1 if hit else 0
        rate = triggers / runs
        should = q["should_trigger"]
        ok = (rate > 0.5) if should else (rate <= 0.5)
        results.append((q["id"], q["query"][:36], should, rate, ok))
        flag = "PASS" if ok else "FAIL"
        print(f"q{q['id']:<3} want={'T' if should else 'F'} rate={rate:.2f} {flag:4} | {q['query'][:40]}")

    n_pass = sum(1 for r in results if r[4])
    print(f"\n통과 {n_pass}/{len(results)}")
    fails = [r for r in results if not r[4]]
    if fails:
        print("실패 질의:", [f"q{r[0]}" for r in fails])
        print("- should-trigger 실패 → description 확장 필요")
        print("- negative 실패 → 경계 문구 필요")


if __name__ == "__main__":
    main()
