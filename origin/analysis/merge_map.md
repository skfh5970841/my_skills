# merge_map.md — Phase 0: v1 개선 ↔ v2 core 병합 매핑
작성: 2026-08-26

## 발견된 구조적 사실
1. v2는 드리프트 없음(sync --check 통과). 그러나 **v2 advisor가 참조하는 CONSULT/OUTLINE 모드 파일·질문은행 4종이 v2에 없음**(구버전에만 존재) — 마이그레이션 불완전.
2. 지난번 탐구의 개선(실측 데이터·기교 예산·AP-09~11 등)은 v1에만 있고 v2 core에는 없음.
3. v2 고유 자산(v1에 없는 것): 전환 없는 전환 패턴, 종결어미 판단 기준(~다 80~90%, 실측과 부합), 길이별 가이드, 비인문 주제 축, persona_core의 확신/유보/침묵 영역, 클로드 특화 함정 4종, 판단의 위임 결론, 도입–결론 짝 패턴 → **모두 보존**.

## 병합 지도

### reference_core.md
- R1 리듬 섹션에 실측 데이터+3박자 실행 앵커 삽입 (중위값 29~34자, ≥60자 11~14%)
- R2 전환어 테이블을 실측판으로 교체 (흥미로운 것은·다시 말하면=미관측 명시, 방향 선택 원칙)
- R3 P-RHYTHM-C → 역접 배치(하지만/다만 주력, 그런데 단독=특수 장치)
- R4 독자 편입 앵커 신설 (우리>>당신>여러분, ~17/10k)
- R5 기교 예산 신설
- R6 P-STRUCTURE-C에 인용 장치 12.7% 실측 보강
- R7 종합 예시 세금→평등 교체 + 복사 금지 문구

### template_core.md
- T1 도입 인트로: 질문 소환 프레임 + 원전 첫문장 질문 0개 근거 (질문형 우선 완화, 6유형 유지)
- T2 논증 중간 질문 연쇄 섹션 신설 (전개 아래)
- T3 통찰 유형 "한 편 하나" 규칙
- T4 종합 예시 세금→습관 교체

### anti_patterns_core.md
- A1 AP-08 전환어 체크리스트화 · AP-09 기교 과적 · AP-10 독자 편입 과잉 신설
- A2 체크리스트 확장

### transformation_core.md
- X1 RULE-01 프레임을 "장면형 재구성(질문 소환)"으로 정렬

### gaze_core.md — 수정 없음 (인터뷰 근거 이미 반영)

### advisor 누락 파일 복원 (v1 → v2 이식 + 수정)
- M1 mode_consult.md / mode_outline.md / question_bank_core.md / question_bank_full.md
  - mode_outline §2.2 "도입은 질문이어야 한다" → 질문 소환 프레임으로 수정
  - mode_outline §3.1 도입 유형 → template_core 6유형과 동기화
  - mode_outline §3.3 설명 순서 → 용어 지연 도입 정렬
  - question_bank Q-17 "추상적 정의부터" → 현상·장면부터로 수정
- M2 v2 advisor SKILL.md description에 경계 라인 추가

### dialogue (Phase B/C 결과물로 신규 작성)
- D1 voice.md / D2 thinking_moves.md / D3 what_breaks_it.md
