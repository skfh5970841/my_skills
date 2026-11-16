# 채사장 계열 스킬

채사장의 시선을 공유하는 스킬 묶음이다. 공통 코어(`chaesajang-core/`)를 단일 원본으로 두고 각 스킬에 배포한다.

| 스킬 | 산출물 |
|---|---|
| chaesajang-style | 완성된 산문 (창작·변환) |
| chaesajang-advisor | 자문·개요, 그리고 거기서 이어지는 집필 (style과 같은 점검 기준) |
| chaesajang-dialogue | 대화 자체 |
| chaesajang-style-youtube-scripter | 영상 대본 |
| chaesajang-write-teacher | 사용자가 직접 쓰도록 하는 훈련·첨삭 (자아를 연기하지 않음) |
| chaesajang-family-optimizer | 위 스킬들의 개선 (중립적 연구자) |

## 스킬 개선하기

`chaesajang-family-optimizer`에 아쉬운 출력과 한 줄의 의견을 주면 된다. 기본 흐름은 **문제 하나 고르기 → 작게 고쳐 비교하기 → 좋아진 변경만 반영하기**다. 모드 선택이나 명령어 입력은 필요하지 않다.

예: “결론 뒤에 같은 설명이 반복돼. 관련 지침을 작게 고치고 전후 결과를 비교해 반영해줘.” 에이전트가 바뀐 부분과 유지된 장점을 보여주고, 검증하지 못한 점은 구분해 보고한다. 이미 반영을 요청한 범위는 재승인 없이 진행한다. 계획만 요청하면 제안으로 마친다.

Deep Research는 판단이 막힐 때만 사용한다. “이 문제를 조사할 프롬프트를 만들어줘”라고 요청하면 [프롬프트 지침](chaesajang-family-optimizer/references/deep-research-prompt.md)에 따라 복사 가능한 한국어 프롬프트를 만든다. 외부 조사 실행은 별개다.

## 옵티마이저 소유권과 안전 경계

- `family.yaml`, `chaesajang-core/`, 각 스킬 폴더가 canonical source다. 직접 수정은 승인된 변경에만 허용한다.
- `skills/`, `dist/`(그 안의 `packages/*.skill` 포함)는 생성물이다. 직접 편집하지 말고 `sync_core.py`와 renderer로 다시 만든다.
- `feedback/completed/` 원문과 `evals/golden/` 이관본은 immutable evidence다. 새 정보는 새 기록으로 추가하며 기존 기록을 덮어쓰지 않는다.
- 기본 개선은 변경 전 내용·전후 비교·판단을 하나의 Markdown 기록에 남기고 승인된 범위에서 원본에 적용한다.
- 아래 정식 CLI 실험의 후보, raw generation, 점수, blind package, rating, report는 해당 `experiments/<id>/`가 소유한다. 이 경로에서는 `ready_for_approval`이 쓰기 권한이 아니며, `promote --approved-by-user`만 canonical source를 변경할 수 있다. 기존 실험의 반영 조건을 기본 흐름으로 우회하지 않는다.

## 선택 사항: 기존 실험 CLI

정식 실험이나 기존 실험 재개를 요청한 경우에만 [기존 실험 절차](chaesajang-family-optimizer/references/advanced-workflow.md)를 사용한다. 아래 평가 파일과 상태 규칙은 이 경로에만 적용한다.

저장소 루트에서 다음 형식을 사용한다. 현재 `bootstrap`은 설정 요약을 검증·출력하고, `cycle`과 `resume`은 저장된 manifest의 다음 행동을 출력하며, `report`는 기록된 보고서만 읽는다. 이 세 명령은 live model을 호출하거나 canonical source를 쓰지 않는다.

```powershell
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 bootstrap --experiment <id> --model <model> --reasoning <effort>
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 research-prompt --target <skill-or-core-area> --problem <observed-problem> --local-evidence <relative-path> --scope delta --since <YYYY-MM-DD> --checked-at <YYYY-MM-DD>
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 cycle --experiment <id> --claims <research.jsonl> --hypothesis <hypothesis.md> --cases <cases.jsonl> --ratings <human_ratings.jsonl> --timeout 180
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 resume --experiment <id> --timeout 180
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 report --experiment <id>
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 promote --experiment <id> --approved-by-user
```

설치본까지 교체할 권한을 따로 받은 경우에만 마지막 명령에 `--install-root <explicit-path>`를 추가한다.

## 사람 평가, 차단 상태, 비용

`human_ratings.jsonl`은 blind pair마다 한 줄의 JSON object를 기록한다. 필드는 `pair_id`, `quality_preference`, `style_preference`, `overall_preference`, `over_imitation`, `meaning_or_fact_issue` (`A`/`B` 각각), `evidence_excerpt`다. 공개 pair의 `A`/`B`만 평가하고 private mapping은 rating 파일에 복사하지 않는다.

`research-prompt`는 외부 도구를 실행하거나 파일을 쓰지 않고, 붙여넣어 사용할 조사 프롬프트만 표준 출력으로 만든다. 명령 비정상 종료, CLI 부재, timeout, 빈 출력, malformed output은 `blocked_external`이며 PASS나 0점이 아니다. provenance·hash·필수 artifact가 불완전하면 `invalid`, gate 또는 보호 사례가 실패하면 `rejected`다. deterministic tests 자체는 live Codex를 호출하지 않는다. 별도로 승인해 실제 Codex generation을 실행하면 모델 사용 비용과 latency가 발생할 수 있다.

## 구성

```
family.yaml                       # 스킬 목록, 스킬별 코어 파일, 시선 블록 주입 여부
chaesajang-core/                  # 공통 코어 마스터 — 코어 내용은 여기서만 수정한다
  persona_core.md                 # 자아
  handoff_core.md                 # 스킬 간 맥락 이동 패킷
  gaze_core.md                    # 시선 4원리 + 쓰는 방식 (SKILL.md의 CORE:gaze 마커로 주입)
  anti_patterns_core.md           # 함정 AP-01~11 + 클로드 네 함정 + 체크리스트
  reference_core.md               # 문장 패턴, 실측 빈도
  template_core.md                # 도입·전개·통찰 예시
  transformation_core.md          # 변환 판단 RULE-01~06
  *_youtube.md (4종)              # scripter 전용 델타
chaesajang-<skill>/               # 스킬 원본. references/의 *_core.md는 코어 사본이다
skills/                           # SKILL.md 스냅샷 (생성물, 커밋함)
dist/                             # 런타임별 조립본과 packages/*.skill (생성물, git 제외)
sync_core.py                      # 동기화
```

## 코어를 고칠 때

1. `chaesajang-core/`의 마스터만 수정한다. 스킬 폴더의 `*_core.md` 사본과 `CORE:gaze` 블록 안쪽은 직접 고치지 않는다.
2. `python3 sync_core.py` — 마스터를 각 스킬 폴더 사본과 SKILL.md 시선 블록에 반영하고, `skills/` 스냅샷과 `dist/`를 다시 만든다.
3. `python3 sync_core.py --check` — 종료코드 0이면 동기화 상태, 2면 드리프트.
4. 설치용 패키지는 `dist/packages/<스킬>.skill`이다.

`dist/`는 git에 없으므로 새로 클론한 직후에는 `--check`가 실패한다. `sync_core.py`를 한 번 실행하면 된다.

## 같은 내용이 두 곳에 있는 곳

- 완성 후 점검 목록: `chaesajang-style/SKILL.md`의 "글을 완성한 뒤"가 정본이고 `chaesajang-advisor/references/mode_write.md`에 같은 목록이 있다. 한쪽을 고치면 다른 쪽도 고친다.
- `gaze_core.md`의 `CORE:method` 블록은 주입되지 않는 보존본이다.
