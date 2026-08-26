# sources_index.md — 출처 회수 결과

# Phase A: 출처 원문 회수 — 완료 보고
작성: 2026-08-26

## 1. 딥리서치 2 (LLM 스킬 설계) 참고문헌 — 10건 전량 회수 시도, 9건 성공

| # | 출처 | URL | 상태 | 저장 파일 |
|---|---|---|---|---|
| 1 | Agent Skills — Best practices for skill creators | https://agentskills.io/skill-creation/best-practices | ✅ 전문 | agentskills_best-practices.md |
| 2 | Agent Skills — Specification | https://agentskills.io/specification | ✅ 전문 | agentskills_specification.md |
| 3 | Agent Skills — Optimizing skill descriptions | https://agentskills.io/skill-creation/optimizing-descriptions | ✅ 전문 | agentskills_optimizing-descriptions.md |
| 4 | OpenAI — Prompt engineering guide | https://developers.openai.com/api/docs/guides/prompt-engineering | ✅ 본문(코드샘플 제외) | openai_prompt-engineering.md |
| 5 | OpenAI — Prompting guide | https://developers.openai.com/api/docs/guides/prompting | ✅ 요약(prompt-engineering과 중복) | openai_prompting.md |
| 6 | Cho et al. 2025 — TICL (NAACL Findings) | https://aclanthology.org/2025.findings-naacl.326/ | ✅ 랜딩페이지+초록 (PDF 본문 미수집) | acl_2025_ticl_tuning-free-personalized-alignment.md |
| 7 | Wang et al. 2025 — Catch Me If You Can (EMNLP Findings) | https://arxiv.org/abs/2509.14543 | ✅ 초록+핵심 수치 | arxiv_2509.14543_catch-me-if-you-can.md |
| 8 | Holtzman et al. 2020 — Neural Text Degeneration (ICLR) | https://arxiv.org/abs/1904.09751 | ✅ 초록 | arxiv_1904.09751_neural-text-degeneration.md |
| 9 | Zhang et al. 2025/26 — Verbalized Sampling | https://arxiv.org/abs/2510.01171 | ✅ 초록 | arxiv_2510.01171_verbalized-sampling.md |
| 10 | 임진 2026 — LLM 문학 번역 창의적 변이 계량 분석 | https://journal.kci.go.kr/kats/archive/articlePdf?artiId=ART003318653 | ✅ PDF 회수+텍스트 추출 (UA/referer 헤더 필요) | kci_2026_llm_translation.pdf/.txt/_summary.md |

## 2. 딥리서치 1 (문체 인벤토리) 출처 — 재발굴 결과

딥리서치 1은 `citeturn` 아티팩트로 URL이 소실됐으나, 다음과 같이 확보됨:

### 사용자가 사전에 수집해둔 자료 (origin 루트)
- `지대넓얕 인용문.md` — 지대넓얕 직접 인용문 + 출처 URL (브런치·티스토리·YES24·알라딘)
- `열한계단_1/2 인용문.md` — 『열한 계단』 발췌 + 출처 (딥리서치 1의 Q1 코퍼스 해당)
- `우리는 언젠가 만난다_1/2 인용문.md` — 발췌 + 출처 (Q2 코퍼스 해당)
- `시민의교양_1/2 인용문.md`, `소마_1/2 인용문.md` — 발췌 + 출처

### 이번 세션에서 신규 회수
- **채널예스 2016-02-18 임나리 인터뷰** (딥리서치 1의 구어 표본 O의 원문):
  - URL: https://ch.yes24.com/Article/details/30155 (DuckDuckGo 검색으로 발견 → fetch 성공)
  - 저장: channelyes_2016_interview_30155.md (질의응답 전문 + 구어체 관찰 메모)

### 보류 / 불필요
- 리디 공개 본문 W0/W1/W2 (지대넓얕 1·2·제로): 보유 책 전문(OCR본)이 상위 집합이므로 불필요
- 네이버 블로그: 딥리서치 1 자체가 robots 제한으로 실패 명시 → 보류
- 스포츠서울 2020 기사, 2026 강연 기사: 채널 확인 용도로만 쓰였고 결론(지식한입≠채사장 채널)은 이미 확정 → 보류

## 3. Phase E 설계 작업에 즉시 먹히는 핵심 근거 (출처에서 발췌)

1. **progressive disclosure 공식 기준** (specification): metadata ~100 tokens / SKILL.md <5000 tokens & <500 lines / resources on demand + 파일 로딩 조건을 명시하라
2. **"왜"를 설명하는 유연한 지침이 rigid directive보다 낫다** (best-practices) — 현재 스킬 철학과 일치, 유지
3. **Gotchas는 SKILL.md에 두라** — 비명백한 트리거는 참조파일에서 놓치기 때문
4. **description 최적화 방법론** (optimizing-descriptions): ~20개 eval 질의(8~10 positive/near-miss negative), trigger rate 3회 반복 측정, train/validation split → Phase D 테스트 설계에 직접 적용
5. **TICL**: negative sample + explanation이 few-shot 예시보다 제거 영향이 큼 → anti_patterns 강화 방향 근거
6. **Catch Me If You Can**: 5-shot으로도 blog/forum 스타일 절대 정확도 낮음 → 과대기대 경계, 예시 다양성이 핵심 변수
7. **Verbalized Sampling**: mode collapse(기교 반복) 대응 프롬프트 기법 — 다양성 제어 장치 근거
