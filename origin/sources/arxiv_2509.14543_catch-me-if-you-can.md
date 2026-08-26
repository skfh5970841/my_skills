# [SOURCE] arXiv 2509.14543 — Catch Me If You Can? Not Yet: LLMs Still Struggle to Imitate the Implicit Writing Styles of Everyday Authors
# URL: https://arxiv.org/abs/2509.14543
# Retrieved: 2026-08-26 via webfetch
# Purpose: chaesajang-style 스킬 개선 근거 자료 (few-shot 문체 모방 한계 근거)
# Venue: EMNLP 2025 (Findings)

Authors: Zhengxiang Wang, Nafis Irtiza Tripto, Solha Park, Zhenzhen Li, Jiawei Zhou
Submitted: 18 Sep 2025

## Abstract

As large language models (LLMs) become increasingly integrated into personal writing tools, a critical question arises: can LLMs faithfully imitate an individual's writing style from just a few examples? Personal style is often subtle and implicit, making it difficult to specify through prompts yet essential for user-aligned generation.

This work presents a comprehensive evaluation of state-of-the-art LLMs' ability to mimic personal writing styles via in-context learning from a small number of user-authored samples. We introduce an ensemble of complementary metrics including authorship attribution, authorship verification, style matching, and AI detection to robustly assess style imitation.

Our evaluation spans over 40,000 generations per model across domains such as news, email, forums, and blogs, covering writing samples from more than 400 real-world authors.

Results show that while LLMs can approximate user styles in structured formats like news and email, they struggle with nuanced, informal writing in blogs and forums. Further analysis on various prompting strategies such as number of demonstrations reveal key limitations in effective personalization. Our findings highlight a fundamental gap in personalized LLM adaptation and the need for improved techniques to support implicit, style-consistent generation.

## 딥리서치 2에서 인용된 핵심 수치

GPT-4o 저자검증 정확도 (5-shot vs zero-shot):
- Enron 이메일: 85.02% → 96.15%
- Reddit: 56.66% → 63.65%
- Blog: 8.15% → 19.37%

→ few-shot은 강력하지만 "몇 개 예시면 문체 해결"은 아님. 비정형 개인 문체는 절대 성능이 낮음.
