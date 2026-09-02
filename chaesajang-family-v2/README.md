# 채사장 계열 코어 통합 — 배포 가이드

2번(코어 통합)·5번(핸드오프) 과제의 최종 산출물. 1번 과제(자아 코어)의 Step 0도 SKILL.md 수정본에 이미 반영되어 있어, 이 배포 한 번으로 두 과제가 함께 적용된다.

## 옵티마이저 소유권과 안전 경계

- `family.yaml`, `chaesajang-core/`, 각 스킬 폴더가 canonical source다. 직접 수정은 승인된 변경에만 허용한다.
- `skills/`, `dist/`, `*.skill`은 생성물이다. 직접 편집하지 말고 `sync_core.py`와 renderer로 다시 만든다.
- `feedback/completed/` 원문과 `evals/golden/` 이관본은 immutable evidence다. 새 정보는 새 기록으로 추가하며 기존 기록을 덮어쓰지 않는다.
- 후보, raw generation, 점수, blind package, rating, report는 해당 `experiments/<id>/`가 소유한다. `ready_for_approval`은 쓰기 권한이 아니며, `promote --approved-by-user`만 canonical source를 변경할 수 있다.

## 최소 CLI

저장소 루트에서 다음 형식을 사용한다. 현재 `bootstrap`은 설정 요약을 검증·출력하고, `cycle`과 `resume`은 저장된 manifest의 다음 행동을 출력하며, `report`는 기록된 보고서만 읽는다. 이 세 명령은 live model을 호출하거나 canonical source를 쓰지 않는다.

```powershell
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 bootstrap --experiment <id> --model <model> --reasoning <effort>
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 cycle --experiment <id> --claims <research.jsonl> --hypothesis <hypothesis.md> --cases <cases.jsonl> --ratings <human_ratings.jsonl> --timeout 180
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 resume --experiment <id> --timeout 180
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 report --experiment <id>
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --root chaesajang-family-v2 promote --experiment <id> --approved-by-user
```

설치본까지 교체할 권한을 따로 받은 경우에만 마지막 명령에 `--install-root <explicit-path>`를 추가한다.

## 사람 평가, 차단 상태, 비용

`human_ratings.jsonl`은 blind pair마다 한 줄의 JSON object를 기록한다. 필드는 `pair_id`, `quality_preference`, `style_preference`, `overall_preference`, `over_imitation`, `meaning_or_fact_issue` (`A`/`B` 각각), `evidence_excerpt`다. 공개 pair의 `A`/`B`만 평가하고 private mapping은 rating 파일에 복사하지 않는다.

명령 비정상 종료, CLI 부재, timeout, 빈 출력, malformed output은 `blocked_external`이며 PASS나 0점이 아니다. provenance·hash·필수 artifact가 불완전하면 `invalid`, gate 또는 보호 사례가 실패하면 `rejected`다. deterministic tests 자체는 live Codex를 호출하지 않는다. 별도로 승인해 실제 Codex generation을 실행하면 모델 사용 비용과 latency가 발생할 수 있다.

## 산출물 구성

```
chaesajang-core/                  # 마스터 — 앞으로 이것만 수정한다
  persona_core.md                 # 자아 (1번 과제)
  handoff_core.md                 # 스킬 간 맥락 이동 패킷 (5번 과제)
  gaze_core.md                    # 시선 4원리 + 쓰는 방식 (SKILL.md 마커 주입용)
  anti_patterns_core.md           # 함정 AP-01~07 + 클로드 네 함정 + 체크리스트
  reference_core.md               # 문장 패턴 (A/B 인물화, 용어 지연 도입 편입)
  template_core.md                # 글쓰기 예시 (advisor 변형 7종 편입)
  transformation_core.md          # 변환 판단 RULE-01~06
  *_youtube.md (4종)              # scripter 전용 델타

skills/                           # 4개 SKILL.md 수정본 (전체 교체용)
sync_core.py                      # 동기화 스크립트
```

## 배포 절차

1. 로컬 스킬 작업 루트에 `chaesajang-core/` 폴더를 만들고 마스터 10개 파일을 넣는다.
2. 4개 스킬의 SKILL.md를 `skills/`의 수정본으로 교체한다.
   (파일명의 스킬 접두어는 제거: `chaesajang-style.SKILL.md` → `chaesajang-style/SKILL.md`)
3. 구 보조 파일을 삭제한다:
   - style: `references/` 안의 anti_patterns·reference·template·transformation_rules.md
   - advisor: 위 4종 + `references/persona_contract.md`
   - scripter: 루트의 anti_patterns·reference·template·transformation_rules.md
4. `python3 sync_core.py` 실행 → 코어 사본 배포 + gaze 마커 주입.
5. 각 스킬을 package_skill.py로 재패키징.

## 이후 운용

- 코어 내용 수정은 **마스터에서만** 하고 sync_core.py를 재실행한다.
- 사본을 직접 고치고 싶어지는 순간이 드리프트의 시작이다.
- `python3 sync_core.py --check`로 언제든 드리프트를 검사할 수 있다 (종료코드 2 = 드리프트 존재).
- 시선 4원리·쓰는 방식 수정 → gaze_core.md의 마커 블록 안쪽만 수정.

## 미반영 항목 (수동 1건)

advisor의 `references/mode_write.md`에 한 줄 추가 권장:
> 코어 파일은 전체를 읽지 않아도 된다. 작업에 필요한 섹션만 읽는다.
> (template_core·reference_core가 변형 편입으로 길어졌기 때문)

## 변경 요약

| 항목 | 이전 | 이후 |
|---|---|---|
| 보조 파일 | 9벌 (3계보 독립 드리프트) | 코어 5 + 델타 4, 단일 원본 |
| 자아 정의 | 2/4 스킬, 기능형 | 4/4 스킬, 입장·기원 포함 |
| 핸드오프 | dialogue→style 안내만 | 패킷 표준, 4스킬 발신·수신 연결 |
| 시선 4원리 | 2벌, 상호 모순 (확신 정의) | 1벌, 마커 주입 |
| 상호참조 | 1건 파손 (자기계발 클리셰) | AP-번호 참조로 수정 |
| advisor 고유 자산 | advisor에 고립 | A/B 인물화 등 코어 편입 |
