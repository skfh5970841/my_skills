# 기존 실험과 CLI

사용자가 CLI 모드나 정식 실험을 명시하거나 기존 `experiments/<id>/` 작업을 이어갈 때 적용한다. 일반적인 작은 개선에는 이 절차를 요구하지 않는다. 기존 실험을 간단한 수정으로 다시 분류해 실패한 평가나 반영 조건을 우회하지 않는다.

진입점은 `scripts/loop.py`다. 현재 `bootstrap`은 설정 요약, `cycle`·`resume`은 다음 행동을 출력하며 실제 모델 생성을 자동 수행하지 않는다. `report`는 저장된 보고서를 읽는다. 명령 실행을 평가 완료로 보고하지 않는다.

| 모드 | 용도 | 필요한 참조 |
|---|---|---|
| `bootstrap` | 조사·스냅샷·평가 입력 준비 | [조사](research-protocol.md), [평가](evaluation-protocol.md) |
| `research-prompt` | JSONL 증거 카드용 외부 조사 프롬프트 출력 | [조사](research-protocol.md), [프롬프트의 CLI 절차](deep-research-prompt.md#기존-cli로-생성할-때) |
| `cycle` | 가설 하나와 후보를 평가 | [조사](research-protocol.md), [평가](evaluation-protocol.md) |
| `resume` | 마지막 유효 산출물부터 이어가기 | 다음 미완료 단계의 참조 |
| `report` | 기록된 상태만 보고 | [반영 정책](promotion-policy.md) |
| `promote` | 승인된 후보 반영 | [반영 정책](promotion-policy.md) |

가설은 외부 근거와 로컬 관찰을 연결하고, 하나의 지침 묶음이나 참조 선택 방식만 바꾼다. 개선 기준, 보호할 능력, 기각 조건을 지정한다. 정식 실험의 후보는 격리해 보관하고 원본 반영에는 사용자 승인과 반영 정책의 모든 조건이 필요하다. 기존 승인은 명시된 범위에서 유효하다.

실패한 후보와 근거를 보존한다. 오류, 시간 초과, 빈 출력, 누락된 산출물, 평가 데이터 누출은 성공이 아니다. 설치본 교체는 해당 경로까지 승인받은 경우에만 수행한다.
