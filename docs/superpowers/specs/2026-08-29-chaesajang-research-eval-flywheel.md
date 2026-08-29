# 채사장 계열 연구-평가 순환 루프 명세

## 목표

`chaesajang-family-optimizer`라는 별도 관리 스킬을 만든다. 이 스킬은 외부 방법론 조사와 현재 저장소의 관찰을 결합해 검증 가능한 개선 가설 하나를 만들고, 격리된 후보에서 수정·평가한 뒤 사용자 승인을 받은 경우에만 정본과 설치본에 반영한다.

성공 기준은 다음과 같다.

- fresh Codex 출력의 요청 충족, 의미·사실 보존, 논리·정보량이 유지되거나 개선된다.
- 채사장 계열의 사고·문체 동작이 개선되고 상투적·과잉 모사는 증가하지 않는다.
- 중요한 행동 변경은 사용자의 익명 블라인드 선호를 통과한다.
- 모든 판단은 연구 출처, 입력·출력 원문, 실행 명령, 모델·설정, 파일 해시로 재현할 수 있다.
- 승인 전에는 정본·패키지·설치본이 바뀌지 않는다.

## 확정된 범위

- 관리 대상: `chaesajang-advisor`, `chaesajang-style`, `chaesajang-dialogue`, `chaesajang-style-youtube-scripter`, `chaesajang-write-teacher`, `chaesajang-core`
- 관리 스킬: `chaesajang-family-optimizer`
- 정본: `chaesajang-family-v2` 아래의 단일 canonical source
- 생성물: Codex 어댑터, Claude 어댑터, `.skill` 패키지, 설치 미리보기
- 행동 평가 런타임: Codex만 사용
- Claude 지원: frontmatter, 참조, 디렉터리, 패키징의 정적 호환성만 검사
- 승인 전 자동화: 조사, 감사, 기준 출력, 격리 후보, 평가, 블라인드 자료, 보고서, 배포 미리보기
- 승인 필요: canonical promotion, 설치본 갱신, 외부 배포
- 인간 평가자: 초기에는 사용자 1인. 결과를 통계적 우월성으로 표현하지 않는다.
- 제외: 패밀리 내부 라우팅 정확도 최적화. 명시적 호출과 세션 연속성의 최소 smoke test만 유지한다.

## 구현 형태와 파일 소유권

기존 스킬 디렉터리를 대규모 이동하지 않는다. `family.yaml`이 정본과 생성물의 경계를 선언한다.

```text
chaesajang-family-v2/
  family.yaml
  chaesajang-core/                         # 공통 규칙의 유일한 사람이 편집하는 정본
  chaesajang-advisor/                      # 스킬별 고유 정본
  chaesajang-style/
  chaesajang-dialogue/
  chaesajang-style-youtube-scripter/
  chaesajang-write-teacher/
  chaesajang-family-optimizer/
    SKILL.md
    references/
      research-protocol.md
      evaluation-protocol.md
      promotion-policy.md
    scripts/
      loop.py                              # 사용자용 진입점
      optimizer_loop/                      # import 가능한 Python 패키지
  research/
    index.jsonl
    cards/
  evals/
    dev/
    golden/
    holdout/
  experiments/                             # 실행 산출물; 정본과 분리
  dist/                                    # 정본에서 생성한 어댑터·패키지
```

소유권 규칙:

1. 공통 규칙은 `chaesajang-core`에서만 사람이 편집한다.
2. 각 스킬 디렉터리에서 사람이 편집하는 것은 엔트리와 고유 reference뿐이다.
3. 공통 reference 사본, `skills/*.SKILL.md`, `.skill`, `dist/`, 설치본은 생성기로만 갱신한다.
4. 외부 설치본인 `chaesajang-write-teacher`는 원본을 바꾸지 않고 저장소 정본으로 한 번 가져온다.
5. 기존 `sync_core.py`는 전환 기간에 새 렌더러를 호출하는 호환 진입점으로 유지한다.

## 관리 스킬의 모드와 상태

`chaesajang-family-optimizer`는 대상 페르소나를 연기하지 않는 중립적인 연구자·실험 관리자다.

- `bootstrap`: 최초 전체 딥리서치, 정본 snapshot, 평가 자료 초기화
- `cycle`: 보충 조사부터 후보 보고서까지 한 회차 실행
- `resume`: 마지막 성공 단계부터 재개
- `report`: 상태를 바꾸지 않고 현재 결과만 출력
- `promote`: 승인된 후보만 정본·어댑터·설치본에 반영

```text
researching
  -> hypothesis_ready
  -> baseline_captured
  -> candidate_ready
  -> auto_evaluated
  -> awaiting_human | ready_for_approval
  -> promoted

어느 단계에서나 -> rejected | blocked_external | invalid
```

`resume`은 성공한 단계를 다시 실행하지 않는다. 실패 후보는 삭제하지 않고 원인과 함께 보존한다.

## 연구 프로토콜

최초 `bootstrap`은 다음을 폭넓게 조사한다.

- Agent Skill 설계, progressive disclosure, 컨텍스트 효율
- 프롬프트·에이전트 최적화와 eval-driven development
- 작가 문체 모방과 style-personalized text generation
- 인간 블라인드 평가, 자동 지표, LLM judge 편향
- 의미 보존, 사실성, 암기·과적합 방지

각 `cycle`은 마지막 조사 이후 새 자료와 현재 문제에 관련된 자료만 보충한다. 다음 경우에만 전체 조사를 다시 수행한다.

- 행동 평가 모델 또는 런타임이 크게 변경됨
- 핵심 연구 근거가 서로 충돌함
- 작가 코퍼스 또는 평가 과제가 크게 확장됨
- 사용자가 전체 재조사를 요청함

출처 우선순위는 공식 명세·공식 문서, 동료평가된 1차 연구, 신뢰할 수 있는 기술 보고서, 프리프린트·블로그 순이다. 프리프린트나 단일 블로그만으로 정본 변경 가설을 확정하지 않는다.

근거 카드의 필수 필드:

```yaml
claim: 검증 가능한 주장
source_url: 원문 URL
source_date: 원문 발표일
checked_at: 조사일
source_type: official | peer_reviewed | technical_report | preprint | blog
evidence: 원문에서 확인한 근거 요약
confidence: high | medium | low
local_evidence: 현재 파일·출력·실패 사례
decision_impact: 이 저장소에서 바뀔 수 있는 결정
proposed_test: 주장을 반증할 수 있는 테스트
```

현재 파일·출력과 연결되지 않는 자료는 `watchlist`에 남기고 후보 수정으로 승격하지 않는다.

## 가설 계약

한 실험은 하나의 instruction 묶음 또는 하나의 reference 선택 전략만 변경한다.

> 외부 근거와 현재 관찰 때문에, 정확히 이 규칙 묶음 하나를 변경하면 주평가 항목이 개선되고 보호 항목은 악화되지 않을 것이다.

`hypothesis.md`는 근거 ID, 변경·보호 범위, 주평가·보호 지표, 평가 사례, 위험 등급, 인간 블라인드 여부, 중단·기각 규칙을 명시한다. 수정 전 fresh baseline에서 약점이나 구조적 위험을 재현하지 못하면 정본을 변경하지 않는다.

## 평가 자료와 누출 방지

```text
evals/dev/       가설 작성과 조정에 사용
evals/golden/    모든 변경에서 보호할 알려진 실패·행동
evals/holdout/   최종 후보 판정 전까지 생성 에이전트에게 비공개
```

- 같은 책, 장, 연재, 개정본은 그룹 단위로 하나의 split에만 둔다.
- exact hash와 near-duplicate 검사를 split 전에 실행한다.
- 작가 문체 holdout은 `generator_brief`와 `evaluator_reference`를 분리한다.
- 생성 에이전트에는 중립적인 `generator_brief`만 제공한다.
- 실제 원문과 평가 전용 체크리스트는 평가 프로세스만 읽는다.
- holdout 자료가 후보 prompt, reference, 연구 카드에 노출되면 실험을 `invalid`로 바꾼다.
- 배포 가능한 데이터에는 전체 저작물 대신 provenance, hash, 허용된 짧은 발췌 또는 로컬 전용 경로를 저장한다.

## 평가 축과 실행 사다리

| 축 | 내용 | 역할 |
|---|---|---|
| request_fulfillment | 요청 형식과 과업 충족 | hard gate |
| meaning_and_facts | 의미·수치·인용·사실 보존 | hard gate |
| structure_and_information | 논리, 구조, 정보량 | 비교 지표 |
| style_behavior | 개념 도입, 관점 전환, 비유, 결론 동작 | 비교 지표 |
| over_imitation | 상투어, 과잉 철학화, 페르소나 누출 | 비교 지표 |
| resource_use | 로드 파일, 입력 토큰, 호출 수, 시간 | 보조 지표 |

평가는 비용이 싼 순서로 실행한다.

1. frontmatter, 참조, 정본 hash, 패키지, split 누출의 결정적 검사
2. 명시적 호출과 세션 연속성의 최소 smoke test
3. 모든 영향·보호 사례의 baseline/candidate fresh Codex 생성 1회
4. 통과 가능성이 있는 후보의 영향·보호 사례를 각각 총 3회 반복
5. 의미·사실 보존과 각 품질 축의 자동 평가
6. 위험 변경의 익명 인간 블라인드 평가

기준과 후보는 동일한 Codex 모델, reasoning 설정, 입력, 허용 reference를 사용한다. 불일치하면 비교를 `invalid`로 처리한다.

LLM judge는 인간 라벨에 대해 교정한 보조 신호다. A/B와 B/A를 모두 사용하고 길이 차이를 통제하거나 보고한다. LLM judge만으로 후보를 승격하지 않는다.

## 위험 분류와 인간 블라인드

문체, 페르소나, 출력 구조, 공통 코어 행동, reference 선택, 대화 연속성·handoff 변경은 인간 블라인드가 필수다. 오탈자, 깨진 경로, 동기화, 패키징처럼 출력 의미를 바꾸지 않는 변경은 자동 검사만 요구한다.

블라인드 패키지는 baseline/candidate의 정체를 숨기고 A/B와 B/A 순서를 균형 있게 제공한다. 사용자에게 유용성·완성도, 사고·문체 충실도, 과잉 모사, 의미 왜곡, 판단 근거 구절을 묻는다.

초기에는 사용자 1인의 판단을 사용하며, 통계적으로 유의한 개선이라고 표현하지 않는다.

## 페르소나 층위

- `chaesajang-advisor`, `chaesajang-dialogue`: 관점과 사고 페르소나
- `chaesajang-style`, `chaesajang-style-youtube-scripter`: 사고·구조·문체 기법, 전기적 역할극 제외
- `chaesajang-write-teacher`: 원리를 가르치되 역할극 제외
- `chaesajang-family-optimizer`: 중립적인 연구자·평가자

## 오류와 실패 처리

- Codex 또는 외부 명령의 비정상 종료·시간 초과·빈 출력: `blocked_external`
- provenance, 출력, score, 명령, hash 누락: `invalid`
- baseline/candidate 모델·설정 불일치: `invalid`
- 한 후보의 독립 변경이 둘 이상임: `invalid`
- holdout 누출: `invalid`
- hard gate 또는 golden 보호 사례 실패: `rejected`
- 인간 블라인드에서 후보 비선호: `rejected`

실패는 정본·설치본을 변경하지 않는다. 후보와 원인은 보존하고 새 실패 사례를 dev 또는 golden에 추가한다.

## 실험 산출물

```text
experiments/<experiment-id>/
  manifest.json
  research.jsonl
  hypothesis.md
  baseline.jsonl
  candidate.patch
  candidate.jsonl
  scores.json
  blind_pairs.jsonl
  human_ratings.jsonl
  report.md
```

현재 상태보다 뒤 단계의 파일은 없어도 된다. 이미 통과한 단계에 필요한 파일이 빠지면 `resume`과 승격을 금지한다.

## 승격과 배포

후보는 정적 gate, hard gate, golden 보호, 목표 품질 개선, 위험 변경의 사용자 블라인드 선호, provenance 완전성을 모두 만족할 때만 `ready_for_approval`이 된다.

`ready_for_approval`은 승격이 아니다. 사용자가 명시적으로 승인해야 다음 순서를 실행한다.

1. 후보 patch를 canonical source에 적용
2. 공통 reference와 Codex·Claude 어댑터 재생성
3. `.skill` 패키지와 manifest/hash 검증
4. Codex 행동 smoke test와 Claude 정적 검사 재실행
5. 승인 범위에 포함된 경우에만 설치본 교체
6. 승인·거부 이유와 새 회귀 사례 기록

## 우선 해결할 기반 문제

- 저장소에 없는 `chaesajang-write-teacher`를 canonical source에 편입
- 실제 스킬 폴더, `skills/*.SKILL.md`, `.skill`, 설치본의 드리프트를 단일 생성·검증 경로로 통합
- advisor 배포 snapshot의 잘못된 frontmatter가 다시 생성되지 않게 방지
- API 오류가 negative PASS가 될 수 있는 기존 trigger runner를 명시적 실패 의미로 교체
- 하드코딩 출력 통계를 fresh Codex generation 계약으로 교체
- FB-001~003을 원문을 덮어쓰지 않는 immutable golden 사례로 구조화
- 공통 코어의 물리 복제와 긴 로드 문제는 루프 구축 뒤 첫 행동 실험 후보로 다룸

## 주요 연구 근거

- https://agentskills.io/specification
- https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/docs/guides/evaluation-best-practices
- https://developers.openai.com/api/docs/guides/graders
- https://aclanthology.org/2025.findings-naacl.326/
- https://aclanthology.org/2025.findings-emnlp.532/
- https://aclanthology.org/2025.naacl-long.436/
- https://aclanthology.org/2025.ijcnlp-long.18/
