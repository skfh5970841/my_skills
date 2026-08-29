# 채사장 계열 Research-Eval Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 외부 연구와 fresh Codex 출력 평가를 연결하고, 격리 후보가 자동·인간 gate를 통과해 사용자 승인을 받은 경우에만 채사장 계열 정본을 갱신하는 `chaesajang-family-optimizer` 스킬을 구축한다.

**Architecture:** `chaesajang-family-v2/family.yaml`이 다섯 스킬과 공통 코어의 정본·생성물 경계를 선언한다. 관리 스킬 안의 Python 패키지가 연구 근거, 실험 상태, 후보 사본, Codex 명령 실행, 평가, 블라인드 자료, 보고서와 승격을 단계별로 처리한다. 모든 후보는 `experiments/<id>/candidate/source` 안에서만 바뀌며, `promote --approved-by-user` 전에는 canonical source와 설치본을 쓰지 않는다.

**Tech Stack:** Python 3.11+, PyYAML 6.x, pytest, 표준 라이브러리 `dataclasses/pathlib/subprocess/hashlib/json/zipfile/difflib`, 기존 `sync_core.py`, Codex CLI command adapter

**Spec:** `docs/superpowers/specs/2026-08-29-chaesajang-research-eval-flywheel.md`

## Global Constraints

- 관리 대상은 `chaesajang-advisor`, `chaesajang-style`, `chaesajang-dialogue`, `chaesajang-style-youtube-scripter`, `chaesajang-write-teacher`, `chaesajang-core`다.
- 행동 출력은 Codex에서만 평가하고 Claude는 정적 호환성만 검사한다.
- 패밀리 내부 라우팅 정확도는 최적화하지 않는다. 명시적 호출·세션 연속성 smoke test만 유지한다.
- 한 실험은 하나의 instruction 묶음 또는 하나의 reference 전략만 변경한다.
- 위험 변경은 사용자 1인의 익명 A/B·B/A 블라인드 평가를 요구하며 통계적 우월성이라고 표현하지 않는다.
- 오류·시간 초과·빈 출력은 PASS나 0점이 아니라 `blocked_external` 또는 `invalid`다.
- 사용자 승인 전에는 canonical source, 설치본, 외부 배포를 변경하지 않는다.
- 기존 `graphify-out/`, `prompts/`와 다른 사용자 미추적 파일을 수정하지 않는다.
- 구현 중 git commit은 사용자가 로컬 커밋을 명시적으로 승인한 경우에만 만들며, 승인 시 모든 add/commit은 `conventional-commit-batcher` 스킬을 사용한다.

---

### Task 1: 관리 스킬 골격, 정본 registry, write-teacher 편입

**Files:**
- Create: `chaesajang-family-v2/family.yaml`
- Create: `chaesajang-family-v2/requirements.txt`
- Create: `chaesajang-family-v2/.gitignore`
- Create: `chaesajang-family-v2/experiments/README.md`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/SKILL.md`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/references/research-protocol.md`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/references/evaluation-protocol.md`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/references/promotion-policy.md`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/__init__.py`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/registry.py`
- Create: `chaesajang-family-v2/chaesajang-write-teacher/SKILL.md` from `C:/Users/leech/.codex/skills/chaesajang-write-teacher/SKILL.md`
- Create: `chaesajang-family-v2/chaesajang-write-teacher/agents/openai.yaml`
- Create: `chaesajang-family-v2/chaesajang-write-teacher/references/core-judgment-loop.md`
- Create: `chaesajang-family-v2/chaesajang-write-teacher/references/teaching-modes.md`
- Create: `chaesajang-family-v2/chaesajang-write-teacher/references/co-writing-flow.md`
- Create: `chaesajang-family-v2/chaesajang-write-teacher/references/rubric.md`
- Create: `chaesajang-family-v2/chaesajang-write-teacher/references/feedback-patterns.md`
- Create: `chaesajang-family-v2/chaesajang-write-teacher/references/assignment-bank.md`
- Create: `chaesajang-family-v2/chaesajang-write-teacher/references/teacher-anti-patterns.md`
- Create: `chaesajang-family-v2/chaesajang-write-teacher/references/chaesajang-style-principles.md`
- Test: `chaesajang-family-v2/tests/test_family_registry.py`

**Interfaces:**
- Produces: `SkillSpec(name: str, source: Path, core_files: tuple[str, ...], inject_gaze: bool)`
- Produces: `FamilyRegistry(root: Path, core: Path, skills: tuple[SkillSpec, ...], generated: dict)`
- Produces: `load_registry(root: Path) -> FamilyRegistry`
- Produces: `FamilyRegistry.canonical_paths() -> tuple[Path, ...]`

- [ ] **Step 1: Write the failing registry and manager-skill tests**

```python
def test_registry_declares_exactly_five_managed_skills(repo_root):
    registry = load_registry(repo_root / "chaesajang-family-v2")
    assert {skill.name for skill in registry.skills} == {
        "chaesajang-advisor",
        "chaesajang-style",
        "chaesajang-dialogue",
        "chaesajang-style-youtube-scripter",
        "chaesajang-write-teacher",
    }

def test_optimizer_is_neutral_and_requires_approval(repo_root):
    text = (
        repo_root
        / "chaesajang-family-v2"
        / "chaesajang-family-optimizer"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "중립적인 연구자" in text
    assert "사용자 승인" in text
    assert "채사장 역할극" in text
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest chaesajang-family-v2/tests/test_family_registry.py -q`

Expected: FAIL because the registry package and optimizer skill do not exist.

- [ ] **Step 3: Implement the registry and skill skeleton**

Use this exact core mapping in `family.yaml`:

```yaml
schema_version: 1
core: chaesajang-core
skills:
  - name: chaesajang-style
    source: chaesajang-style
    core_files: [persona_core.md, handoff_core.md, anti_patterns_core.md, reference_core.md, template_core.md, transformation_core.md]
    inject_gaze: true
  - name: chaesajang-advisor
    source: chaesajang-advisor
    core_files: [persona_core.md, handoff_core.md, anti_patterns_core.md, reference_core.md, template_core.md, transformation_core.md]
    inject_gaze: false
  - name: chaesajang-dialogue
    source: chaesajang-dialogue
    core_files: [persona_core.md, handoff_core.md]
    inject_gaze: false
  - name: chaesajang-style-youtube-scripter
    source: chaesajang-style-youtube-scripter
    core_files: [persona_core.md, handoff_core.md, anti_patterns_core.md, reference_core.md, template_core.md, transformation_core.md, anti_patterns_youtube.md, reference_youtube.md, template_youtube.md, transformation_youtube.md]
    inject_gaze: true
  - name: chaesajang-write-teacher
    source: chaesajang-write-teacher
    core_files: []
    inject_gaze: false
generated:
  compatibility_snapshots: skills
  dist: dist
  experiments: experiments
  package_extension: .skill
adapters:
  codex:
    exclude: []
  claude:
    exclude: [agents]
```

`load_registry` must reject duplicate names, missing canonical directories, unknown top-level keys, absolute source paths, and resolved paths outside the family root. Copy the installed teacher without modifying its source and preserve its `agents/openai.yaml`.

The manager `SKILL.md` must expose `bootstrap`, `cycle`, `resume`, `report`, and `promote`; load the three reference files by phase; state that it never role-plays the target author; and require an evidence-linked single-change hypothesis before candidate creation. `research-protocol.md` carries the initial/delta research rules, four full-refresh triggers, source hierarchy, and evidence-card schema from the spec. `evaluation-protocol.md` carries split isolation, six axes, adaptive 1-then-3 generation ladder, one-person blind wording, and the five-skill persona layering. `promotion-policy.md` carries terminal/error states, artifact requirements, rollback, and explicit-approval gates.

Write `requirements.txt` as `PyYAML>=6.0,<7` and `pytest>=8,<9`. Write `.gitignore` so `dist/` and every raw `experiments/*` child are ignored while `experiments/README.md` remains tracked. The README states that raw generations may contain private or copyrighted source material and must not be committed by default.

- [ ] **Step 4: Run validation and the focused test**

Run:

```powershell
python -m pytest chaesajang-family-v2/tests/test_family_registry.py -q
python C:/Users/leech/.codex/skills/.system/skill-creator/scripts/quick_validate.py chaesajang-family-v2/chaesajang-family-optimizer
python C:/Users/leech/.codex/skills/.system/skill-creator/scripts/quick_validate.py chaesajang-family-v2/chaesajang-write-teacher
```

Expected: all commands exit 0.

- [ ] **Step 5: Create a task checkpoint only if local commits were explicitly authorized**

Use `conventional-commit-batcher` with the task files and intent `feat(skills): scaffold chaesajang family optimizer`.

### Task 2: 실험 manifest, 상태 전이, 단계별 artifact 계약

**Files:**
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/contracts.py`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/artifacts.py`
- Test: `chaesajang-family-v2/tests/test_experiment_contracts.py`

**Interfaces:**
- Consumes: `FamilyRegistry`
- Produces: `ExperimentStatus(str, Enum)`
- Produces: `ExperimentManifest.from_dict(data: dict) -> ExperimentManifest`
- Produces: `ExperimentManifest.to_dict() -> dict`
- Produces: `transition(manifest: ExperimentManifest, target: ExperimentStatus) -> ExperimentManifest`
- Produces: `required_artifacts(status: ExperimentStatus, risk: str) -> tuple[str, ...]`
- Produces: `validate_artifacts(experiment_dir: Path, manifest: ExperimentManifest, risk: str) -> list[str]`
- Produces: `read_jsonl(path: Path) -> list[dict]`
- Produces: `write_jsonl(path: Path, rows: Iterable[dict]) -> None`

- [ ] **Step 1: Write failing state and artifact tests**

```python
def test_manifest_round_trips_provenance():
    manifest = ExperimentManifest.from_dict({
        "experiment_id": "2026-08-29-001",
        "status": "researching",
        "source_hashes": {"chaesajang-core/persona_core.md": "abc"},
        "model": "gpt-5.6",
        "runtime": "codex",
        "reasoning": "high",
        "dataset_versions": {"dev": "v1", "golden": "v1", "holdout": "v1"},
        "command": ["codex", "exec"],
        "created_at": "2026-08-29T22:00:00+09:00",
    })
    assert ExperimentManifest.from_dict(manifest.to_dict()) == manifest

def test_ready_for_approval_requires_human_files_for_risky_change(tmp_path):
    manifest = make_manifest(status="ready_for_approval", risk="behavior")
    missing = validate_artifacts(tmp_path, manifest, risk="behavior")
    assert "blind_pairs.jsonl" in missing
    assert "human_ratings.jsonl" in missing
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest chaesajang-family-v2/tests/test_experiment_contracts.py -q`

Expected: FAIL because contracts do not exist.

- [ ] **Step 3: Implement exact states and transition validation**

Allow only:

```python
ALLOWED = {
    "researching": {"hypothesis_ready", "blocked_external", "invalid"},
    "hypothesis_ready": {"baseline_captured", "rejected", "invalid"},
    "baseline_captured": {"candidate_ready", "rejected", "blocked_external", "invalid"},
    "candidate_ready": {"auto_evaluated", "rejected", "blocked_external", "invalid"},
    "auto_evaluated": {"awaiting_human", "ready_for_approval", "rejected", "invalid"},
    "awaiting_human": {"ready_for_approval", "rejected", "invalid"},
    "ready_for_approval": {"promoted", "rejected", "invalid"},
    "promoted": set(),
    "rejected": set(),
    "blocked_external": {"researching", "hypothesis_ready", "baseline_captured", "candidate_ready"},
    "invalid": set(),
}
```

Use atomic writes with a temporary sibling and `os.replace`. Reject unknown fields, missing fields, path traversal in experiment IDs, and transition attempts that skip a state. Require artifacts only for stages already completed; do not require future-stage files.

- [ ] **Step 4: Run the focused test**

Run: `python -m pytest chaesajang-family-v2/tests/test_experiment_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Create a conditional checkpoint**

If commits are authorized, use `conventional-commit-batcher` with intent `feat(loop): add experiment state contracts`.

### Task 3: canonical snapshot과 연구 근거 저장

**Files:**
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/snapshot.py`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/research.py`
- Create: `chaesajang-family-v2/research/index.jsonl`
- Create: `chaesajang-family-v2/research/cards/README.md`
- Test: `chaesajang-family-v2/tests/test_snapshot_research.py`

**Interfaces:**
- Consumes: `FamilyRegistry.canonical_paths()`, `write_jsonl`
- Produces: `snapshot_registry(registry: FamilyRegistry) -> dict[str, str]`
- Produces: `combined_snapshot_hash(snapshot: Mapping[str, str]) -> str`
- Produces: `normalize_claim(data: dict) -> dict`
- Produces: `append_claim(path: Path, claim: dict) -> None`
- Produces: `select_delta_claims(claims: Iterable[dict], since: date, tags: set[str]) -> list[dict]`

- [ ] **Step 1: Write failing hash and evidence tests**

```python
def test_snapshot_changes_when_canonical_text_changes(tmp_path, registry_factory):
    registry = registry_factory(tmp_path)
    before = snapshot_registry(registry)
    (tmp_path / "chaesajang-core" / "persona_core.md").write_text("changed", encoding="utf-8")
    assert snapshot_registry(registry) != before

def test_low_confidence_preprint_cannot_be_actionable_alone():
    claim = normalize_claim({
        "claim": "x",
        "source_url": "https://example.test/paper",
        "source_date": "2026-08-20",
        "checked_at": "2026-08-29",
        "source_type": "preprint",
        "evidence": "controlled observation",
        "confidence": "low",
        "local_evidence": ["persona_core.md"],
        "decision_impact": "change a rule",
        "proposed_test": "A/B",
    })
    assert claim["status"] == "watchlist"
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest chaesajang-family-v2/tests/test_snapshot_research.py -q`

Expected: FAIL because snapshot and research modules do not exist.

- [ ] **Step 3: Implement stable hashes and claim rules**

Hash UTF-8 file bytes with SHA-256, store POSIX relative paths, sort before computing the combined hash, and exclude `dist/`, `experiments/`, `.skill`, compatibility snapshots, caches, and git metadata.

`normalize_claim` requires exactly the fields in the spec, verifies `http://` or `https://` source URLs, ISO dates, enumerated source type/confidence, non-empty local evidence, decision impact, and proposed test. Mark a low-confidence or unsupported preprint/blog claim `watchlist`; never silently drop it.

Seed `research/index.jsonl` with normalized records for the nine URLs in the spec. Each record must map to a local decision and a proposed test; do not copy long verbatim excerpts.

- [ ] **Step 4: Run the focused test**

Run: `python -m pytest chaesajang-family-v2/tests/test_snapshot_research.py -q`

Expected: PASS.

- [ ] **Step 5: Create a conditional checkpoint**

If commits are authorized, use `conventional-commit-batcher` with intent `feat(loop): record research evidence and canonical snapshots`.

### Task 4: 가설 frontmatter와 격리 후보

**Files:**
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/hypothesis.py`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/candidate.py`
- Test: `chaesajang-family-v2/tests/test_candidate_isolation.py`

**Interfaces:**
- Consumes: `FamilyRegistry`, `snapshot_registry`
- Produces: `Hypothesis.from_markdown(path: Path) -> Hypothesis`
- Produces: `create_candidate(registry: FamilyRegistry, experiment_dir: Path) -> Path`
- Produces: `changed_canonical_files(registry: FamilyRegistry, candidate_root: Path, baseline: Mapping[str, str]) -> tuple[str, ...]`
- Produces: `validate_change_scope(hypothesis: Hypothesis, changed: Iterable[str]) -> list[str]`
- Produces: `write_candidate_patch(registry: FamilyRegistry, candidate_root: Path, output: Path) -> None`

- [ ] **Step 1: Write failing isolation and one-change tests**

```python
def test_candidate_edit_does_not_touch_canonical(tmp_path, registry_factory):
    registry = registry_factory(tmp_path)
    experiment = tmp_path / "experiments" / "exp-1"
    candidate = create_candidate(registry, experiment)
    target = candidate / "chaesajang-core" / "persona_core.md"
    target.write_text("candidate", encoding="utf-8")
    assert (tmp_path / "chaesajang-core" / "persona_core.md").read_text(encoding="utf-8") != "candidate"

def test_two_change_groups_are_invalid(hypothesis):
    errors = validate_change_scope(
        hypothesis,
        ["chaesajang-core/persona_core.md", "chaesajang-advisor/SKILL.md"],
    )
    assert errors
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest chaesajang-family-v2/tests/test_candidate_isolation.py -q`

Expected: FAIL because hypothesis and candidate modules do not exist.

- [ ] **Step 3: Implement safe candidate copying and scope checks**

`hypothesis.md` must start with YAML frontmatter containing:

```yaml
claim_ids: [claim-id]
change_group: persona-layering
allowed_paths: [chaesajang-core/persona_core.md]
primary_axis: over_imitation
protected_axes: [request_fulfillment, meaning_and_facts, structure_and_information]
risk: behavior
blind_required: true
stop_rule: reject if a hard gate fails or baseline weakness cannot be reproduced
```

Resolve every allowed and copied path under the family root. Copy only registry-declared canonical paths into `candidate/source`. Preserve canonical bytes. Reject symlinks that resolve outside the root. A change is in scope only when every changed path is covered by `allowed_paths` and every path belongs to one `change_group`. Produce a unified UTF-8 patch with `difflib.unified_diff`; binary changes are invalid.

- [ ] **Step 4: Run the focused test**

Run: `python -m pytest chaesajang-family-v2/tests/test_candidate_isolation.py -q`

Expected: PASS.

- [ ] **Step 5: Create a conditional checkpoint**

If commits are authorized, use `conventional-commit-batcher` with intent `feat(loop): isolate single-hypothesis candidates`.

### Task 5: 정본 렌더러, Codex·Claude 어댑터, static gate

**Files:**
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/render.py`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/static_gate.py`
- Modify: `chaesajang-family-v2/sync_core.py`
- Test: `chaesajang-family-v2/tests/test_render_static_gate.py`

**Interfaces:**
- Consumes: `FamilyRegistry`
- Produces: `render_skill(registry: FamilyRegistry, skill: SkillSpec, source_root: Path, destination: Path, runtime: str) -> dict[str, str]`
- Produces: `render_all(registry: FamilyRegistry, source_root: Path, dist_root: Path) -> dict[str, dict[str, str]]`
- Produces: `package_skill(skill_dir: Path, output: Path) -> str`
- Produces: `GateResult(passed: bool, errors: tuple[str, ...], details: dict)`
- Produces: `run_static_gate(registry: FamilyRegistry, source_root: Path, dist_root: Path) -> GateResult`

- [ ] **Step 1: Write failing adapter and drift tests**

```python
def test_claude_adapter_excludes_agents_directory(tmp_path, real_registry):
    render_all(real_registry, real_registry.root, tmp_path / "dist")
    assert not (
        tmp_path / "dist" / "claude" / "chaesajang-write-teacher" / "agents"
    ).exists()

def test_invalid_frontmatter_and_snapshot_drift_both_reported(tmp_path, registry_factory):
    registry = registry_factory(tmp_path)
    corrupt_frontmatter_and_snapshot(tmp_path)
    result = run_static_gate(registry, tmp_path, tmp_path / "dist")
    assert len(result.errors) >= 2
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest chaesajang-family-v2/tests/test_render_static_gate.py -q`

Expected: FAIL because render and gate modules do not exist.

- [ ] **Step 3: Implement deterministic rendering**

For each skill, copy its canonical tree to a temporary destination, overwrite registry-declared common references from `chaesajang-core`, and inject the exact `CORE:gaze` block only when `inject_gaze: true`. Render Codex with all files and Claude without paths listed in `adapters.claude.exclude`.

Generate `skills/<name>.SKILL.md` from the rendered Codex entrypoint. Create every `.skill` as a ZIP containing one top-level `<name>/` directory. Sort paths and normalize ZIP timestamps so identical inputs yield identical hashes.

`run_static_gate` must collect, rather than short-circuit, errors for YAML frontmatter, name-directory mismatch, broken relative references, core drift, duplicate markers, compatibility snapshot drift, adapter drift, ZIP layout, and package hash mismatch.

Replace `sync_core.py` internals with a compatibility wrapper around the registry renderer while preserving `--root`, `--check`, exit 0 for clean, and exit 2 for drift.

- [ ] **Step 4: Run old and new static tests**

Run:

```powershell
python -m pytest chaesajang-family-v2/tests/test_render_static_gate.py chaesajang-family-v2/tests/test_feedback_core_update.py -q
python chaesajang-family-v2/sync_core.py
python chaesajang-family-v2/sync_core.py --check
```

Expected: tests PASS; the write mode regenerates only declared generated files; the following check reports no drift.

- [ ] **Step 5: Create a conditional checkpoint**

If commits are authorized, use `conventional-commit-batcher` with intent `feat(loop): generate portable skill adapters`.

### Task 6: Codex command adapter와 fresh baseline/candidate 생성

**Files:**
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/runner.py`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/generate.py`
- Test: `chaesajang-family-v2/tests/test_codex_runner.py`

**Interfaces:**
- Consumes: `ExperimentManifest`, `FamilyRegistry`, `write_jsonl`
- Produces: `RunConfig(command: tuple[str, ...], cwd: Path, timeout_seconds: int, stdin_text: str, model: str, reasoning: str, runtime: str, expect_json: bool = False)`
- Produces: `RunResult(status: str, returncode: int | None, stdout: str, stderr: str, elapsed_ms: int)`
- Produces: `run_command(config: RunConfig) -> RunResult`
- Produces: `build_generation_prompt(case: dict, skill_path: Path) -> str`
- Produces: `generate_cases(cases: Iterable[dict], source_root: Path, config: RunConfig, repeats: int) -> list[dict]`

- [ ] **Step 1: Write failing error-semantics and parity tests**

```python
def test_nonzero_and_empty_output_are_not_passes(tmp_path):
    failed = run_command(RunConfig(
        (sys.executable, "-c", "raise SystemExit(3)"), tmp_path, 5, "",
        "fake-model", "high", "codex", False,
    ))
    empty = run_command(RunConfig(
        (sys.executable, "-c", "pass"), tmp_path, 5, "",
        "fake-model", "high", "codex", False,
    ))
    assert failed.status == "blocked_external"
    assert empty.status == "blocked_external"

def test_generation_records_model_settings_and_repeat_index(fake_runner, tmp_path):
    rows = generate_cases([case("x")], tmp_path, fake_runner, repeats=3)
    assert [row["repeat"] for row in rows] == [0, 1, 2]
    assert all(row["model"] == fake_runner.model for row in rows)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest chaesajang-family-v2/tests/test_codex_runner.py -q`

Expected: FAIL because runner and generator do not exist.

- [ ] **Step 3: Implement shell-free subprocess execution**

Use `subprocess.run(command, input=stdin_text, text=True, capture_output=True, timeout=...)` without `shell=True`. Treat non-zero exit, timeout, and whitespace-only stdout as `blocked_external`; preserve stderr and return code. Parse JSON only when `expect_json` is true, and in that mode treat malformed JSON as `blocked_external`. Ordinary writing outputs remain plain text.

The default real command assembled by the CLI is:

```python
(
    "codex", "exec",
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "--sandbox", "read-only",
    "--color", "never",
    "--model", manifest.model,
    "--config", f'model_reasoning_effort="{manifest.reasoning}"',
    "--cd", str(source_root),
    "-"
)
```

`build_generation_prompt` explicitly tells Codex to read the selected local `SKILL.md` and only the references that skill requires, make no file changes, then answer the case input. Store raw output, source snapshot, case ID, repeat, exact command, model, reasoning, runtime, start time, elapsed time, and status.

- [ ] **Step 4: Run the focused test**

Run: `python -m pytest chaesajang-family-v2/tests/test_codex_runner.py -q`

Expected: PASS without making a network call.

- [ ] **Step 5: Create a conditional checkpoint**

If commits are authorized, use `conventional-commit-batcher` with intent `feat(loop): run reproducible Codex generations`.

### Task 7: eval split, 누출 검사, 다축 score 계약

**Files:**
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/evals.py`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/judge.py`
- Create: `chaesajang-family-v2/evals/dev/README.md`
- Create: `chaesajang-family-v2/evals/golden/README.md`
- Create: `chaesajang-family-v2/evals/holdout/README.md`
- Test: `chaesajang-family-v2/tests/test_evals.py`

**Interfaces:**
- Produces: `EvalCase.from_dict(data: dict, split: str) -> EvalCase`
- Produces: `load_cases(path: Path, split: str) -> list[EvalCase]`
- Produces: `validate_split_isolation(splits: Mapping[str, Sequence[EvalCase]]) -> list[str]`
- Produces: `score_deterministic(case: EvalCase, output: str) -> dict[str, dict]`
- Produces: `validate_external_scores(rows: Iterable[dict]) -> list[str]`
- Produces: `aggregate_scores(rows: Iterable[dict]) -> dict`
- Produces: `build_judge_prompt(case: EvalCase, left: dict, right: dict, order: str) -> str`
- Produces: `judge_pairs(case: EvalCase, baseline: dict, candidate: dict, config: RunConfig) -> list[dict]`

- [ ] **Step 1: Write failing split and axis tests**

```python
def test_same_source_group_cannot_cross_splits():
    splits = {
        "dev": [eval_case("a", source_group="book-1/chapter-2")],
        "holdout": [eval_case("b", source_group="book-1/chapter-2")],
    }
    assert validate_split_isolation(splits)

def test_hard_gates_remain_separate_from_style():
    scores = score_deterministic(
        eval_case("x", required_terms=["결론"], forbidden_terms=["허위"]),
        "결론",
    )
    assert scores["request_fulfillment"]["passed"] is True
    assert "style_behavior" in scores
    assert "overall_score" not in scores

def test_codex_judge_runs_both_orders(fake_json_runner):
    rows = judge_pairs(eval_case("x"), output("old"), output("new"), fake_json_runner)
    assert {row["order"] for row in rows} == {"AB", "BA"}
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest chaesajang-family-v2/tests/test_evals.py -q`

Expected: FAIL because eval contracts do not exist.

- [ ] **Step 3: Implement data and score validation**

Each case requires `case_id`, `target_skill`, `source_group`, `generator_brief`, `axes`, `risk`, and deterministic checks. An optional `evaluator_reference` may exist only in evaluator-only records and must never appear in a generation row.

Reject duplicate case IDs, duplicate content hashes, a source group spanning splits, normalized character 8-gram Jaccard similarity of 0.85 or greater across splits, unknown axes, and holdout references found in candidate prompts.

Keep these top-level axes separate: `request_fulfillment`, `meaning_and_facts`, `structure_and_information`, `style_behavior`, `over_imitation`, `resource_use`. Deterministic scoring handles required/forbidden text, length ranges, exact facts/checklist items, output presence, and longest source overlap.

`judge_pairs` uses `RunConfig(expect_json=True)`, evaluator-only references, an explicit six-axis JSON schema, and both AB/BA orders. Judge rows must include rubric version, order, both response lengths, model, reasoning, per-axis result, and explanation; invalid rows fail validation instead of receiving zero. The aggregate keeps AB/BA disagreement visible and labels all judge results `supporting_only`, so no downstream gate can treat them as human approval.

- [ ] **Step 4: Run the focused test**

Run: `python -m pytest chaesajang-family-v2/tests/test_evals.py -q`

Expected: PASS.

- [ ] **Step 5: Create a conditional checkpoint**

If commits are authorized, use `conventional-commit-batcher` with intent `feat(loop): add isolated multi-axis evals`.

### Task 8: 블라인드 패키지, 사용자 rating, 승인 보고서

**Files:**
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/blind.py`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/report.py`
- Test: `chaesajang-family-v2/tests/test_blind_report.py`

**Interfaces:**
- Consumes: `ExperimentManifest`, `Hypothesis`, `GateResult`, aggregated scores
- Produces: `make_blind_pairs(baseline_rows: Sequence[dict], candidate_rows: Sequence[dict], seed: int) -> list[dict]`
- Produces: `validate_order_balance(pairs: Sequence[dict]) -> list[str]`
- Produces: `normalize_human_rating(data: dict, known_pair_ids: set[str]) -> dict`
- Produces: `decide_readiness(manifest: ExperimentManifest, hypothesis: Hypothesis, gate: GateResult, scores: dict, ratings: Sequence[dict]) -> str`
- Produces: `build_report(...) -> str`

- [ ] **Step 1: Write failing anonymity and promotion tests**

```python
def test_blind_pairs_hide_identity_and_balance_order(baseline_rows, candidate_rows):
    pairs = make_blind_pairs(baseline_rows, candidate_rows, seed=7)
    assert {pair["order"] for pair in pairs} == {"AB", "BA"}
    assert all("baseline" not in json.dumps(pair).lower() for pair in pairs)
    assert all("candidate" not in json.dumps(pair).lower() for pair in pairs)

def test_risky_change_cannot_be_ready_without_candidate_preference(
    manifest, behavior_hypothesis, passing_gate
):
    decision = decide_readiness(
        manifest, behavior_hypothesis, passing_gate, passing_scores(), [],
    )
    assert decision == "awaiting_human"
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest chaesajang-family-v2/tests/test_blind_report.py -q`

Expected: FAIL because blind and report modules do not exist.

- [ ] **Step 3: Implement the one-person blind protocol**

Pair only matching case IDs and repeat indices. Use a recorded seed, anonymous pair IDs, equal A/B and B/A coverage, and exclude model/runtime/path metadata from the blind file. A human rating must answer `quality_preference`, `style_preference`, `over_imitation`, `meaning_or_fact_issue`, and `evidence_excerpt`.

A low-risk static-only change can become `ready_for_approval` after static and golden gates. A risky change remains `awaiting_human` until the user prefers the candidate overall, reports no critical meaning/fact issue, and protected golden cases remain passing. State explicitly in `report.md` that one-person results are user preference, not statistical superiority.

The report must list research claims, local evidence, one-change diff, raw artifact paths, per-axis results, regressions, user ratings, limitations, exact hashes/commands, and the files that promotion would modify.

- [ ] **Step 4: Run the focused test**

Run: `python -m pytest chaesajang-family-v2/tests/test_blind_report.py -q`

Expected: PASS.

- [ ] **Step 5: Create a conditional checkpoint**

If commits are authorized, use `conventional-commit-batcher` with intent `feat(loop): gate promotion on blind preference`.

### Task 9: 안전한 promotion과 고수준 CLI 모드

**Files:**
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/promote.py`
- Create: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/optimizer_loop/cli.py`
- Modify: `chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py`
- Test: `chaesajang-family-v2/tests/test_cli_promotion.py`

**Interfaces:**
- Consumes: all Tasks 1-8 interfaces
- Produces: `next_action(manifest: ExperimentManifest) -> str`
- Produces: `promote(experiment_dir: Path, registry: FamilyRegistry, approved_by_user: bool, install: bool = False) -> dict`
- Produces CLI modes: `bootstrap`, `cycle`, `resume`, `report`, `promote`

- [ ] **Step 1: Write failing approval and resume tests**

```python
def test_promote_rejects_missing_explicit_approval(tmp_path, ready_experiment, registry):
    with pytest.raises(PermissionError):
        promote(ready_experiment, registry, approved_by_user=False)

def test_resume_returns_first_incomplete_stage(manifest_factory):
    manifest = manifest_factory(status="baseline_captured")
    assert next_action(manifest) == "candidate"
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest chaesajang-family-v2/tests/test_cli_promotion.py -q`

Expected: FAIL because CLI and promotion modules do not exist.

- [ ] **Step 3: Implement explicit modes and transactional promotion**

`loop.py` delegates to `optimizer_loop.cli.main`. Mode behavior:

```text
loop.py bootstrap --experiment ID --model MODEL --reasoning LEVEL
loop.py cycle --experiment ID [--claims FILE] [--hypothesis FILE] [--cases DIR] [--ratings FILE] [--timeout SECONDS]
loop.py resume --experiment ID [--timeout SECONDS]
loop.py report --experiment ID
loop.py promote --experiment ID --approved-by-user [--install-root DIR]
```

- `bootstrap --experiment ID --model MODEL --reasoning LEVEL`: create manifest, snapshot, and research import instructions; never browse silently from Python.
- `cycle --experiment ID`: validate the current artifact, print and execute only deterministic stages whose required input already exists, and stop at research judgment, candidate editing, external failure, human rating, or approval.
- `resume --experiment ID`: report `next_action` and continue from that stage without re-running successful stages.
- `report --experiment ID`: read-only report generation.
- `promote --experiment ID --approved-by-user [--install-root DIR]`: require `ready_for_approval` and complete artifacts. Supplying `--install-root` is the only way to request installation.

Promotion first copies candidate files into a temporary sibling, renders and validates adapters there, and creates byte-for-byte backups of every canonical file that will change. Only after every gate passes may it use `os.replace`; if any replacement or post-write hash check fails, restore every changed file from those backups and mark the experiment `invalid`. Record pre- and post-promotion hashes. Without `--install-root`, do not touch paths outside the repository. With `--install-root`, resolve every destination from the explicit argument and reject broad targets, missing expected skill directories, and targets outside the named install root.

- [ ] **Step 4: Run the focused test and CLI help**

Run:

```powershell
python -m pytest chaesajang-family-v2/tests/test_cli_promotion.py -q
python chaesajang-family-v2/chaesajang-family-optimizer/scripts/loop.py --help
```

Expected: tests PASS and help lists the five high-level modes.

- [ ] **Step 5: Create a conditional checkpoint**

If commits are authorized, use `conventional-commit-batcher` with intent `feat(loop): add resumable approval-gated CLI`.

### Task 10: golden 자료 이관, 종단 dry run, 문서와 전체 검증

**Files:**
- Create: `chaesajang-family-v2/evals/golden/fb_001.jsonl`
- Create: `chaesajang-family-v2/evals/golden/fb_002.jsonl`
- Create: `chaesajang-family-v2/evals/golden/fb_003.jsonl`
- Create: `chaesajang-family-v2/evals/golden/interaction_cases.jsonl`
- Create: `chaesajang-family-v2/evals/dev/optimizer_smoke.jsonl`
- Create: `chaesajang-family-v2/tests/test_end_to_end_loop.py`
- Modify: `chaesajang-family-v2/tests/test_feedback_core_update.py`
- Modify: `origin/analysis/trigger_eval/run_trigger_eval.py`
- Modify: `chaesajang-family-v2/README.md`

**Interfaces:**
- Consumes: all prior task interfaces without bypasses

- [ ] **Step 1: Write the failing end-to-end and legacy-error tests**

```python
def test_dry_run_reaches_ready_without_touching_canonical(tmp_path, fixture_family):
    before = snapshot_registry(fixture_family.registry)
    result = run_fake_low_risk_cycle(fixture_family, tmp_path)
    assert result.status == "ready_for_approval"
    assert snapshot_registry(fixture_family.registry) == before

def test_trigger_runner_error_is_failure_not_negative_pass(monkeypatch):
    monkeypatch.setattr(trigger_runner, "invoke", failing_invoke)
    result = trigger_runner.evaluate_case({"expected_trigger": False})
    assert result["status"] == "blocked_external"
    assert result["passed"] is False
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest chaesajang-family-v2/tests/test_end_to_end_loop.py -q
python -m pytest chaesajang-family-v2/tests/test_feedback_core_update.py -q
```

Expected: at least the new end-to-end and error-semantics tests FAIL.

- [ ] **Step 3: Migrate immutable cases and finish integration**

Transcribe FB-001~003 without changing their original feedback files. Every record includes `case_id`, `target_skill`, `source_group`, `generator_brief`, `axes`, `risk`, `before_hash`, deterministic checks, and provenance path. Where the feedback note has mutated before-text, record the ambiguity explicitly and do not fabricate an original.

`interaction_cases.jsonl` covers explicit invocation and session continuity only. `optimizer_smoke.jsonl` covers: no evidence means no candidate, low-risk packaging skips human blind, persona change requires human blind, failed command becomes `blocked_external`, and unapproved promotion is denied.

Fix the legacy trigger runner so an exception, missing CLI, timeout, malformed output, or incomplete repeat produces a non-zero process result and `blocked_external`; it must never count as negative-case PASS.

Document the file ownership rules, bootstrap/cycle/resume/report/promote commands, human-rating file format, blocked states, and the fact that a real Codex run may incur latency/cost.

- [ ] **Step 4: Run complete verification**

Run:

```powershell
python -m pytest chaesajang-family-v2/tests -q
python chaesajang-family-v2/sync_core.py --check
python C:/Users/leech/.codex/skills/.system/skill-creator/scripts/quick_validate.py chaesajang-family-v2/chaesajang-family-optimizer
python C:/Users/leech/.codex/skills/.system/skill-creator/scripts/quick_validate.py chaesajang-family-v2/chaesajang-advisor
python C:/Users/leech/.codex/skills/.system/skill-creator/scripts/quick_validate.py chaesajang-family-v2/chaesajang-style
python C:/Users/leech/.codex/skills/.system/skill-creator/scripts/quick_validate.py chaesajang-family-v2/chaesajang-dialogue
python C:/Users/leech/.codex/skills/.system/skill-creator/scripts/quick_validate.py chaesajang-family-v2/chaesajang-style-youtube-scripter
python C:/Users/leech/.codex/skills/.system/skill-creator/scripts/quick_validate.py chaesajang-family-v2/chaesajang-write-teacher
```

Expected: all commands exit 0. A live Codex-unavailable check is reported `blocked_external`, never PASS.

- [ ] **Step 5: Run one read-only live Codex smoke only when credentials are available**

Run one `optimizer_smoke` case against canonical and one against its identical candidate using `--sandbox read-only`. Store the raw results in an experiment directory. If the command is unavailable, record `blocked_external` and leave deterministic verification green.

- [ ] **Step 6: Create a conditional checkpoint**

If commits are authorized, use `conventional-commit-batcher` with intent `feat(loop): complete chaesajang optimizer flywheel`.

## Plan Self-Review Checklist

- Every requirement in the spec is assigned to Tasks 1-10.
- The same registry, manifest, status strings, axis names, and artifact names are used across tasks.
- No task may modify canonical content before Task 9 promotion with explicit approval.
- Tests use fake commands except the optional read-only live smoke in Task 10.
- No task rewrites the original FB notes or the existing user-owned `graphify-out/` and `prompts/` files.
- Implementation commits remain conditional on explicit user authorization.
