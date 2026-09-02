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


def invoke(query: str):
    """Run one legacy Claude trigger probe without a shell."""
    return subprocess.run(
        ["claude", "-p", query, "--output-format", "json", "--max-turns", "1"],
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="ignore",
        shell=False,
    )


def check_triggered(query: str):
    try:
        r = invoke(query)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as error:
        return None, f"invoke-error={type(error).__name__}: {error}"
    if r.returncode != 0:
        return None, f"nonzero-exit={r.returncode} stderr={r.stderr[:120]}"
    out = r.stdout.strip()
    if not out:
        return None, f"no-output stderr={r.stderr[:120]}"
    skills = []
    try:
        data = json.loads(out)
    except json.JSONDecodeError as error:
        return None, f"malformed-output={error.msg}"
    if not isinstance(data, (dict, list)):
        return None, "malformed-output=top-level JSON must be an object or array"
    find_skill_calls(data, skills)
    # Some valid legacy payloads carry a serialized tool event inside `result`.
    for s in FAMILY:
        if s in out and ("Skill" in out or "skill" in out):
            if s not in skills:
                skills.append(s)
    return skills, None


def evaluate_case(case: dict, runs: int, target: str) -> dict:
    """Evaluate all repeats, blocking the whole case on any incomplete repeat."""
    if not isinstance(runs, int) or isinstance(runs, bool) or runs <= 0:
        raise ValueError("runs must be a positive integer")
    triggers = 0
    completed_runs = 0
    for _ in range(runs):
        skills, error = check_triggered(case["query"])
        if error:
            return {
                "id": case["id"],
                "status": "blocked_external",
                "passed": False,
                "trigger_rate": None,
                "completed_runs": completed_runs,
                "error": error,
            }
        completed_runs += 1
        hit = any(skill in FAMILY for skill in skills) if target == "any" else target in skills
        triggers += 1 if hit else 0
    rate = triggers / runs
    should = case["should_trigger"]
    passed = (rate > 0.5) if should else (rate <= 0.5)
    return {
        "id": case["id"],
        "status": "completed",
        "passed": passed,
        "trigger_rate": rate,
        "completed_runs": completed_runs,
        "error": None,
    }


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    runs = int(args[0]) if args else 1
    target = args[1] if len(args) > 1 else "chaesajang-style"
    print(f"총 {len(QUERIES)}질의 × {runs}회 / target={target}\n")
    results = []
    for q in QUERIES:
        result = evaluate_case(q, runs, target)
        results.append(result)
        if result["status"] == "blocked_external":
            print(
                f"q{q['id']:<3} want={'T' if q['should_trigger'] else 'F'} "
                f"rate=-- BLOCKED | {q['query'][:40]} | {result['error']}"
            )
            continue
        flag = "PASS" if result["passed"] else "FAIL"
        print(
            f"q{q['id']:<3} want={'T' if q['should_trigger'] else 'F'} "
            f"rate={result['trigger_rate']:.2f} {flag:4} | {q['query'][:40]}"
        )

    n_pass = sum(1 for result in results if result["passed"])
    print(f"\n통과 {n_pass}/{len(results)}")
    fails = [result for result in results if not result["passed"]]
    if fails:
        print("실패 질의:", [f"q{result['id']}" for result in fails])
        print("- should-trigger 실패 → description 확장 필요")
        print("- negative 실패 → 경계 문구 필요")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
