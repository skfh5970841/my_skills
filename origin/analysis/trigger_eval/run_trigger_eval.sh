#!/bin/bash
# chaesajang-style description 트리거 평가 스크립트
# 방법론: https://agentskills.io/skill-creation/optimizing-descriptions
# 요구: claude CLI (JSON 출력), jq. 다른 에이전트 클라이언트 사용 시 check_triggered만 교체.
#
# 사용: bash run_trigger_eval.sh [RUNS]
# RUNS: 질의당 반복 횟수 (기본 3)

QUERIES_FILE="$(dirname "$0")/eval_queries.json"
SKILL_NAME="chaesajang-style"
RUNS="${1:-3}"

check_triggered() {
  local query="$1"
  # Claude Code JSON 출력에서 Skill 도구 호출 감지.
  # 다른 클라이언트는 실행 로그에서 SKILL.md 로딩 여부로 판정하도록 이 함수만 교체할 것.
  claude -p "$query" --output-format json 2>/dev/null \
    | jq -e --arg skill "$SKILL_NAME" \
      'any(.. | objects | select(has("name")); .name == "Skill" and .input.skill == $skill)' \
    > /dev/null 2>&1
}

count=$(jq length <(jq '.queries' "$QUERIES_FILE"))
echo "총 ${count}개 질의 × ${RUNS}회 = $((count * RUNS)) 회 실행"

for i in $(seq 0 $((count - 1))); do
  query=$(jq -r ".queries[$i].query" "$QUERIES_FILE")
  should=$(jq -r ".queries[$i].should_trigger" "$QUERIES_FILE")
  id=$(jq -r ".queries[$i].id" "$QUERIES_FILE")
  triggers=0
  for run in $(seq 1 "$RUNS"); do
    check_triggered "$query" && triggers=$((triggers + 1))
  done
  rate=$(awk "BEGIN{printf \"%.2f\", $triggers/$RUNS}")
  pass="FAIL"
  if { [ "$should" = "true" ] && awk "BEGIN{exit !($triggers/$RUNS > 0.5)}"; } || \
     { [ "$should" = "false" ] && awk "BEGIN{exit !($triggers/$RUNS <= 0.5)}"; }; then
    pass="PASS"
  fi
  printf "q%-3s should=%-5s rate=%s %s | %s\n" "$id" "$should" "$rate" "$pass" "$(echo "$query" | head -c 40)"
done

echo ""
echo "판정: should-trigger는 rate>0.5, negative는 rate<=0.5가 PASS."
echo "실패한 should-trigger → description 확장 필요. 실패한 negative → 경계 문구 추가 필요."
