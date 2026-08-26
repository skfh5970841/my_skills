# [SOURCE] OpenAI — Prompting guide
# URL: https://developers.openai.com/api/docs/guides/prompting
# Retrieved: 2026-08-26 via webfetch
# Note: prompt-engineering 가이드와 대부분 중복. 요지만 보존.

## Refine your prompt

- Put overall tone or role guidance in the system message; keep task-specific details and examples in user messages.
- Combine few-shot examples into a concise YAML-style or bulleted block so your team can scan and update them.
- Run your prompt tests and evaluation cases every time you publish; catching issues early is cheaper than fixing them in production.

## Prompts in your application

Treat prompts as application code. Store prompt content in named modules, build dynamic sections with typed function arguments, and review prompt changes in the same pull requests as the product behavior they support.

(OpenAI는 reusable prompt objects를 폐지 예정 — 프롬프트를 코드로 관리 권장.)
