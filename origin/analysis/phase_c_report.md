# phase_c_report.md — 갭 감사 + 트리거 겹침 매트릭스
작성: 2026-08-26

## 1. v2 코어 × 원전 인벤토리 갭 대조

| 파일 | 주장 | 판정 | 조치 |
|---|---|---|---|
| gaze_core 편안한 확신 | 뼈대는 단정, 해석은 완충 | ✅ 실측(~다 82~89%, 구어 완충) 부합 | 없음 |
| reference_core 종결어미 | ~다 체 80~90% | ✅ 실측 82~89%와 일치 | 없음 |
| reference_core 전환어 표 | 흥미로운 것은·다시 말하면 포함 | ❌ 원전 0회 | **병합으로 교체 완료** |
| reference_core 리듬 | (실측 데이터 없음) | ⚠️ | **3박자+앵커 삽입 완료** |
| template_core 도입 프레임 | "질문 앞에 세우기" + 질문형 우선 | ❌ 첫문장 질문 0건 | **질문 소환 프레임으로 수정 완료** |
| template_core 통찰 4+보조 유형 | (과적 방지 규칙 없음) | ⚠️ Phase D F3 위험 | **한 편 하나 규칙 추가 완료** |
| anti_patterns AP-01~07+클로드 4함정 | 구조 양호 | ⚠️ F1~F3·F4 누락 | **AP-08~10 추가 완료** |
| transformation_core RULE-01~06 | 구조 양호 | ⚠️ RULE-01 프레임 | **질문 소환 정렬 완료** |
| persona_core 확신/유보/침묵 | 시장·정부 유보 등 | ✅ 인터뷰에서 저자의 실제 입장 표명 방식과 부합 | 없음 |
| mode_outline §2.2/3.1/3.3 | 질문형 도입 오류 등 | ❌→✅ | **이식하며 수정 완료** |
| question_bank Q1~35 | 분류체계 | ✅ 대체로 타당 / ⚠️ 구어 화법 3종 누락 | thinking_moves로 보완 |
| dialogue 국면 설계 | 수신→재배치→확장→수렴→착지 | ✅ B2 인터뷰 패턴과 일치 | voice/thinking_moves/what_breaks_it 신규 작성 |
| youtube 델타 8단계 구조 | 강의 자막과 비교 | ✅ 높은 일치 | 세금 예시 중복·다시 말하면 교체 완료 |
| dialogue 미작성 파일 3종 | SKILL.md가 참조하나 부재 | ❌ | **voice.md·thinking_moves.md·what_breaks_it.md 작성 완료** |

## 2. 트리거 겹침 매트릭스 (5스킬)

| 발화 예시 | style | advisor | dialogue | scripter |
|---|---|---|---|---|
| "채사장 스타일로 글 써줘" | ◎ 산문 | △(WRITE 신호 겹침) | ✗ | ❌ **격overlap: scripter description이 동일 트리거 보유** |
| "이 글 지대넓얕 톤으로 바꿔줘" | ◎ 변환 | △ | ✗ | ❌ 동일 |
| "유튜브 대본으로 만들어줘" | → scripter 안내 | △ | ✗ | ◎ |
| "구조 잡아줘/개요" | ✗(안내) | ◎ OUTLINE | ✗ | ✗ |
| "채사장이랑 대화하고 싶어" | ✗ | △(자문과 유사) | ◎ | ✗ |
| "채사장처럼 생각해줘" | ✗ | ◎ CONSULT | △(대화와 경계 미묘) | ✗ |

### 충돌 해소 조치
- **[HIGH] scripter description**: '채사장 스타일로 써줘', '교양 글쓰기', '쉽고 깊게 써줘' 등
  **산문 트리거가 그대로 적혀 있음** → 영상 의도가 없으면 style과 직접 충돌.
  → scripter description을 "영상 대본·스크립트 의도가 있을 때"로 한정하는 수정 필요 (Phase F).
- advisor↔style: 상호 참조 라인으로 해소됨 (v2 advisor description에 반영 완료).
- advisor CONSULT ↔ dialogue: "채사장처럼 생각해줘"(advisor) vs "같이 생각해보자"(dialogue).
  경계: 자문(글쓰기 지향) vs 대화(탐구 자체). dialogue description에 이미 명시됨. 유지.

## 3. 잔여 과제 (Phase E로)
- scripter description 수정안 확정
- mode_outline에 서사 프레임 옵션 보강 문구 (B3 결과)
- question_bank_core에 상대 호출형 보강 여부 판단
