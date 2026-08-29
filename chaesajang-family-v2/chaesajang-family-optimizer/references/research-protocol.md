# Research protocol

## Initial and delta research

`bootstrap` performs an initial full review of Agent Skill design, progressive disclosure and context efficiency, prompt and agent optimization, eval-driven development, personalized style generation, blind human evaluation, automatic metrics and judge bias, meaning/fact preservation, and memorization or overfitting prevention.

Later `cycle` runs are delta research: investigate only material published since the last review and material connected to the observed local problem. Perform a full refresh only when one of these four triggers occurs:

1. The behavioral evaluation model or runtime changes substantially.
2. Core research evidence conflicts.
3. The author corpus or evaluation tasks expand substantially.
4. The user asks for a full re-research.

## Source hierarchy

Prefer, in order: official specifications and documentation; peer-reviewed primary research; trustworthy technical reports; then preprints and blogs. A preprint or a single blog alone cannot establish a canonical-change hypothesis.

## Evidence cards

Store each reusable claim with this schema:

```yaml
claim: 검증 가능한 주장
source_url: 원문 URL
source_date: 원문 발표일
checked_at: 조사일
source_type: official | peer_reviewed | technical_report | preprint | blog
evidence: 원문에서 확인한 근거 요약
confidence: high | medium | low
local_evidence: 현재 파일·출력·실패 사례
decision_impact: 이 저장소에서 바뀔 수 있는 결정
proposed_test: 주장을 반증할 수 있는 테스트
```

Material not connected to a current file, output, or failure remains on a watchlist. It cannot become a candidate change.
