import json
import math
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

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


def output_row(text, case_id="case-1"):
    return {"case_id": case_id, "output": text, "status": "completed"}


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
    )
    holdout = eval_case(
        evals,
        "b",
        split="holdout",
        generator_brief="완전히 별개의 홀드아웃 요청",
        evaluator_reference="짧음!",
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
    assert all(row["rubric_version"] == judge.RUBRIC_VERSION for row in rows)
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
        eval_case(evals), output_row("old"), output_row("new"), run_config(runner, tmp_path)
    )

    aggregate = evals.aggregate_scores(rows)

    assert aggregate["role"] == "supporting_only"
    assert aggregate["row_count"] == 2
    assert tuple(aggregate["axes"]) == AXES
    assert aggregate["axes"]["style_behavior"] == {
        "baseline": 1,
        "candidate": 1,
        "tie": 0,
        "count": 2,
    }
    disagreement = aggregate["ab_ba_disagreement"]["style_behavior"]
    assert disagreement["compared_pairs"] == 1
    assert disagreement["disagreements"] == 1
    assert "ready_for_approval" not in aggregate
    assert "human_approval" not in aggregate


def test_aggregate_rejects_invalid_rows_instead_of_averaging(loop_modules):
    evals, _, _ = loop_modules
    with pytest.raises(ValueError, match="invalid external score"):
        evals.aggregate_scores([{"status": "invalid"}])
