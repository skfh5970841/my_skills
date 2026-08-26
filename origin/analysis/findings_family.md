# findings_family.md — chaesajang 계열 v2 통합 개선 최종 보고서
작성: 2026-08-26

## 0. 개요
- 목적: chaesajang 계열(style·advisor·dialogue·youtube-scripter·core) 전반을 원전 데이터로 검증하고, v2 아키텍처(core+sync)로 통합
- 산출 체인: merge_map → phase_b_report(사고 방식 인벤토리) → phase_c_report(갭·트리거) → phase_d_report_family(실증) → 본 보고서

## 1. 핵심 발견

### 구조적 발견 (이번 라운드의 가장 큰 수확)
1. **v2 마이그레이션 불완전**: v2 advisor SKILL.md가 참조하는 mode_consult/mode_outline/question_bank 4종이 v2에 없었음 (구버전에만 존재) → 이식·수정 완료
2. **dialogue 미작성 파일 3종**: voice/thinking_moves/what_breaks_it 부재 → 원전 분석 기반으로 신규 작성 완료
3. **scripter description 트리거 충돌(HIGH)**: '채사장 스타일로 써줘' 등 산문 트리거를 scripter가 보유해 style과 직접 충돌 → 영상 의도 한정으로 수정
4. **이중 유지 문제**: 지난번 style 개선이 설치된 v1에만 있어 v2와 갈라짐 → 병합 완료(merge_map.md)

### 원전 검증 결과
| 대상 | 판정 |
|---|---|
| dialogue 국면(수신→재배치→확장→수렴→착지) | ✅ 인터뷰 응답 패턴과 일치 |
| youtube 델타 8단계 구조 | ✅ 강의 자막과 일치 |
| persona_core 확신/유보/침묵 | ✅ 저자의 실제 입장 표명 방식과 부합 |
| reference_core 종결어미(~다 80~90%) | ✅ 실측 82~89% |
| question_bank 분류체계 Q1~35 | ✅ 대체로 타당 + ⚠️ 구어 화법 3종 누락(수용 확인형·셀프 답변형 "뭐냐면은"·상대 호출형) → thinking_moves에 반영 |
| mode_outline 질문형 도입 / 용어 순서 | ❌ → 수정 완료 |
| 코어 파일 간 세금 예시 중복(reference/template/template_youtube) | ❌ → 평등/습관 예시로 교체 |

### 신규 작성 파일 (dialogue)
- `voice.md`: 어미 2모드·완충 기본값("~것 같아요")·화법 신호어("뭐냐면은" 등 실측)·리듬
- `thinking_moves.md`: 실측 질문 유형 8종 중 7동작 정식화(재배치·연결 지정·극단 테스트·장면 체감·수렴 압축·되묻기·호출)
- `what_breaks_it.md`: 무너짐 6유형 + 3초 점검

## 2. 적용 완료 내역
1. v2 core 병합: reference_core(R1~7)·template_core(T1~4)·anti_patterns_core(AP-08~10)·transformation_core(X1) — 모두 지난번 style 탐구의 실측 근거 이식
2. advisor 누락 4종 이식 + mode_outline §2.2/3.1/3.3 수정 + Q-17 현상 우선 수정 + mode_consult 4.5 호출형 추가 + 서사 프레임 옵션 추가
3. youtube 델타 결함 2건 수정(V-RHYTHM-B 전환어, 종합 예시 교체)
4. dialogue 파일 3종 신규 작성
5. scripter description 영상 의도 한정 수정
6. sync_core.py 실행 → 4 스킬 동기화 완료 (--check 통과)

## 3. 잔여 과제
- [사용자] 실제 고민 2개 기반 dialogue 테스트 (가상 시나리오는 D1에서 통과)
- [사용자] trigger_eval 스크립트 실행 (style↔scripter 수정 후 재측정 권장)
- [Phase F] v2 설치 전환 + 구버전 백업·제거 + 회귀 테스트 + 블라인드 3회차
- KCI 논문 PDF 등 미회수 출처 1건 (우선순위 낮음)

## 4. 최종 상태 업데이트 (2026-08-26)
- 블라인드 3회차: 스킬 응답 0:3 전패 → "실질 앵커" 규칙(매 턴 구체 재료 1개)을
  dialogue SKILL·voice·thinking_moves에 추가, mode_consult에 방향 후보 옵션 추가, 재배포 완료
- 사용자 실제 고민 2건(친구 질투 / AI 글쓰기 구분) 대화 실행 → 사용자 판정 대기
- ~/.agents/skills/chaesajang-advisor도 v2로 교체 완료 (구버전은 backup_v1/agents_advisor)
- 설치 현황: ~/.claude/skills 4스킬(v2) + ~/.agents/skills advisor(v2)

## 5. 남은 작업 목록
1. [사용자 판정] 실제 고민 2건 대화 응답의 진정성 평가 — 통과 시 계열 개선 종료,
   미통과 시 앵커 밀도·어투 추가 조정 후 재검증
2. [선택] trigger_eval 스크립트 실행 (~20 질의 × 3회, style↔scripter 수정분 재측정)
3. [낮음] KCI 논문 PDF 등 딥리서치 1 미회수 출처 1건
4. [낮음] sync_core.py 안내 문구의 package_skill.py 참조 — 해당 파일이 없으므로 문구 정리 또는 스크립트 작성
5. [참고] 팟캐스트 ASR 화자 미구분 한계는 thinking_moves 인벤토리에 이미 명시됨

## 6. 마무리 작업 결과 (2026-08-26)
- KCI 논문(딥리서치 출처 10번) 회수 완료: UA/referer 헤더 우회 필요 확인, pdfplumber로 29면 텍스트 추출
  → sources/kci_2026_llm_translation.{pdf,txt,_summary.md}, sources_index 갱신. **출처 회수율 10/10**
- sync_core.py의 존재하지 않는 package_skill.py 참조 제거 (설치는 폴더 복사 방식으로 명시)
- ~/.agents/skills/chaesajang-advisor v2 교체 완료
- 트리거 평가: claude CLI는 있으나 **API 크레딧 부족("Credit balance is too low")으로 실행 불가**.
  jq 없는 환경용 Python 러너 작성 완료(trigger_eval/run_trigger_eval.py) — 크레딧 충전 후
  `python run_trigger_eval.py 3` 또는 `python run_trigger_eval.py 3 any`로 즉시 실행 가능.
