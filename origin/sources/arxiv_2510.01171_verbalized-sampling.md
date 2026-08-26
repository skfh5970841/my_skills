# [SOURCE] arXiv 2510.01171 — Verbalized Sampling: How to Mitigate Mode Collapse and Unlock LLM Diversity
# URL: https://arxiv.org/abs/2510.01171
# Retrieved: 2026-08-26 via webfetch
# Purpose: chaesajang-style 스킬 개선 근거 자료 (패턴 과적·다양성 제어 근거)
# Authors: Jiayi Zhang, Simon Yu, Derek Chong, Anthony Sicilia, Michael R. Tomz, Christopher D. Manning, Weiyan Shi
# v4 2026-07-15 / Code: https://github.com/CHATS-lab/verbalize-sampling

## Abstract

Post-training alignment often reduces LLM diversity, leading to a phenomenon known as mode collapse. Unlike prior work that attributes this effect to algorithmic limitations, we identify a fundamental, pervasive data-level driver: **typicality bias in preference data**, whereby annotators systematically favor familiar text as a result of well-established findings in cognitive psychology. We formalize this bias theoretically, verify it on preference datasets empirically, and show that it plays a central role in mode collapse.

Motivated by this analysis, we introduce **Verbalized Sampling**, a simple, training-free prompting strategy to circumvent mode collapse. VS prompts the model to verbalize a probability distribution over a set of responses (e.g., "Generate 5 jokes about coffee and their corresponding probabilities").

Comprehensive experiments show that VS significantly improves performance across creative writing (poems, stories, jokes), dialogue simulation, open-ended QA, and synthetic data generation, without sacrificing factual accuracy and safety. For instance, **in creative writing, VS increases diversity by 1.6-2.1x over direct prompting**. We further observe an emergent trend that more capable models benefit more from VS.

## 스킬 개선 관련 시사점

- 문체 재현 시 mode collapse(같은 기교 반복)는 데이터 수준의 typicality bias에서 옴
- 프롬프트 레벨 대응: 여러 후보 접근을 확률과 함께 verbalize하도록 요청 → 다양성 확보
- 딥리서치 2 권고: "5개 접근/voice plan 생성 → 최고확률만 쓰지 말고 후보 샘플링"
