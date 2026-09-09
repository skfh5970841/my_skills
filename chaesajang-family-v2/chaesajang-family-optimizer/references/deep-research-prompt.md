# 외부 Deep Research 프롬프트

현재 지침과 출력만으로 방향을 정할 수 있으면 조사를 생략한다. 사용자가 프롬프트를 요청하면 바로 작성한다. 프롬프트 생성은 외부 도구 실행이나 자료 전송을 뜻하지 않는다.

## 기본: 바로 복사할 한국어 프롬프트

현재 문제에 맞춰 아래 틀을 완성한다. 외부 도구는 저장소 경로를 읽을 수 없으므로 필요한 지침과 출력 발췌를 본문에 포함한다. 관찰하지 않은 실패나 읽지 않은 파일 내용을 채워 넣지 않는다. 사례가 없으면 미확인이라고 적고 후보 조사로 한정한다.

```text
한국어 글쓰기 AI 스킬의 작은 개선을 조사해 주세요.

대상과 용도: [스킬과 이번 작업]
확인된 문제: [실제 관찰 또는 지침의 문제. 미확인인 내용은 구분]
현재 관련 지침: [필요한 부분 발췌]
실제 요청과 출력, 사용자 의견: [발췌. 없으면 없음]
유지할 장점: [이번 수정으로 잃지 않아야 할 능력]

핵심 질문: [한 가지 행동을 개선하기 위해 아직 판단하지 못한 질문]

공식 자료와 원문 연구를 우선해 이 질문에 필요한 근거만 확인해 주세요.
먼저 추천을 쉬운 한국어 5문장 이내로 설명하고, 제안은 최대 3개로 제한해 주세요.
각 제안에는 바꿀 지침 문구, 기대 이유, 부작용, 간단한 전후 비교 방법을 적어 주세요.
그중 처음 시도할 변경 하나를 고르세요. 새 도구나 평가 시스템 구축은 요구하지 마세요.
직접 관련된 출처를 최대 5개 제시하고 원문 링크, 발표·수정일(모르면 미확인), 근거와 적용 한계를 밝혀 주세요.
연구 결과와 이 스킬에 대한 추론을 구분하고, 실제 개선을 검증한 것처럼 말하지 마세요.
특정 작가의 문장 재현이나 개인적 신념 추정은 필요하지 않습니다.
결과는 읽기 쉬운 한국어 Markdown으로 작성해 주세요. JSONL은 필요하지 않습니다.
```

반환된 제안과 출처를 검토해 후보 하나만 비교한다. 조사 결과만으로 스킬을 바꾸거나 효과가 입증됐다고 판단하지 않는다.

## 기존 CLI로 생성할 때

정식 실험의 JSONL 증거 카드가 필요할 때만 아래 절차를 적용한다. 이 형식을 기본 프롬프트에 요구하지 않는다.

Use this boundary when evidence must be gathered with Deep Research or another external research tool. The optimizer owns the research question and evidence contract; the external tool owns searching and source inspection.

Generate the prompt with `research-prompt`. The command prints a paste-ready prompt to standard output and neither invokes an external tool nor writes repository files.

## Required context

- `target`: the skill or canonical area that may eventually change.
- `problem`: a concrete local observation or reproduced failure, not a desired solution.
- `local_evidence`: one or more repository-relative paths that anchor the observation.
- `scope`: `initial`, `delta`, or `full-refresh`.
- `checked_at`: the explicit research date used for reproducible provenance.

`delta` also requires `since`. `full-refresh` also requires one documented trigger: `runtime-change`, `evidence-conflict`, `corpus-expansion`, or `user-request`.

## Output boundary

The generated prompt requests JSONL evidence cards matching `research-protocol.md`. It must not ask the external tool to edit a skill, choose a candidate, or imitate the target author. Returned cards remain untrusted input until `research.py` validates them and the optimizer connects them to a falsifiable hypothesis.
