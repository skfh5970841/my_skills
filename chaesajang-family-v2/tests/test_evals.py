import copy
import json
import math
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest


AXES = (
    "request_fulfillment",
    "meaning_and_facts",
    "structure_and_information",
    "style_behavior",
    "over_imitation",
    "resource_use",
)


@pytest.fixture
def loop_modules():
    scripts = Path(__file__).resolve().parents[1] / "chaesajang-family-optimizer" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from optimizer_loop import evals, judge, runner

        yield evals, judge, runner
    finally:
        for name in ("optimizer_loop.evals", "optimizer_loop.judge", "optimizer_loop"):
            sys.modules.pop(name, None)
        sys.path.remove(str(scripts))


def case_data(case_id="case-1", **overrides):
    value = {
        "case_id": case_id,
        "target_skill": "chaesajang-style",
        "source_group": f"fixture/{case_id}",
        "generator_brief": "인공지능의 한계를 쉬운 한국어로 설명하세요.",
        "axes": list(AXES),
        "risk": "behavior",
        "deterministic_checks": {
            "output_present": True,
            "required_terms": ["결론"],
            "forbidden_terms": ["허위"],
            "min_characters": 2,
            "max_characters": 200,
            "exact_facts": ["사실 하나"],
            "checklist_items": ["핵심 질문"],
            "max_source_overlap_characters": 12,
        },
        "evaluator_reference": "평가 전용 원문은 생성 프롬프트에 노출되면 안 된다.",
    }
    value.update(overrides)
    return value


def eval_case(evals, case_id="case-1", split="dev", **overrides):
    return evals.EvalCase.from_dict(case_data(case_id, **overrides), split)


def output_row(text, case_id="case-1", **overrides):
    row = {
        "case_id": case_id,
        "target_skill": "chaesajang-style",
        "repeat": 0,
        "input": case_data(case_id)["generator_brief"],
        "prompt": "Neutral generation prompt shared by both conditions",
        "output": text,
        "stderr": "",
        "command": ["codex", "exec", "-"],
        "cwd": "C:/source",
        "timeout_seconds": 30,
        "model": "gpt-test",
        "reasoning": "high",
        "runtime": "codex",
        "elapsed_ms": 1,
        "status": "completed",
        "returncode": 0,
        "source_stable": True,
    }
    row.update(overrides)
    return row


def expected_pair(case, repeat=0):
    return {
        "case_id": case.case_id,
        "target_skill": case.target_skill,
        "split": case.split,
        "repeat": repeat,
    }


def deterministic_pair(evals, case, repeat=0, text="핵심 질문. 결론. 사실 하나."):
    provenance = {
        "case_id": case.case_id,
        "target_skill": case.target_skill,
        "repeat": repeat,
        "input": case.generator_brief,
    }
    return [
        evals.make_deterministic_row(
            case, output_row(text, **provenance), "baseline"
        ),
        evals.make_deterministic_row(
            case, output_row(text, **provenance), "candidate"
        ),
    ]


def valid_judge_payload(winner="A"):
    return {
        "axes": {
            axis: {"winner": winner, "explanation": f"{axis} 근거"}
            for axis in AXES
        },
        "overall_explanation": "전체 판단 근거",
    }


def run_config(runner, tmp_path, *, runtime="codex", expect_json=False):
    return runner.RunConfig(
        command=("codex", "exec", "-"),
        cwd=tmp_path,
        timeout_seconds=30,
        stdin_text="replaced",
        model="gpt-test",
        reasoning="high",
        runtime=runtime,
        expect_json=expect_json,
    )


def test_eval_case_is_frozen_records_split_and_normalizes_collections(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(evals)

    assert case.split == "dev"
    assert case.axes == AXES
    assert case.deterministic_checks["required_terms"] == ("결론",)
    with pytest.raises(FrozenInstanceError):
        case.case_id = "changed"
    with pytest.raises(TypeError):
        case.deterministic_checks["min_characters"] = 0


@pytest.mark.parametrize(
    "mutation, message",
    [
        ({"extra": True}, "unknown"),
        ({"case_id": None}, "case_id"),
        ({"case_id": "bad\x00id"}, "control"),
        ({"target_skill": "../outside"}, "target_skill"),
        ({"target_skill": "C:/outside"}, "target_skill"),
        ({"axes": ["style_behavior", "style_behavior"]}, "duplicate"),
        ({"axes": ["made_up"]}, "unknown"),
        ({"risk": ""}, "risk"),
        ({"evaluator_reference": "   "}, "evaluator_reference"),
        ({"deterministic_checks": {"made_up": 1}}, "unknown"),
        ({"deterministic_checks": {"min_characters": True}}, "min_characters"),
        (
            {"deterministic_checks": {"min_characters": 9, "max_characters": 2}},
            "range",
        ),
        (
            {"deterministic_checks": {"max_source_overlap_characters": 3}, "evaluator_reference": None},
            "evaluator_reference",
        ),
    ],
)
def test_eval_case_rejects_unknown_missing_unsafe_and_inconsistent_data(
    loop_modules, mutation, message
):
    evals, _, _ = loop_modules
    data = case_data()
    if "extra" in mutation:
        data["extra"] = mutation["extra"]
    else:
        data.update(mutation)
        if mutation.get("evaluator_reference") is None:
            data.pop("evaluator_reference", None)

    with pytest.raises((TypeError, ValueError), match=message):
        evals.EvalCase.from_dict(data, "dev")


def test_eval_case_rejects_missing_required_field_and_invalid_split(loop_modules):
    evals, _, _ = loop_modules
    data = case_data()
    data.pop("generator_brief")

    with pytest.raises(ValueError, match="missing"):
        evals.EvalCase.from_dict(data, "dev")
    with pytest.raises(ValueError, match="split"):
        evals.EvalCase.from_dict(case_data(), "training")


def test_load_cases_reads_strict_jsonl_and_rejects_duplicate_id_or_content(
    tmp_path, loop_modules
):
    evals, _, _ = loop_modules
    valid_path = tmp_path / "valid.jsonl"
    valid_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in (
                case_data("one"),
                case_data("two", generator_brief="완전히 다른 요청입니다."),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    assert [case.case_id for case in evals.load_cases(valid_path, "dev")] == ["one", "two"]

    duplicate_id = tmp_path / "duplicate-id.jsonl"
    duplicate_id.write_text(
        "\n".join(json.dumps(case_data("same"), ensure_ascii=False) for _ in range(2)),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate case_id"):
        evals.load_cases(duplicate_id, "dev")

    duplicate_content = tmp_path / "duplicate-content.jsonl"
    duplicate_content.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in (
                case_data("a"),
                case_data("b", source_group="fixture/b"),
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate.*generator_brief"):
        evals.load_cases(duplicate_content, "dev")

    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text('{"case_id": ', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        evals.load_cases(malformed, "dev")


def test_split_isolation_collects_ids_groups_exact_and_near_duplicates(loop_modules):
    evals, _, _ = loop_modules
    dev = eval_case(evals, "dev-1", generator_brief="가나다라마바사아자차카타파하", source_group="book/chapter")
    holdout = eval_case(
        evals,
        "holdout-1",
        split="holdout",
        generator_brief="가나다라마바사아자차카타파하!",
        source_group="book/chapter",
    )
    duplicate_id = eval_case(
        evals,
        "dev-1",
        split="golden",
        generator_brief="서로 다른 요청",
        evaluator_reference="서로 다른 평가 원문",
        source_group="other/group",
        deterministic_checks={"output_present": True},
    )

    errors = evals.validate_split_isolation(
        {"dev": [dev], "holdout": [holdout], "golden": [duplicate_id]}
    )

    assert any("duplicate case_id" in error for error in errors)
    assert any("source_group" in error for error in errors)
    assert any("8-gram" in error and "generator_brief" in error for error in errors)


def test_split_isolation_checks_references_separately_and_handles_short_text(loop_modules):
    evals, _, _ = loop_modules
    dev = eval_case(
        evals,
        "a",
        generator_brief="긴 개발 요청 하나",
        evaluator_reference="짧음",
        deterministic_checks={"output_present": True},
    )
    holdout = eval_case(
        evals,
        "b",
        split="holdout",
        generator_brief="완전히 별개의 홀드아웃 요청",
        evaluator_reference="짧음!",
        deterministic_checks={"output_present": True},
    )

    errors = evals.validate_split_isolation({"dev": [dev], "holdout": [holdout]})

    assert any("evaluator_reference" in error and "duplicate" in error for error in errors)
    assert not any("generator_brief" in error and "duplicate" in error for error in errors)


def test_holdout_reference_leakage_scans_generation_rows_but_allows_briefs(loop_modules):
    evals, _, _ = loop_modules
    holdout = eval_case(
        evals,
        "h",
        split="holdout",
        generator_brief="이 중립 요청은 생성에 허용된다.",
        evaluator_reference="비공개 평가 원문 여덟글자 이상",
    )
    clean = {
        "case_id": "h",
        "input": holdout.generator_brief,
        "prompt": f"Generator brief: {holdout.generator_brief}",
    }
    leaked = {
        "case_id": "h",
        "prompt": "앞부분 비공개 평가 원문 여덟글자 이상 뒷부분",
    }

    assert evals.validate_holdout_leakage([holdout], [clean]) == []
    errors = evals.validate_holdout_leakage([holdout], [clean, leaked])
    assert len(errors) == 1
    assert "evaluator_reference" in errors[0]


def test_deterministic_scores_keep_six_axes_separate_with_literal_evidence(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(evals)
    text = "핵심 질문. 결론. 사실 하나."

    scores = evals.score_deterministic(case, text)

    assert tuple(scores) == AXES
    assert "overall_score" not in scores
    assert scores["request_fulfillment"]["passed"] is True
    request_evidence = scores["request_fulfillment"]["evidence"]
    assert request_evidence["output_present"] is True
    assert request_evidence["required_terms"] == {"결론": True}
    assert request_evidence["forbidden_terms"] == {"허위": False}
    assert request_evidence["checklist_items"] == {"핵심 질문": True}
    assert scores["meaning_and_facts"]["passed"] is True
    assert scores["meaning_and_facts"]["evidence"]["exact_facts"] == {"사실 하나": True}
    assert scores["structure_and_information"]["passed"] is True
    assert scores["style_behavior"]["passed"] is None
    assert scores["style_behavior"]["status"] == "not_scored"
    assert scores["resource_use"]["passed"] is None


def test_empty_and_non_string_outputs_fail_without_crashing(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(evals)

    for output in ("", "   ", None, 42):
        scores = evals.score_deterministic(case, output)
        assert scores["request_fulfillment"]["passed"] is False
        assert scores["request_fulfillment"]["evidence"]["output_present"] is False
        assert scores["meaning_and_facts"]["passed"] is False
        assert scores["structure_and_information"]["passed"] is False
        assert scores["over_imitation"]["passed"] is False


def test_overlap_uses_longest_contiguous_normalized_match_and_threshold(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(
        evals,
        evaluator_reference="가 나, 다! 라마바사",
        deterministic_checks={"max_source_overlap_characters": 4},
    )

    scores = evals.score_deterministic(case, "앞말 가나다라마 뒷말")

    evidence = scores["over_imitation"]["evidence"]
    assert evidence["longest_normalized_source_overlap_characters"] == 5
    assert evidence["max_source_overlap_characters"] == 4
    assert scores["over_imitation"]["passed"] is False


def test_unconfigured_axes_are_not_invented_as_passes(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(
        evals,
        deterministic_checks={"output_present": True},
        evaluator_reference="평가 자료",
    )

    scores = evals.score_deterministic(case, "응답")

    assert scores["request_fulfillment"]["passed"] is True
    for axis in AXES[1:]:
        assert scores[axis]["passed"] is None
        assert scores[axis]["status"] == "not_scored"


def test_build_judge_prompt_is_anonymous_evaluator_only_and_strict(loop_modules):
    evals, judge, _ = loop_modules
    case = eval_case(evals)
    prompt = judge.build_judge_prompt(case, output_row("old"), output_row("new"), "AB")

    assert "Response A:\nold" in prompt
    assert "Response B:\nnew" in prompt
    assert case.evaluator_reference in prompt
    assert "baseline" not in prompt.casefold()
    assert "candidate" not in prompt.casefold()
    assert all(axis in prompt for axis in AXES)
    assert "overall_explanation" in prompt
    with pytest.raises(ValueError, match="order"):
        judge.build_judge_prompt(case, output_row("old"), output_row("new"), "AA")
    with pytest.raises(ValueError, match="output"):
        judge.build_judge_prompt(case, {"output": ""}, output_row("new"), "AB")


def test_codex_judge_runs_ab_and_ba_and_maps_labels_back(
    tmp_path, loop_modules, monkeypatch
):
    evals, judge, runner = loop_modules
    case = eval_case(evals)
    calls = []

    def fake_run(config):
        calls.append(config)
        return runner.RunResult(
            "completed", 0, json.dumps(valid_judge_payload("A"), ensure_ascii=False), "", 7
        )

    monkeypatch.setattr(judge, "run_command", fake_run)
    rows = judge.judge_pairs(
        case,
        output_row("old response"),
        output_row("new response"),
        run_config(runner, tmp_path),
    )

    assert [row["order"] for row in rows] == ["AB", "BA"]
    assert [row["axis_results"]["style_behavior"]["winner"] for row in rows] == [
        "baseline",
        "candidate",
    ]
    assert [row["label_map"] for row in rows] == [
        {"A": "baseline", "B": "candidate"},
        {"A": "candidate", "B": "baseline"},
    ]
    assert all(row["role"] == "supporting_only" for row in rows)
    assert all(row["status"] == "valid" for row in rows)
    assert all(row["baseline_length"] == len("old response") for row in rows)
    assert all(row["candidate_length"] == len("new response") for row in rows)
    assert all(row["model"] == "gpt-test" and row["reasoning"] == "high" for row in rows)
    assert all(row["runtime"] == "codex" and row["repeat"] == 0 for row in rows)
    assert all(row["rubric_version"] == judge.RUBRIC_VERSION for row in rows)
    assert all(row["row_type"] == "judge" for row in rows)
    assert rows[0]["pair_id"] == rows[1]["pair_id"]
    assert len(rows[0]["pair_id"]) == 64
    assert rows[0]["parity_signature"] == rows[1]["parity_signature"]
    assert all(row["command"] == ["codex", "exec", "-"] for row in rows)
    assert all(row["cwd"] == str(tmp_path) for row in rows)
    assert all(row["timeout_seconds"] == 30 for row in rows)
    assert all(row["returncode"] == 0 and row["elapsed_ms"] == 7 for row in rows)
    assert all(len(row["prompt_sha256"]) == 64 for row in rows)
    assert rows[0]["prompt_sha256"] != rows[1]["prompt_sha256"]
    assert all(row["raw_output"] for row in rows)
    assert all(call.expect_json is True for call in calls)
    assert all(call.runtime == "codex" for call in calls)
    assert "Response A:\nnew response" in calls[1].stdin_text
    assert "Response B:\nold response" in calls[1].stdin_text


def test_judge_rejects_non_codex_runtime_before_execution(
    tmp_path, loop_modules, monkeypatch
):
    evals, judge, runner = loop_modules
    monkeypatch.setattr(judge, "run_command", lambda _: pytest.fail("must not run"))

    with pytest.raises(ValueError, match="codex"):
        judge.judge_pairs(
            eval_case(evals),
            output_row("old"),
            output_row("new"),
            run_config(runner, tmp_path, runtime="claude"),
        )


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        json.dumps({"axes": {}, "overall_explanation": "partial"}),
        '{"axes": {}, "overall_explanation": NaN}',
        json.dumps(
            {
                **valid_judge_payload(),
                "axes": {
                    **valid_judge_payload()["axes"],
                    "style_behavior": {"winner": "A", "explanation": ""},
                },
            }
        ),
    ],
)
def test_malformed_partial_nan_and_schema_invalid_judge_rows_stay_invalid(
    tmp_path, loop_modules, monkeypatch, payload
):
    evals, judge, runner = loop_modules
    monkeypatch.setattr(
        judge,
        "run_command",
        lambda _: runner.RunResult("completed", 0, payload, "", 1),
    )

    rows = judge.judge_pairs(
        eval_case(evals), output_row("old"), output_row("new"), run_config(runner, tmp_path)
    )

    assert len(rows) == 2
    assert all(row["status"] == "invalid" for row in rows)
    assert evals.validate_external_scores(rows)
    assert all("axis_results" not in row for row in rows)


def test_blocked_runner_rows_stay_blocked_and_fail_external_validation(
    tmp_path, loop_modules, monkeypatch
):
    evals, judge, runner = loop_modules
    monkeypatch.setattr(
        judge,
        "run_command",
        lambda _: runner.RunResult("blocked_external", None, "", "offline", 2),
    )

    rows = judge.judge_pairs(
        eval_case(evals), output_row("old"), output_row("new"), run_config(runner, tmp_path)
    )

    assert all(row["status"] == "blocked_external" for row in rows)
    assert all(row["raw_output"] == "" and row["stderr"] == "offline" for row in rows)
    assert evals.validate_external_scores(rows)


def test_external_score_validation_rejects_missing_values_and_nonfinite_numbers(loop_modules):
    evals, _, _ = loop_modules
    incomplete = {
        "case_id": "x",
        "order": "AB",
        "role": "supporting_only",
        "status": "valid",
        "axis_results": {},
        "overall_explanation": "why",
    }
    poisoned = dict(incomplete, axis_results={axis: {"winner": "tie", "explanation": "ok"} for axis in AXES})
    poisoned["numeric_score"] = math.nan

    assert evals.validate_external_scores([incomplete])
    assert evals.validate_external_scores([poisoned])


def test_aggregate_preserves_axes_counts_and_ab_ba_disagreement(
    tmp_path, loop_modules, monkeypatch
):
    evals, judge, runner = loop_modules
    case = eval_case(evals)
    baseline = output_row("핵심 질문. 결론. 사실 하나.")
    candidate = output_row("핵심 질문. 결론. 사실 하나.")
    winners = iter(("A", "A"))
    monkeypatch.setattr(
        judge,
        "run_command",
        lambda _: runner.RunResult(
            "completed",
            0,
            json.dumps(valid_judge_payload(next(winners)), ensure_ascii=False),
            "",
            1,
        ),
    )
    rows = judge.judge_pairs(
        case, baseline, candidate, run_config(runner, tmp_path)
    )
    deterministic_rows = [
        evals.make_deterministic_row(case, baseline, "baseline"),
        evals.make_deterministic_row(case, candidate, "candidate"),
    ]

    aggregate = evals.aggregate_scores([*deterministic_rows, *rows])

    judge_aggregate = aggregate["judge"]
    assert judge_aggregate["role"] == "supporting_only"
    assert judge_aggregate["row_count"] == 2
    assert tuple(aggregate["axes"]) == AXES
    assert judge_aggregate["axes"]["style_behavior"] == {
        "baseline": 1,
        "candidate": 1,
        "tie": 0,
        "count": 2,
    }
    disagreement = judge_aggregate["ab_ba_disagreement"]["style_behavior"]
    assert disagreement["compared_pairs"] == 1
    assert disagreement["disagreements"] == 1
    assert "ready_for_approval" not in aggregate
    assert "human_approval" not in aggregate


def test_aggregate_rejects_invalid_rows_instead_of_averaging(loop_modules):
    evals, _, _ = loop_modules
    with pytest.raises(ValueError, match="invalid external score"):
        evals.aggregate_scores([{"status": "invalid"}])


def test_holdout_leakage_ignores_non_generator_output_and_stderr(loop_modules):
    evals, _, _ = loop_modules
    holdout = eval_case(
        evals,
        "holdout-output",
        split="holdout",
        evaluator_reference="비공개 평가 원문은 오직 평가기에만 보여야 합니다",
    )
    row = output_row(
        holdout.evaluator_reference,
        case_id=holdout.case_id,
        input=holdout.generator_brief,
        prompt=f"Generator brief: {holdout.generator_brief}",
        stderr=holdout.evaluator_reference,
    )

    assert evals.validate_holdout_leakage([holdout], [row]) == []


def test_holdout_leakage_detects_meaningful_partial_but_not_tiny_phrase(loop_modules):
    evals, _, _ = loop_modules
    reference = "고유한비공개평가원문일부분이외부생성문맥으로노출되면안됩니다"
    holdout = eval_case(
        evals,
        "holdout-partial",
        split="holdout",
        evaluator_reference=reference,
    )
    threshold = evals.MIN_PARTIAL_LEAK_CHARACTERS
    assert threshold == 16
    partial = reference[3 : 3 + threshold]

    partial_errors = evals.validate_holdout_leakage(
        [holdout], [{"prompt": f"앞부분 {partial} 뒷부분"}]
    )
    tiny_errors = evals.validate_holdout_leakage(
        [holdout], [{"prompt": "비공개 평가 원문"}]
    )

    assert any("partial" in error for error in partial_errors)
    assert tiny_errors == []


def test_holdout_leakage_detects_near_full_variant_inside_prompt(loop_modules):
    evals, _, _ = loop_modules
    reference = "".join(chr(0xAC00 + index) for index in range(120))
    near_variant = reference[:60] + "힣" + reference[61:]
    holdout = eval_case(
        evals,
        "holdout-near",
        split="holdout",
        evaluator_reference=reference,
    )

    errors = evals.validate_holdout_leakage(
        [holdout],
        [
            {
                "prompt": f"unrelated-prefix-{near_variant}-unrelated-suffix",
                "research_cards": [{"content": "safe"}],
            }
        ],
    )

    assert any("8-gram" in error for error in errors)


@pytest.mark.parametrize(
    "mutation, message",
    [
        ({"target_skill": "Uppercase"}, "target_skill"),
        ({"target_skill": "double--hyphen"}, "target_skill"),
        ({"target_skill": "a" * 65}, "target_skill"),
        ({"case_id": "../case"}, "case_id"),
        (
            {"deterministic_checks": {"required_terms": []}},
            "required_terms",
        ),
        (
            {"deterministic_checks": {"output_present": False}},
            "output_present",
        ),
        (
            {
                "deterministic_checks": {
                    "required_terms": ["같은 말"],
                    "forbidden_terms": ["같은말"],
                }
            },
            "contradiction",
        ),
        (
            {
                "axes": [axis for axis in AXES if axis != "meaning_and_facts"],
            },
            "meaning_and_facts",
        ),
        ({"deterministic_checks": {"min_characters": 0}}, "min_characters"),
        ({"deterministic_checks": {"max_characters": 0}}, "max_characters"),
        (
            {
                "deterministic_checks": {"max_source_overlap_characters": 99},
                "evaluator_reference": "짧은 평가 원문",
            },
            "overlap",
        ),
    ],
)
def test_eval_case_enforces_strict_nonvacuous_contract(loop_modules, mutation, message):
    evals, _, _ = loop_modules
    data = case_data()
    data.update(mutation)

    with pytest.raises((TypeError, ValueError), match=message):
        evals.EvalCase.from_dict(data, "dev")


def test_eval_case_allows_tabs_and_newlines_only_in_narrative_text(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(
        evals,
        generator_brief="첫 줄\n\t둘째 줄",
        evaluator_reference="평가 줄 하나\n\t평가 줄 둘",
        deterministic_checks={"output_present": True},
    )

    assert "\n\t" in case.generator_brief
    assert "\n\t" in case.evaluator_reference
    with pytest.raises(ValueError, match="control"):
        eval_case(
            evals,
            generator_brief="unsafe\u000btext",
            deterministic_checks={"output_present": True},
        )


def test_split_validation_rejects_unknown_keys_and_duplicates_within_a_split(loop_modules):
    evals, _, _ = loop_modules
    first = eval_case(
        evals,
        "same-id",
        generator_brief="중복 생성 요청",
        evaluator_reference="중복 평가 원문",
        source_group="same/group",
        deterministic_checks={"output_present": True},
    )
    duplicate_id_and_generator = eval_case(
        evals,
        "same-id",
        generator_brief="중복 생성 요청!",
        evaluator_reference="서로 다른 평가 원문",
        source_group="same/group",
        deterministic_checks={"output_present": True},
    )
    duplicate_reference = eval_case(
        evals,
        "third-id",
        generator_brief="완전히 다른 생성 요청",
        evaluator_reference="중복 평가 원문!",
        source_group="same/group",
        deterministic_checks={"output_present": True},
    )

    errors = evals.validate_split_isolation(
        {"dev": [first, duplicate_id_and_generator, duplicate_reference], "training": []}
    )

    assert any("unknown split" in error for error in errors)
    assert any("duplicate case_id" in error for error in errors)
    assert any("duplicate" in error and "generator_brief" in error for error in errors)
    assert any("duplicate" in error and "evaluator_reference" in error for error in errors)
    assert not any("source_group" in error for error in errors)


def test_split_validation_uses_short_text_near_similarity_fallback(loop_modules):
    evals, _, _ = loop_modules
    dev = eval_case(
        evals,
        "short-dev",
        generator_brief="abcdefg",
        evaluator_reference="평가자료하나",
        source_group="dev/group",
        deterministic_checks={"output_present": True},
    )
    holdout = eval_case(
        evals,
        "short-holdout",
        split="holdout",
        generator_brief="abcdefx",
        evaluator_reference="별개평가자료",
        source_group="holdout/group",
        deterministic_checks={"output_present": True},
    )

    errors = evals.validate_split_isolation({"dev": [dev], "holdout": [holdout]})

    assert any("short-text" in error and "generator_brief" in error for error in errors)


def test_validate_case_targets_binds_cases_to_registry_membership(loop_modules):
    evals, _, _ = loop_modules
    registry = SimpleNamespace(
        skills=(SimpleNamespace(name="chaesajang-style"), SimpleNamespace(name="other-skill"))
    )

    assert evals.validate_case_targets([eval_case(evals)], registry) == []
    errors = evals.validate_case_targets(
        [eval_case(evals, target_skill="missing-skill")], registry
    )
    assert len(errors) == 1
    assert "target_skill" in errors[0]


@pytest.mark.parametrize(
    "side, field, value, message",
    [
        ("baseline", "status", "blocked_external", "completed"),
        ("candidate", "source_stable", False, "stable"),
        ("candidate", "case_id", "other-case", "case_id"),
        ("candidate", "target_skill", "other-skill", "target_skill"),
        ("candidate", "repeat", 1, "repeat"),
        ("candidate", "model", "other-model", "model"),
        ("candidate", "reasoning", "low", "reasoning"),
        ("candidate", "runtime", "claude", "runtime"),
        ("candidate", "input", "other input", "input"),
        ("candidate", "prompt", "other prompt", "prompt"),
    ],
)
def test_judge_rejects_generation_pair_mismatch_before_execution(
    tmp_path, loop_modules, monkeypatch, side, field, value, message
):
    evals, judge, runner = loop_modules
    baseline = output_row("old")
    candidate = output_row("new")
    target = baseline if side == "baseline" else candidate
    target[field] = value
    monkeypatch.setattr(judge, "run_command", lambda _: pytest.fail("must not run"))

    with pytest.raises(ValueError, match=message):
        judge.judge_pairs(
            eval_case(evals), baseline, candidate, run_config(runner, tmp_path)
        )


@pytest.mark.parametrize(
    "field, value",
    [("model", "other-model"), ("reasoning", "low"), ("runtime", "claude")],
)
def test_judge_config_must_match_generation_provenance_before_execution(
    tmp_path, loop_modules, monkeypatch, field, value
):
    evals, judge, runner = loop_modules
    config = replace(run_config(runner, tmp_path), **{field: value})
    monkeypatch.setattr(judge, "run_command", lambda _: pytest.fail("must not run"))

    with pytest.raises(ValueError, match=field):
        judge.judge_pairs(
            eval_case(evals), output_row("old"), output_row("new"), config
        )


def test_pair_ids_are_stable_per_repeat_and_distinct_between_repeats(
    tmp_path, loop_modules, monkeypatch
):
    evals, judge, runner = loop_modules
    monkeypatch.setattr(
        judge,
        "run_command",
        lambda _: runner.RunResult(
            "completed", 0, json.dumps(valid_judge_payload()), "", 1
        ),
    )
    case = eval_case(evals)

    repeat_zero = judge.judge_pairs(
        case,
        output_row("old", repeat=0),
        output_row("new", repeat=0),
        run_config(runner, tmp_path),
    )
    repeat_one = judge.judge_pairs(
        case,
        output_row("old", repeat=1),
        output_row("new", repeat=1),
        run_config(runner, tmp_path),
    )

    assert len({row["pair_id"] for row in repeat_zero}) == 1
    assert len({row["pair_id"] for row in repeat_one}) == 1
    assert repeat_zero[0]["pair_id"] != repeat_one[0]["pair_id"]


def test_make_deterministic_row_is_typed_and_preserves_pair_parity(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(evals, split="golden")
    baseline = output_row("핵심 질문. 결론. 사실 하나.", repeat=2)
    candidate = output_row("핵심 질문. 결론. 사실 하나.", repeat=2)

    baseline_row = evals.make_deterministic_row(case, baseline, "baseline")
    candidate_row = evals.make_deterministic_row(case, candidate, "candidate")

    assert baseline_row["row_type"] == candidate_row["row_type"] == "deterministic"
    assert baseline_row["split"] == candidate_row["split"] == "golden"
    assert baseline_row["repeat"] == candidate_row["repeat"] == 2
    assert baseline_row["parity_signature"] == candidate_row["parity_signature"]
    assert tuple(baseline_row["scores"]) == AXES
    assert baseline_row["condition"] == "baseline"
    assert candidate_row["condition"] == "candidate"


def test_aggregate_requires_complete_unique_parity_matched_deterministic_pairs(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(evals)
    baseline_generation = output_row("핵심 질문. 결론. 사실 하나.")
    candidate_generation = output_row("핵심 질문. 결론. 사실 하나.")
    baseline = evals.make_deterministic_row(case, baseline_generation, "baseline")
    candidate = evals.make_deterministic_row(case, candidate_generation, "candidate")

    with pytest.raises(ValueError, match="complete.*baseline.*candidate"):
        evals.aggregate_scores([baseline])
    with pytest.raises(ValueError, match="duplicate"):
        evals.aggregate_scores([baseline, copy.deepcopy(baseline), candidate])

    mismatched_generation = output_row(
        "핵심 질문. 결론. 사실 하나.", prompt="different prompt"
    )
    mismatched = evals.make_deterministic_row(
        case, mismatched_generation, "candidate"
    )
    with pytest.raises(ValueError, match="parity"):
        evals.aggregate_scores([baseline, mismatched])


def test_aggregate_reports_candidate_hard_gate_and_golden_failures(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(evals, split="golden")
    baseline = evals.make_deterministic_row(
        case, output_row("핵심 질문. 결론. 사실 하나."), "baseline"
    )
    candidate = evals.make_deterministic_row(
        case, output_row("허위"), "candidate"
    )

    aggregate = evals.aggregate_scores([candidate, baseline])

    assert aggregate["deterministic_pair_count"] == 1
    assert aggregate["axes"]["request_fulfillment"]["baseline"]["passed"] == 1
    assert aggregate["axes"]["request_fulfillment"]["candidate"]["failed"] == 1
    assert {item["axis"] for item in aggregate["hard_gate_failures"]} == {
        "request_fulfillment",
        "meaning_and_facts",
    }
    assert {item["axis"] for item in aggregate["golden_failures"]} == {
        "request_fulfillment",
        "meaning_and_facts",
    }
    assert aggregate["hard_gates_passed"] is False
    assert aggregate["golden_passed"] is False
    assert aggregate["judge"]["role"] == "supporting_only"
    assert aggregate["judge"]["row_count"] == 0
    assert "ready_for_approval" not in aggregate
    assert "human_approval" not in aggregate


def test_judge_aggregate_pairs_shuffled_multiple_repeats_by_pair_id(
    tmp_path, loop_modules, monkeypatch
):
    evals, judge, runner = loop_modules
    case = eval_case(evals)
    monkeypatch.setattr(
        judge,
        "run_command",
        lambda _: runner.RunResult(
            "completed", 0, json.dumps(valid_judge_payload("A")), "", 1
        ),
    )
    deterministic_rows = []
    judge_rows = []
    for repeat in (0, 1):
        baseline = output_row("핵심 질문. 결론. 사실 하나.", repeat=repeat)
        candidate = output_row("핵심 질문. 결론. 사실 하나.", repeat=repeat)
        deterministic_rows.extend(
            (
                evals.make_deterministic_row(case, baseline, "baseline"),
                evals.make_deterministic_row(case, candidate, "candidate"),
            )
        )
        judge_rows.extend(
            judge.judge_pairs(case, baseline, candidate, run_config(runner, tmp_path))
        )
    shuffled = [
        judge_rows[3],
        deterministic_rows[1],
        judge_rows[0],
        deterministic_rows[3],
        judge_rows[2],
        deterministic_rows[0],
        judge_rows[1],
        deterministic_rows[2],
    ]

    aggregate = evals.aggregate_scores(shuffled)

    assert aggregate["deterministic_pair_count"] == 2
    assert aggregate["judge"]["pair_count"] == 2
    assert aggregate["judge"]["row_count"] == 4
    assert aggregate["judge"]["ab_ba_disagreement"]["style_behavior"] == {
        "compared_pairs": 2,
        "disagreements": 2,
    }


def test_judge_aggregate_rejects_unbalanced_and_duplicate_orders(
    tmp_path, loop_modules, monkeypatch
):
    evals, judge, runner = loop_modules
    case = eval_case(evals)
    baseline_generation = output_row("핵심 질문. 결론. 사실 하나.")
    candidate_generation = output_row("핵심 질문. 결론. 사실 하나.")
    deterministic = [
        evals.make_deterministic_row(case, baseline_generation, "baseline"),
        evals.make_deterministic_row(case, candidate_generation, "candidate"),
    ]
    monkeypatch.setattr(
        judge,
        "run_command",
        lambda _: runner.RunResult(
            "completed", 0, json.dumps(valid_judge_payload()), "", 1
        ),
    )
    rows = judge.judge_pairs(
        case, baseline_generation, candidate_generation, run_config(runner, tmp_path)
    )

    with pytest.raises(ValueError, match="exactly one AB and BA"):
        evals.aggregate_scores([*deterministic, rows[0]])
    with pytest.raises(ValueError, match="exactly one AB and BA"):
        evals.aggregate_scores([*deterministic, rows[0], copy.deepcopy(rows[0]), rows[1]])


def test_valid_external_rows_reject_validation_errors_and_bad_provenance(
    tmp_path, loop_modules, monkeypatch
):
    evals, judge, runner = loop_modules
    monkeypatch.setattr(
        judge,
        "run_command",
        lambda _: runner.RunResult(
            "completed", 0, json.dumps(valid_judge_payload()), "", 1
        ),
    )
    valid = judge.judge_pairs(
        eval_case(evals), output_row("old"), output_row("new"), run_config(runner, tmp_path)
    )[0]
    mutations = {
        "validation_errors": ["must not coexist with valid"],
        "stderr": 7,
        "command": [],
        "cwd": "",
        "timeout_seconds": 0,
        "returncode": True,
        "elapsed_ms": -1,
        "prompt_sha256": "bad",
    }

    for field, value in mutations.items():
        poisoned = copy.deepcopy(valid)
        poisoned[field] = value
        errors = evals.validate_external_scores([poisoned])
        assert any(field in error for error in errors), (field, errors)


def test_real_json_runner_boundary_blocks_malformed_and_schema_invalid_rows(
    tmp_path, loop_modules, monkeypatch
):
    evals, judge, runner = loop_modules
    case = eval_case(evals)
    baseline = output_row("핵심 질문. 결론. 사실 하나.")
    candidate = output_row("핵심 질문. 결론. 사실 하나.")
    judge_config = run_config(runner, tmp_path)
    deterministic = [
        evals.make_deterministic_row(case, baseline, "baseline"),
        evals.make_deterministic_row(case, candidate, "candidate"),
    ]

    malformed_result = runner.run_command(
        replace(
            judge_config,
            command=(sys.executable, "-c", "print('{bad')"),
            expect_json=True,
        )
    )
    assert malformed_result.status == "blocked_external"
    monkeypatch.setattr(judge, "run_command", lambda _: malformed_result)
    malformed_rows = judge.judge_pairs(case, baseline, candidate, judge_config)
    assert all(row["status"] == "blocked_external" for row in malformed_rows)
    assert evals.validate_external_scores(malformed_rows)
    with pytest.raises(ValueError, match="invalid external score"):
        evals.aggregate_scores([*deterministic, *malformed_rows])

    partial_result = runner.run_command(
        replace(
            judge_config,
            command=(
                sys.executable,
                "-c",
                "import json; print(json.dumps({'axes': {}, 'overall_explanation': 'partial'}))",
            ),
            expect_json=True,
        )
    )
    assert partial_result.status == "completed"
    monkeypatch.setattr(judge, "run_command", lambda _: partial_result)
    partial_rows = judge.judge_pairs(case, baseline, candidate, judge_config)
    assert all(row["status"] == "invalid" for row in partial_rows)
    assert evals.validate_external_scores(partial_rows)
    with pytest.raises(ValueError, match="invalid external score"):
        evals.aggregate_scores([*deterministic, *partial_rows])


def test_aggregate_without_inventory_never_claims_passing_coverage(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(evals)

    aggregate = evals.aggregate_scores(deterministic_pair(evals, case))

    assert aggregate["coverage_verified"] is False
    assert aggregate["expected_pair_count"] is None
    assert aggregate["hard_gates_passed"] is None
    assert aggregate["golden_passed"] is None


def test_dev_only_inventory_has_no_vacuous_golden_pass(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(evals)

    aggregate = evals.aggregate_scores(
        deterministic_pair(evals, case), expected_pairs=[expected_pair(case)]
    )

    assert aggregate["coverage_verified"] is True
    assert aggregate["expected_pair_count"] == 1
    assert aggregate["expected_golden_pair_count"] == 0
    assert aggregate["hard_gates_passed"] is True
    assert aggregate["golden_passed"] is None


def test_aggregate_rejects_partial_golden_inventory(loop_modules):
    evals, _, _ = loop_modules
    first = eval_case(evals, "golden-one", split="golden")
    second = eval_case(evals, "golden-two", split="golden")

    with pytest.raises(ValueError, match="missing expected deterministic pair"):
        evals.aggregate_scores(
            deterministic_pair(evals, first),
            expected_pairs=[expected_pair(first), expected_pair(second)],
        )


def test_aggregate_rejects_missing_expected_repeat(loop_modules):
    evals, _, _ = loop_modules
    case = eval_case(evals)

    with pytest.raises(ValueError, match="missing expected deterministic pair"):
        evals.aggregate_scores(
            deterministic_pair(evals, case, repeat=0),
            expected_pairs=[expected_pair(case, 0), expected_pair(case, 1)],
        )


def test_aggregate_rejects_unexpected_extra_pair(loop_modules):
    evals, _, _ = loop_modules
    expected = eval_case(evals, "expected-case")
    extra = eval_case(evals, "extra-case")

    with pytest.raises(ValueError, match="unexpected deterministic pair"):
        evals.aggregate_scores(
            [
                *deterministic_pair(evals, expected),
                *deterministic_pair(evals, extra),
            ],
            expected_pairs=[expected_pair(expected)],
        )


def test_near_duplicates_are_allowed_within_one_split_but_not_across(loop_modules):
    evals, _, _ = loop_modules
    original = "".join(chr(0xAC00 + index) for index in range(120))
    variant = original[:60] + "힣" + original[61:]
    same_split_first = eval_case(
        evals,
        "same-one",
        generator_brief=original,
        evaluator_reference="첫 번째 평가 전용 원문은 충분히 길고 서로 다릅니다",
        source_group="shared/source",
    )
    same_split_second = eval_case(
        evals,
        "same-two",
        generator_brief=variant,
        evaluator_reference="두 번째 평가 전용 원문은 충분히 길고 서로 다릅니다",
        source_group="shared/source",
    )

    same_split_errors = evals.validate_split_isolation(
        {"dev": [same_split_first, same_split_second]}
    )

    assert not any("8-gram generator_brief" in error for error in same_split_errors)
    assert not any("source_group" in error for error in same_split_errors)

    holdout = eval_case(
        evals,
        "cross-split",
        split="holdout",
        generator_brief=variant,
        evaluator_reference="홀드아웃 평가 전용 원문도 충분히 길고 별개입니다",
        source_group="holdout/source",
    )
    cross_split_errors = evals.validate_split_isolation(
        {"dev": [same_split_first], "holdout": [holdout]}
    )
    assert any("8-gram generator_brief" in error for error in cross_split_errors)


def test_short_text_near_duplicates_are_allowed_only_within_one_split(loop_modules):
    evals, _, _ = loop_modules
    first = eval_case(
        evals,
        "short-one",
        generator_brief="abcdefg",
        deterministic_checks={"output_present": True},
        source_group="short/source",
    )
    second = eval_case(
        evals,
        "short-two",
        generator_brief="abcdefx",
        deterministic_checks={"output_present": True},
        source_group="short/source",
    )

    errors = evals.validate_split_isolation({"dev": [first, second]})

    assert not any("short-text generator_brief" in error for error in errors)


@pytest.mark.parametrize(
    "required, forbidden",
    [
        ("핵심 결론", "결론"),
        ("핵 심, 결론", "심결"),
    ],
)
def test_eval_case_rejects_forbidden_substrings_inside_normalized_required_terms(
    loop_modules, required, forbidden
):
    evals, _, _ = loop_modules
    data = case_data()
    data["deterministic_checks"] = {
        "required_terms": [required],
        "forbidden_terms": [forbidden],
    }

    with pytest.raises(ValueError, match="contradiction"):
        evals.EvalCase.from_dict(data, "dev")


def test_required_substring_of_forbidden_term_is_satisfiable(loop_modules):
    evals, _, _ = loop_modules
    data = case_data()
    data["deterministic_checks"] = {
        "required_terms": ["결론"],
        "forbidden_terms": ["핵 심, 결론"],
    }

    case = evals.EvalCase.from_dict(data, "dev")
    scores = evals.score_deterministic(case, "결론")

    assert scores["request_fulfillment"]["passed"] is True
    assert scores["request_fulfillment"]["evidence"]["required_terms"] == {
        "결론": True
    }
    assert scores["request_fulfillment"]["evidence"]["forbidden_terms"] == {
        "핵 심, 결론": False
    }


def test_eval_case_uses_exact_overlapping_superstring_length_for_maximum(loop_modules):
    evals, _, _ = loop_modules
    overlapping = case_data()
    overlapping["deterministic_checks"] = {
        "output_present": True,
        "required_terms": ["abcd", "cdef", "defg"],
        "max_characters": 7,
    }
    case = evals.EvalCase.from_dict(overlapping, "dev")
    assert case.deterministic_checks["max_characters"] == 7

    impossible = copy.deepcopy(overlapping)
    impossible["deterministic_checks"]["max_characters"] = 6
    with pytest.raises(ValueError, match="superstring|impossible"):
        evals.EvalCase.from_dict(impossible, "dev")


def test_eval_case_superstring_length_accounts_for_contained_literals(loop_modules):
    evals, _, _ = loop_modules
    data = case_data()
    data["deterministic_checks"] = {
        "required_terms": ["가나다라마바사", "나다라", "라마바사"],
        "max_characters": 7,
    }

    case = evals.EvalCase.from_dict(data, "dev")

    assert case.deterministic_checks["max_characters"] == 7


def test_eval_case_allows_twelve_noncontained_superstring_literals(loop_modules):
    evals, _, _ = loop_modules
    data = case_data()
    data["deterministic_checks"] = {
        "required_terms": [f"token-{index:02d}" for index in range(12)],
        "max_characters": 200,
    }

    case = evals.EvalCase.from_dict(data, "dev")

    assert len(case.deterministic_checks["required_terms"]) == 12


def test_eval_case_rejects_more_than_twelve_noncontained_superstring_literals(
    loop_modules,
):
    evals, _, _ = loop_modules
    data = case_data()
    data["deterministic_checks"] = {
        "required_terms": [f"token-{index:02d}" for index in range(13)],
        "max_characters": 300,
    }

    with pytest.raises(ValueError, match="at most 12|12.*literal|too many"):
        evals.EvalCase.from_dict(data, "dev")


def test_superstring_limit_is_applied_after_containment_pruning(loop_modules):
    evals, _, _ = loop_modules
    carrier = "abcdefghijklmnopqrstuvwx"
    data = case_data()
    data["deterministic_checks"] = {
        "required_terms": [carrier, *(carrier[:length] for length in range(2, 15))],
        "max_characters": len(carrier),
    }

    case = evals.EvalCase.from_dict(data, "dev")

    assert len(case.deterministic_checks["required_terms"]) == 14
