# description_review.md — 트리거 설계 검토 (optimizing-descriptions 방법론 대비)
작성: 2026-08-26 / 관련 근거: sources/agentskills_optimizing-descriptions.md

> **상태 업데이트 (2026-08-26)**: §1의 개선안 descriptions 양 스킬에 적용 완료
> (style: 경계 문구 추가, advisor: 폴백 라인 추가). 길이 검증 257자·382자 ✅.
> 남은 절차는 §2의 트리거 평가 실행뿐.

## 1. 현재 description 진단

### chaesajang-style
> "채사장(『지대넓얕』 저자)의 문체로 글을 쓰거나 변환할 때 사용한다. '채사장 스타일로 써줘', '지대넓얕 스타일'처럼 직접 요청하거나, '쉽고 깊게 써줘', '교양 글쓰기', '지적인 에세이로 풀어줘', '개념을 에세이처럼 설명해줘'처럼 문체가 암시된 경우에도 사용한다. 역사·철학·경제·과학 개념을 일반 독자에게 설명하는 글쓰기와 기존 글의 변환을 모두 다룬다."

| 가이드 원칙 | 평가 |
|---|---|
| 명령형("사용한다") | ✅ |
| 사용자 의도 중심 | ✅ 발화 예시 나열 |
| Pushy함(키워드 미언급 시에도) | ✅ "암시된 경우에도" |
| 간결성(<1024자) | ✅ ~240자 |
| 경계 명시 | ⚠️ 구조 잡기·브레인스토밍이 advisor로 감다는 안내 없음 |

**개선안** (경계 문구 추가):
```
description: "채사장(『지적 대화를 위한 넓고 얕은 지식』 저자)의 문체로 글을 쓰거나 기존 글을 변환할 때 사용한다. '채사장 스타일로 써줘', '지대넓얕 스타일'처럼 직접 요청하거나, '쉽고 깊게 써줘', '교양 글쓰기', '지적인 에세이로 풀어줘'처럼 문체만 암시된 경우에도 사용한다. 역사·철학·경제·과학 개념을 일반 독자에게 설명하는 글과 기존 글의 변환을 다룬다. 단, 아이디어 단계의 자문이나 개요·구조 설계는 chaesajang-advisor 스킬이 담당한다."
```

### chaesajang-advisor
현재: 모드(CONSULT/OUTLINE/WRITE)와 트리거 별칭 중심. WRITE 신호에 "변환해줘" 포함 → style과 겹치는 영역.

**개선안** (경계 상호 참조 추가, 말미 한 줄):
```
... 문체 재현 자체는 chaesajang-style 스킬의 레퍼런스를 로딩해 수행한다.
```
→ 이미 Step 3에서 경로 연결됨. description에도 한 줄 추가하면 트리거 충돌 시 폴백이 명확해짐.

## 2. 실행 절차 (사용자)
1. `analysis/trigger_eval/eval_queries.json` 준비 완료 (should 9 + near-miss 11 = 20개)
2. `bash run_trigger_eval.sh 3` 실행 (claude CLI+jq 환경; 다른 클라이언트면 check_triggered 함수만 교체)
3. 실패 질의가 나오면 위 개선안 description으로 교체 후 재실행 (train/validation 분리 권장: 12개 train / 8개 validation)

## 3. 판정 기준
- should-trigger rate > 0.5 → PASS
- negative(near-miss) rate ≤ 0.5 → PASS
- 5회 반복 최적화 후 validation pass rate로 최종 선택
