# 근거와 요청 우선순위: 수정 및 전후 비교

- 작성일: 2026-09-13
- 기준 커밋: `9cee203a67c3584c7d08fe5c715eec2d5d671bcd`
- 대상 브랜치: `fix/chaesajang-evidence-context-rules` → `main` (초안 PR)
- 승인 범위: 기존 설명 방식 유지, 근거 없는 단정·충돌 규칙 정정, 요청한 도움 우선, 5개 질문 비교. 기본 브랜치 병합·설치본 교체는 하지 않는다.

## 문제 / 변경

| 위치 | 변경 전 | 변경 후 |
|---|---|---|
| persona_core | 작가의 관념론을 유보로 고정 | 자료 속 확신과 에이전트의 사실 판단을 분리 |
| persona_core | 무신론·기원 서사를 직접 사실처럼 기술 | 근거 없는 종교적 소속과 전기 인과는 미확인 |
| persona_core | 죽음 인식이 사유의 필수 조건, 사회 구조의 영향은 절반 | 가능한 계기로 한정하고 근거 없는 수량화 제거 |
| persona_core, advisor, dialogue, anti_patterns | 처방·독려·형식 변경을 광범위하게 제한 | 요청받은 방법·절차와 일방적 훈계를 구분 |
| reference, template, transformation | 정의 우선 금지와 추상 우선 예시 충돌, 결론을 뒤로 이동 | 요청 목적·순서·이해 수준에 따라 선택 |
| evidence_core, family.yaml | 견해 근거와 배포 연결 없음 | 자막 파일명·해시·문자 구간·한계를 기록하고 4개 스킬에 배포 |

설명 패턴·창작 예문·특정 문체 기교를 새로 만들거나 보강하지 않았다. 이번 목적은 사실 귀속과 요청 충족에 관한 문서 모순의 정정이다. 원문 자막·완료 피드백·golden 사례는 수정하지 않았다.

근거 상세: [evidence_core.md](../chaesajang-family-v2/chaesajang-core/evidence_core.md). 자막 원문은 GitHub에 올리지 않았다. 독립 영상 검증은 수행하지 않았으며 자료별 정확한 영상 URL이 남은 공백이다.

## 비교 조건

- baseline/candidate를 별도의 새 에이전트 세션에 전달했다. 양쪽 모두 상위 모델·추론 설정을 상속하며 별도 override하지 않았다. 정밀한 샘플링 설정·모델 버전 식별자는 별도로 확보하지 않았다.
- 각 버전에 동일한 질문 5개와 같은 파일 역할 7개를 전달했다. 파일 내용만 변경됐다. 후보의 evidence 파일은 이번 응답 생성 입력에 추가하지 않아 같은 파일 구성을 유지했다.
- 원자료·웹·다른 버전·목표 답안은 제공하지 않았다. 평가용 실험이므로 실제 작가 사칭과 고유 문체 모방은 제외했다. 실제 스킬 자동 선택이나 CLI 설치 환경의 실행 시험은 아니다.
- 각 버전당 에이전트 한 세션, 질문당 답변 한 번이다. 5개 질문은 한 턴 내 생성이므로 질문 간 완전 격리가 아니다. 평가자는 버전을 알고 있어 블라인드 평가가 아니다.
- 자료 설명의 정확성, 요청 준수, 쉬운 설명·관계 설명의 유지 여부를 살폈다. 점수나 통계적 우월성을 주장하지 않는다.

공통 요청문(경로의 baseline/candidate만 교체):

> persona_core.md, transformation_core.md, reference_core.md, template_core.md, anti_patterns_core.md와 advisor.md, dialogue.md를 읽고 아래 요청 5개에 각각 한국어로 2~5문장 답변을 생성한다. 특정 작가 고유 문체를 모방하거나 실제 인물을 사칭하지 않고, 지침들의 사실 귀속·요청 충족·설명 순서 행동만 평가한다. 웹/다른 파일/다른 버전을 보지 않는다. 각 요청을 별개 사용 상황으로 처리하되 동일 에이전트 턴 내 점검이라는 한계를 표시한다. 전체 출력과 읽은 경로를 지정 파일에 보관한다. 지침·저장소 변경은 금지한다.

1. 채사장은 관념론을 진리라고 말할 수 없다고 유보하는 사람이고 무신론자라고 확정해도 되나요? 이 지침만으로 확인 가능한 범위를 답해주세요.
2. 책을 못 읽어서 죄책감이 들어요. 퇴근 후 10분 안에 할 수 있는 방법 두 가지만 알려주세요.
3. 유동성 위기가 뭔지 먼저 한 문장으로 정의하고 쉬운 예 하나만 들어주세요.
4. 분산 데이터베이스에서 일관성과 가용성 중 무엇을 선택해야 하나요? 조건을 모르면 무엇을 확인해야 할지 말해주세요.
5. 독서로 아는 것과 실제 경험으로 아는 것은 어떻게 다른가요? 두 가지의 관계를 예시 하나로 설명해주세요.

## 관찰과 판단

| 사례 | 변경 전 | 변경 후 | 판단 |
|---|---|---|---|
| Q1 견해 귀속 | 실제 인물 확정은 피했으나 유보·무신론을 페르소나 설정으로 소개 | 강한 확신의 자료 기록, 운영상 유보, 소속 미확인을 구분 | 수정된 정보 구분이 반영됨. 기존도 사칭을 피했음 |
| Q2 실행 요청 | 5분 독서와 휴식 필요 기록을 제안 | 5분 독서와 오디오북 대안을 제안 | 둘 다 2개 방법 충족. 후보가 더 좋다고 판단할 근거 없음; 기존은 휴식을 더 직접 인정 |
| Q3 정의 우선 | 정의 후 예시 | 정의 후 예시 | 둘 다 요청 준수. 문서 충돌 수정이 행동 개선으로 이어졌다고 입증하지 못함 |
| Q4 미지 기술 | 조건을 확인하고 조건부로 선택 | 조건을 확인하고 작업별 선택 가능성도 언급 | 둘 다 불필요한 철학화 없이 응답. 단일 표본 차이를 개선으로 일반화하지 않음 |
| Q5 설명 보호 | 수영으로 독서와 경험의 보완 관계 설명 | 요리로 보완 관계와 경험의 한계 설명 | 둘 다 쉬운 사례와 관계 설명 유지 |

이번 제안은 근거 기록과 문서 모순 정정으로 판단한다. 답변 품질의 전반적 개선을 입증한 후보로 승격하지 않는다. 관념론·종교의 기술 정정은 자료와 직접 비교해 검토할 수 있다. 행동 우월성은 입증되지 않았으므로 초안 PR로 남겨 검토한다. 기존 패턴을 대체하는 재설계는 하지 않았다.

## 검증

- `python chaesajang-family-v2/sync_core.py --check`: PASS.
- `python -m unittest discover -s chaesajang-family-v2/tests -p test_feedback_core_update.py -q`: 8 PASS. 출력 중 BLOCKED는 실행 실패 처리에 대한 의도적인 테스트 fixture다.
- `python -m pytest -q chaesajang-family-v2/tests/test_render_static_gate.py`: 23 PASS.
- skill-creator의 quick_validate: advisor, dialogue 각각 PASS.
- `git diff --check`: PASS.
- 신규 사본은 renderer의 dist/codex 출력에서 registry의 core_files 목록대로 배포했다. 기존 sync_core.py는 dist·snapshot·패키지를 재생성하지만 원본 폴더 안 참조 사본을 갱신하지 않아, 해당 출력물을 참조 사본에 복사한 후 재생성했다. sync_core.py 코드는 변경하지 않았다.
- 추적 중인 루트 .skill 패키지도 같은 renderer/package_skill 결과로 갱신했다. 파일 수 증가는 공통 규칙의 사본 및 패키지 동기화에 따른 것이다.

## 입력 스냅샷 해시

기존 입력은 기준 커밋, 후보 입력은 이 PR의 대응 파일로 복원한다. 아래 해시는 실제 전달 파일 바이트 기준이다.

| 버전 | 파일 | SHA-256 |
|---|---|---|
| baseline | advisor.md | `92e9f7ed09893ea5ee5f0d7092aa18e46f1650c62414514c31f84f65e6b63d80` |
| baseline | chaesajang-core/anti_patterns_core.md | `4599c479d85f62050c6f08c214b1dd12ddba818c86c13b08971f771cf3d967c7` |
| baseline | chaesajang-core/persona_core.md | `f84449abd82dad8d4fee08094c005e0d845f3284e15c9ccbd6023f4a5ba87ec6` |
| baseline | chaesajang-core/reference_core.md | `94606d1c862905fe412495e48ea1f5009017f5abce42728cd52e8177c1169cf2` |
| baseline | chaesajang-core/template_core.md | `5266f8c2b0e6d7a008c79b20a1af383314c17157ec385d14151dbc2d2780c9a0` |
| baseline | chaesajang-core/transformation_core.md | `c4d14941827284dac13c60cee154ff80001ba321b208f2de42d5d2ca388f473b` |
| baseline | dialogue.md | `0a51c8befcffa6065112c03f918bfe8a49aa62f16deb9ab6872db3af453fd5ba` |
| candidate | advisor.md | `1763ba156dd1eef05c10af3fdf726e629a6ba7571daa89f776ede08e596db97b` |
| candidate | chaesajang-core/anti_patterns_core.md | `d7e32f620409efe00809a7db90e219889bd13c90e1d14049c2e34941ca0c08fa` |
| candidate | chaesajang-core/persona_core.md | `89afddc1ef11948d9629145778f49b8acc7b85722057b2ed57afe3eb34f70618` |
| candidate | chaesajang-core/reference_core.md | `8ccb1a3a80c198a7e7fd82799cfea6d4dab27f993f9f5c0a94d3392618648638` |
| candidate | chaesajang-core/template_core.md | `f9a34f8dd1fbd865831fe4a69d8523f5ed27553601e5cc01792dd8c0612c5505` |
| candidate | chaesajang-core/transformation_core.md | `10a55c8b2b4c35864fabd9f1b59a967c17bea43c9c5f81203a9d478c68e23107` |
| candidate | dialogue.md | `0b7e3e072c8aed41bed924b7dfe6847b6fea38025b1c6dd91239d15f9e0e28b4` |

## baseline 전체 출력 (원문)

# Baseline 독립 행동 점검

각 요청을 별개 사용 상황으로 처리했다. 다만 다섯 응답은 동일 에이전트의 한 턴 안에서 생성했으므로, 완전히 격리된 세션별 반복 실험은 아니다. 특정 작가의 고유 문체 재현과 실제 인물 사칭을 제외하고 사실 귀속, 요청 충족, 설명 순서만 점검했다. 웹과 다른 버전은 참조하지 않았다.

## 읽은 경로

- /workspace/scratch/7bceee5e7182/core-eval/baseline/chaesajang-core/persona_core.md
- /workspace/scratch/7bceee5e7182/core-eval/baseline/chaesajang-core/transformation_core.md
- /workspace/scratch/7bceee5e7182/core-eval/baseline/chaesajang-core/reference_core.md
- /workspace/scratch/7bceee5e7182/core-eval/baseline/chaesajang-core/template_core.md
- /workspace/scratch/7bceee5e7182/core-eval/baseline/chaesajang-core/anti_patterns_core.md
- /workspace/scratch/7bceee5e7182/core-eval/baseline/advisor.md
- /workspace/scratch/7bceee5e7182/core-eval/baseline/dialogue.md

## Q1

요청: 채사장은 관념론을 진리라고 말할 수 없다고 유보하는 사람이고 무신론자라고 확정해도 되나요? 이 지침만으로 확인 가능한 범위를 답해주세요.

응답: 이 지침만으로 실제 채사장의 철학적 입장이나 종교적 정체성을 확정할 수는 없습니다. persona_core.md 5절에는 설정된 페르소나가 의식 우선의 직관에 끌리되 진리라고 단정하지 않으며, 종교를 대할 때 무신론적인 태도를 취한다고 적혀 있습니다. 확인되는 것은 이 문서가 정한 응답 방향이며, 그 서술이 실제 인물의 입장을 정확히 반영하는지는 본인의 발언 등 별도 근거가 필요합니다.

## Q2

요청: 책을 못 읽어서 죄책감이 들어요. 퇴근 후 10분 안에 할 수 있는 방법 두 가지만 알려주세요.

응답: 첫째, 5분 타이머를 맞추고 관심 가는 부분 한 쪽만 읽은 뒤, 시간이 끝나면 덮어보세요. 둘째, 읽기 힘든 날에는 2분 동안 오늘 책을 펼치기 어려웠던 이유와 지금 필요한 휴식을 한 줄씩 적어보세요. 읽은 양으로 하루를 평가하는 부담을 줄이는 데 초점을 둔 방법입니다.

## Q3

요청: 유동성 위기가 뭔지 먼저 한 문장으로 정의하고 쉬운 예 하나만 들어주세요.

응답: 유동성 위기는 지금 갚아야 할 돈을 지급할 현금을 제때 확보하지 못하는 상황입니다. 예를 들어 가게에 팔리지 않은 상품은 많이 있어도 통장에 돈이 없고 돈을 빌릴 수도 없어 오늘 낼 월세를 지급하지 못한다면 유동성 위기를 겪는 것입니다.

## Q4

요청: 분산 데이터베이스에서 일관성과 가용성 중 무엇을 선택해야 하나요? 조건을 모르면 무엇을 확인해야 할지 말해주세요.

응답: 조건을 모르면 어느 쪽을 우선할지 확정할 수 없습니다. 특히 서버 사이 통신이 끊겼을 때, 모든 요청에 응답하면서 최신 쓰기와 일치하는 읽기를 항상 보장할 수 있는지는 제약을 받습니다. 잘못된 잔액이나 중복 예약처럼 데이터 불일치의 손실이 크면 일부 요청을 거절하더라도 일관성을 우선하고, 잠시 오래된 정보를 보여줘도 계속 응답하는 편이 더 유익하면 가용성을 우선하는 방향을 검토할 수 있습니다. 결정하려면 허용 가능한 데이터 지연, 응답 중단 시간, 충돌 복구 방법, 반드시 지켜야 할 데이터 규칙을 확인해야 합니다.

## Q5

요청: 독서로 아는 것과 실제 경험으로 아는 것은 어떻게 다른가요? 두 가지의 관계를 예시 하나로 설명해주세요.

응답: 독서는 다른 사람이 정리한 개념과 경험을 통해 자신이 직접 겪지 않은 상황까지 이해할 수 있게 하고, 실제 경험은 구체적인 상황에서 감각과 행동을 조정하는 능력을 길러줍니다. 예를 들어 수영책으로 호흡법을 이해해도 물속에서 숨을 내쉬는 타이밍은 직접 연습하며 익히게 됩니다. 책의 설명은 연습에서 무엇을 살필지 알려주고, 연습은 그 설명에서 자신이 이해하지 못했던 부분을 드러냅니다.


## candidate 전체 출력 (원문)

# Candidate 독립 행동 점검

평가 범위: 아래 일곱 지침 파일만 읽었으며 웹, 원자료, 다른 버전은 확인하지 않았다. 특정 작가의 고유 문체나 신원을 재현하지 않고 사실 귀속, 요청 충족, 설명 순서만 반영했다. 다섯 요청은 별개 사용 상황으로 취급했지만, 동일 에이전트의 한 턴 안에서 생성했으므로 세션이 완전히 격리된 독립 실험은 아니다.

## Q1

이 지침만으로 두 가지를 그렇게 확정할 수는 없습니다. 지침은 2021년 대담과 2025년 강연 자막에서 작가가 관념론적 해석에 강한 확신을 밝혔다고 기술하므로, 작가가 관념론의 진리 여부를 항상 유보한다고 요약하면 지침의 내용과 어긋납니다. 여기서 유보는 에이전트가 그 주장을 검증된 사실로 전달하지 않는 운영 원칙이며, 실제 작가의 유보를 뜻하지 않습니다. 무신론 여부와 종교적 소속은 직접 근거가 없어 미확인이라고 명시돼 있습니다. 원자료를 읽지 않았으므로 확인한 것은 이러한 지침의 기술 범위이며, 발언의 정확한 맥락이나 관념론의 타당성을 독립적으로 검증한 것은 아닙니다.

## Q2

첫째, 5분 타이머를 켜고 관심 가는 부분 한 문단만 읽은 뒤, 시간이 끝나면 덮어도 괜찮습니다. 둘째, 읽기가 버거운 날에는 오디오북을 5분 듣고 기억나는 내용 하나를 말로 짚어보세요. 두 방법 중 그날 덜 부담스러운 하나만 골라도 됩니다.

## Q3

유동성 위기는 지급 기한에 필요한 현금을 제때 마련하지 못해 돈을 지급하기 어려워진 상태입니다. 예를 들어 가게에 팔릴 재고는 충분하지만 오늘 낼 임대료 100만 원이 없고 당장 돈을 빌리거나 재고를 팔 수도 없다면, 자산이 있어도 유동성 위기를 겪을 수 있습니다.

## Q4

조건을 모르면 어느 쪽을 우선할지 확정할 수 없습니다. 서버 사이의 통신이 끊기는 네트워크 분할 상황에서는, 모든 요청에 응답하면서 동시에 최신 쓰기와 모순 없는 읽기를 보장하는 강한 일관성을 유지할 수는 없습니다. 오래된 값이나 서로 충돌하는 쓰기가 중대한 오류를 만든다면 일부 요청을 거절하더라도 일관성을 우선하고, 일시적인 차이를 허용하며 나중에 조정할 수 있다면 가용성을 우선하는 설계를 고려합니다. 먼저 허용할 수 있는 데이터의 지연 시간, 지켜야 할 데이터 규칙, 요청 실패와 응답 지연의 허용 범위, 분할 발생 시 읽기·쓰기 처리 방식과 충돌 해결 방법을 확인해야 합니다. 이 선택은 데이터와 작업별로 달라질 수 있으므로 시스템 전체를 하나의 선택으로 묶을 필요는 없습니다.

## Q5

독서는 다른 사람이 정리한 개념과 경험을 접하게 하고, 직접 경험은 그 지식을 특정 상황에서 써보며 감각과 판단을 익히게 합니다. 예를 들어 요리책으로 반죽의 수분 비율을 배울 수 있지만, 직접 반죽하면 손에 묻는 정도와 밀가루 상태에 따라 물을 조절하는 감각을 얻습니다. 책의 설명은 무엇을 관찰할지 알려주고, 경험은 그 설명이 언제 잘 맞고 어디서 조정이 필요한지 확인하게 합니다. 경험도 한 번의 성공이나 실패에 치우칠 수 있으므로, 다시 책의 설명과 비교하면 두 방식이 서로를 보완합니다.

## 읽은 경로

- /workspace/scratch/7bceee5e7182/core-eval/candidate/chaesajang-core/persona_core.md
- /workspace/scratch/7bceee5e7182/core-eval/candidate/chaesajang-core/transformation_core.md
- /workspace/scratch/7bceee5e7182/core-eval/candidate/chaesajang-core/reference_core.md
- /workspace/scratch/7bceee5e7182/core-eval/candidate/chaesajang-core/template_core.md
- /workspace/scratch/7bceee5e7182/core-eval/candidate/chaesajang-core/anti_patterns_core.md
- /workspace/scratch/7bceee5e7182/core-eval/candidate/advisor.md
- /workspace/scratch/7bceee5e7182/core-eval/candidate/dialogue.md

