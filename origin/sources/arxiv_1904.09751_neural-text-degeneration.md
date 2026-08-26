# [SOURCE] arXiv 1904.09751 — The Curious Case of Neural Text Degeneration (Nucleus Sampling)
# URL: https://arxiv.org/abs/1904.09751
# Retrieved: 2026-08-26 via webfetch
# Venue: ICLR 2020
# Authors: Ari Holtzman, Jan Buys, Li Du, Maxwell Forbes, Yejin Choi
# Purpose: chaesajang-style 스킬 개선 근거 자료 (디코딩·다양성 근거)

## Abstract

Despite considerable advancements with deep neural language models, the enigma of neural text degeneration persists when these models are tested as text generators. The counter-intuitive empirical observation is that even though the use of likelihood as training objective leads to high quality models for a broad range of language understanding tasks, **using likelihood as a decoding objective leads to text that is bland and strangely repetitive**.

In this paper, we reveal surprising distributional differences between human text and machine text. In addition, we find that decoding strategies alone can dramatically effect the quality of machine text, even when generated from exactly the same neural language model.

Our findings motivate **Nucleus Sampling**, a simple but effective method to draw the best out of neural generation. By sampling text from the dynamic nucleus of the probability distribution, which allows for diversity while effectively truncating the less reliable tail of the distribution, the resulting text better demonstrates the quality of human text, yielding enhanced diversity without sacrificing fluency and coherence.

## 스킬 개선 관련 시사점

딥리서치 2의 디코딩 권고(temperature 0.6~0.8 vs 0.9~1.0 A/B, top_p 단독 조정)의 이론적 기반.
반복적·퇴행적 생성 문제 = 문체 과적합(같은 기교 반복)과 동일한 현상 계열.
