# [SOURCE] ACL Findings NAACL 2025 — Tuning-Free Personalized Alignment via Trial-Error-Explain In-Context Learning (TICL)
# URL: https://aclanthology.org/2025.findings-naacl.326/
# PDF: https://aclanthology.org/2025.findings-naacl.326.pdf
# Retrieved: 2026-08-26 via webfetch (landing page; PDF 본문 미수집)
# Authors: Hyundong Justin Cho, Karishma Sharma, Nicolaas Paul Jedema, Leonardo F. R. Ribeiro, Jonathan May, Alessandro Moschitti
# Pages: 5879–5900, DOI: 10.18653/v1/2025.findings-naacl.326
# Purpose: chaesajang-style 스킬 개선 근거 자료 (contrastive anti-example + explanation 효과 근거)

## Abstract

Language models are aligned to the collective voice of many, resulting in generic outputs that do not align with specific users' styles. In this work, we present Trial-Error-Explain In-Context Learning (TICL), a tuning-free method that personalizes language models for text generation tasks with fewer than 10 examples per user.

TICL iteratively expands an in-context learning prompt via a trial-error-explain process, adding **model-generated negative samples and explanations** that provide fine-grained guidance towards a specific user's style.

TICL achieves favorable win rates on pairwise comparisons with LLM-as-a-judge up to **91.5%** against the previous state-of-the-art and outperforms competitive tuning-free baselines for personalized alignment tasks of writing emails, essays and news articles.

Both lexical and qualitative analyses show that the negative samples and explanations enable language models to learn stylistic context more effectively and **overcome the bias towards structural and formal phrases observed in their zero-shot outputs**.

## 딥리서치 2에서 인용된 핵심 수치

- Claude 3 Sonnet TICL ablation: 전체 방법의 저자 대비 승률 54.5% → explanation 제거 시 46.0%, 초기 ICL 예시만 제거 시 52.0%
- → 실패 출력(negative sample)+이유 설명이 예시 자체보다 제거 영향이 큼 = anti-example+explanation 구조의 근거

## 스킬 개선 관련 시사점

anti_patterns.md를 "금지 목록"이 아니라 "틀린 출력 + 왜 틀렸는지 설명" 형태로 강화하는 것이 실증적으로 유망.
현재 chaesajang-style의 anti_patterns.md는 이미 이 방향에 있음(함정+판단기준+허용예외). 강화 포인트: 원전 기반 실제 사례로 교체.
