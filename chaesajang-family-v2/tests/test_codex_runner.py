import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture
def loop_modules():
    scripts = Path(__file__).resolve().parents[1] / "chaesajang-family-optimizer" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from optimizer_loop import generate, runner

        yield generate, runner
    finally:
        sys.path.remove(str(scripts))


def run_config(runner, tmp_path, command, *, expect_json=False, stdin_text=""):
    return runner.RunConfig(
        command=tuple(command),
        cwd=tmp_path,
        timeout_seconds=5,
        stdin_text=stdin_text,
        model="fake-model",
        reasoning="high",
        runtime="codex",
        expect_json=expect_json,
    )


def generation_config(
    runner,
    source_root,
    *,
    model="fake-model",
    reasoning="high",
    runtime="codex",
    timeout_seconds=5,
    expect_json=False,
):
    root = Path(source_root).resolve(strict=True)
    command = (
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--model",
        model,
        "--config",
        f'model_reasoning_effort="{reasoning}"',
        "--cd",
        str(root),
        "-",
    )
    return runner.RunConfig(
        command=command,
        cwd=root,
        timeout_seconds=timeout_seconds,
        stdin_text="must be replaced",
        model=model,
        reasoning=reasoning,
        runtime=runtime,
        expect_json=expect_json,
    )


def make_skill(root: Path, name: str = "alpha") -> Path:
    skill = root / name
    references = skill / "references"
    references.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing.\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    (references / "guide.md").write_text("guide\n", encoding="utf-8")
    return skill


def eval_case(case_id="case-1", target_skill="alpha", **overrides):
    value = {
        "case_id": case_id,
        "target_skill": target_skill,
        "source_group": "fixture/source",
        "generator_brief": "Explain the topic in plain Korean.",
        "axes": ["style_behavior"],
        "risk": "behavior",
        "deterministic_checks": {"required_terms": ["결론"]},
        "evaluator_reference": "EVALUATOR-ONLY-SECRET",
        "evaluator_checklist": ["CHECKLIST-ONLY-SECRET"],
        "holdout_content": "HOLDOUT-ONLY-SECRET",
    }
    value.update(overrides)
    return value


def test_nonzero_and_empty_output_are_not_passes(tmp_path, loop_modules):
    _, runner = loop_modules
    failed = runner.run_command(
        run_config(
            runner,
            tmp_path,
            (
                sys.executable,
                "-c",
                "import sys; print('partial'); print('problem', file=sys.stderr); raise SystemExit(3)",
            ),
        )
    )
    empty = runner.run_command(
        run_config(runner, tmp_path, (sys.executable, "-c", "print('   ')"))
    )

    assert failed.status == "blocked_external"
    assert failed.returncode == 3
    assert failed.stdout == "partial\n"
    assert failed.stderr == "problem\n"
    assert empty.status == "blocked_external"
    assert empty.returncode == 0
    assert empty.stdout == "   \n"


def test_plain_text_success_is_completed_without_json_parsing(tmp_path, loop_modules):
    _, runner = loop_modules
    result = runner.run_command(
        run_config(runner, tmp_path, (sys.executable, "-c", "print('not json')"))
    )

    assert result.status == "completed"
    assert result.returncode == 0
    assert result.stdout == "not json\n"
    assert result.stderr == ""
    assert result.elapsed_ms >= 0


def test_json_mode_blocks_malformed_json_but_preserves_raw_streams(tmp_path, loop_modules):
    _, runner = loop_modules
    malformed = runner.run_command(
        run_config(
            runner,
            tmp_path,
            (sys.executable, "-c", "import sys; print('{bad'); print('note', file=sys.stderr)"),
            expect_json=True,
        )
    )
    valid = runner.run_command(
        run_config(
            runner,
            tmp_path,
            (sys.executable, "-c", "import json; print(json.dumps({'ok': True}))"),
            expect_json=True,
        )
    )

    assert malformed.status == "blocked_external"
    assert malformed.returncode == 0
    assert malformed.stdout == "{bad\n"
    assert malformed.stderr == "note\n"
    assert valid.status == "completed"
    assert json.loads(valid.stdout) == {"ok": True}


def test_run_command_uses_argv_without_a_shell_and_monotonic_elapsed(
    tmp_path, loop_modules, monkeypatch
):
    _, runner = loop_modules
    seen = {}

    def fake_subprocess_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, "literal output", "")

    ticks = iter((10.0, 10.1234))
    monkeypatch.setattr(runner.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(ticks))
    config = run_config(
        runner,
        tmp_path,
        ("fake-command", "$(touch should-not-exist)", "& echo expanded"),
        stdin_text="raw stdin",
    )

    result = runner.run_command(config)

    assert seen["command"] == config.command
    assert seen["kwargs"] == {
        "cwd": config.cwd,
        "input": "raw stdin",
        "text": True,
        "capture_output": True,
        "timeout": 5,
        "shell": False,
        "encoding": "utf-8",
        "errors": "replace",
    }
    assert result.status == "completed"
    assert result.elapsed_ms == 123
    assert not (tmp_path / "should-not-exist").exists()


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("missing executable"), OSError("launch failed")],
)
def test_launch_errors_are_blocked_external(tmp_path, loop_modules, monkeypatch, error):
    _, runner = loop_modules

    def fail_launch(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(runner.subprocess, "run", fail_launch)
    result = runner.run_command(run_config(runner, tmp_path, ("missing-command",)))

    assert result.status == "blocked_external"
    assert result.returncode is None
    assert result.stdout == ""
    assert str(error) in result.stderr


def test_timeout_is_blocked_and_preserves_available_streams(
    tmp_path, loop_modules, monkeypatch
):
    _, runner = loop_modules

    def time_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=("slow",), timeout=5, output=b"partial stdout", stderr=b"partial stderr"
        )

    monkeypatch.setattr(runner.subprocess, "run", time_out)
    result = runner.run_command(run_config(runner, tmp_path, ("slow",)))

    assert result.status == "blocked_external"
    assert result.returncode is None
    assert result.stdout == "partial stdout"
    assert result.stderr == "partial stderr"


def test_generation_prompt_uses_only_generator_facing_case_data(tmp_path, loop_modules):
    generate, _ = loop_modules
    make_skill(tmp_path)
    case = eval_case()

    prompt = generate.build_generation_prompt(case, Path("alpha") / "SKILL.md")

    assert case["case_id"] in prompt
    assert case["target_skill"] in prompt
    assert case["generator_brief"] in prompt
    assert "alpha/SKILL.md" in prompt
    assert "alpha\\SKILL.md" not in prompt
    assert "only the local references that SKILL.md requires" in prompt
    assert "Do not make any file changes" in prompt
    assert "Return only the requested response" in prompt
    assert case["evaluator_reference"] not in prompt
    assert case["evaluator_checklist"][0] not in prompt
    assert case["holdout_content"] not in prompt
    assert case["axes"][0] not in prompt


def test_baseline_and_candidate_use_identical_logical_prompt_bytes(
    tmp_path, loop_modules, monkeypatch
):
    generate, runner = loop_modules
    baseline_root = tmp_path / "baseline-source"
    candidate_root = tmp_path / "candidate-source"
    make_skill(baseline_root)
    make_skill(candidate_root)
    received = []

    def fake_run(config):
        received.append(config)
        return runner.RunResult("completed", 0, "answer", "", 1)

    monkeypatch.setattr(generate, "run_command", fake_run)
    baseline = generate.generate_cases(
        [eval_case()],
        baseline_root,
        generation_config(runner, baseline_root),
        repeats=1,
    )[0]
    candidate = generate.generate_cases(
        [eval_case()],
        candidate_root,
        generation_config(runner, candidate_root),
        repeats=1,
    )[0]

    assert baseline["prompt"].encode("utf-8") == candidate["prompt"].encode("utf-8")
    assert received[0].stdin_text.encode("utf-8") == received[1].stdin_text.encode("utf-8")
    assert baseline["prompt"] == received[0].stdin_text
    assert candidate["prompt"] == received[1].stdin_text
    assert "alpha/SKILL.md" in baseline["prompt"]
    assert str(baseline_root.resolve()) not in baseline["prompt"]
    assert str(candidate_root.resolve()) not in candidate["prompt"]
    assert "candidate" not in candidate["prompt"].casefold()


def test_generation_records_order_repeats_settings_and_provenance(
    tmp_path, loop_modules, monkeypatch
):
    generate, runner = loop_modules
    make_skill(tmp_path, "alpha")
    make_skill(tmp_path, "beta")
    cases = (eval_case("b", "beta"), eval_case("a", "alpha"))
    config = generation_config(runner, tmp_path)
    received = []

    def fake_run(per_case_config):
        received.append(per_case_config)
        return runner.RunResult("completed", 0, f"answer-{len(received)}", "raw warning", 17)

    monkeypatch.setattr(generate, "run_command", fake_run)
    rows = generate.generate_cases(cases, tmp_path, config, repeats=2)

    assert [(row["case_id"], row["repeat"]) for row in rows] == [
        ("b", 0),
        ("b", 1),
        ("a", 0),
        ("a", 1),
    ]
    assert all(row["model"] == config.model for row in rows)
    assert all(row["reasoning"] == config.reasoning for row in rows)
    assert all(row["runtime"] == config.runtime for row in rows)
    assert all(row["command"] == list(config.command) for row in rows)
    assert all(row["cwd"] == str(tmp_path.resolve()) for row in rows)
    assert all(row["source_root"] == str(tmp_path.resolve()) for row in rows)
    assert all(row["timeout_seconds"] == config.timeout_seconds for row in rows)
    assert [row["output"] for row in rows] == ["answer-1", "answer-2", "answer-3", "answer-4"]
    assert all(row["stderr"] == "raw warning" for row in rows)
    assert all(row["elapsed_ms"] == 17 for row in rows)
    assert all(row["status"] == "completed" for row in rows)
    assert all(row["returncode"] == 0 for row in rows)
    assert all(row["input"] == cases[0 if row["case_id"] == "b" else 1]["generator_brief"] for row in rows)
    assert all(row["prompt"] == call.stdin_text for row, call in zip(rows, received))
    assert all(call.command == config.command for call in received)
    assert all(call.cwd == config.cwd for call in received)
    assert all(call.model == config.model for call in received)
    assert all(call.reasoning == config.reasoning for call in received)
    assert all(call.runtime == config.runtime for call in received)
    assert all(call.expect_json is False for call in received)
    assert rows[0]["source_snapshot"] == rows[1]["source_snapshot"] == {
        "SKILL.md": rows[0]["source_snapshot"]["SKILL.md"],
        "references/guide.md": rows[0]["source_snapshot"]["references/guide.md"],
    }
    assert rows[2]["source_snapshot"] == rows[3]["source_snapshot"]
    assert all(row["source_snapshot_after"] == row["source_snapshot"] for row in rows)
    assert all(row["source_stable"] is True for row in rows)
    assert all("invalid_reason" not in row for row in rows)
    for row in rows:
        timestamp = datetime.fromisoformat(row["started_at"])
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset() is not None
        serialized = json.dumps(row, ensure_ascii=False, allow_nan=False)
        assert "EVALUATOR-ONLY-SECRET" not in serialized
        assert "CHECKLIST-ONLY-SECRET" not in serialized
        assert "HOLDOUT-ONLY-SECRET" not in serialized


def test_source_snapshot_changes_with_any_regular_skill_file(
    tmp_path, loop_modules, monkeypatch
):
    generate, runner = loop_modules
    skill = make_skill(tmp_path)
    config = generation_config(runner, tmp_path)
    monkeypatch.setattr(
        generate,
        "run_command",
        lambda _config: runner.RunResult("completed", 0, "answer", "", 1),
    )

    before = generate.generate_cases([eval_case()], tmp_path, config, repeats=1)[0]
    (skill / "references" / "guide.md").write_text("changed\n", encoding="utf-8")
    (skill / "extra.txt").write_text("new regular file\n", encoding="utf-8")
    after = generate.generate_cases([eval_case()], tmp_path, config, repeats=1)[0]

    assert before["source_snapshot"]["references/guide.md"] != after["source_snapshot"][
        "references/guide.md"
    ]
    assert "extra.txt" not in before["source_snapshot"]
    assert "extra.txt" in after["source_snapshot"]
    assert list(after["source_snapshot"]) == sorted(after["source_snapshot"])


def test_generation_binds_cwd_command_and_plain_text_mode_before_running(
    tmp_path, loop_modules, monkeypatch
):
    generate, runner = loop_modules
    make_skill(tmp_path)
    other_root = tmp_path / "other-root"
    other_root.mkdir()
    valid = generation_config(runner, tmp_path)
    invalid_configs = (
        replace(valid, cwd=other_root),
        replace(valid, command=("codex", "exec", "-")),
        replace(valid, command=("claude", *valid.command[1:])),
        replace(valid, expect_json=True),
    )
    monkeypatch.setattr(
        generate,
        "run_command",
        lambda _config: pytest.fail("invalid generation config must not execute"),
    )

    for config in invalid_configs:
        with pytest.raises(ValueError):
            generate.generate_cases([eval_case()], tmp_path, config, repeats=1)


def test_generation_rejects_non_codex_runtime_before_running(
    tmp_path, loop_modules, monkeypatch
):
    generate, runner = loop_modules
    make_skill(tmp_path)
    config = generation_config(runner, tmp_path, runtime="claude")
    monkeypatch.setattr(
        generate,
        "run_command",
        lambda _config: pytest.fail("non-Codex generation must fail before execution"),
    )

    with pytest.raises(ValueError, match="runtime.*codex"):
        generate.generate_cases([eval_case()], tmp_path, config, repeats=1)


def test_generation_marks_source_mutation_invalid_and_stops_repeats(
    tmp_path, loop_modules, monkeypatch
):
    generate, runner = loop_modules
    skill = make_skill(tmp_path)
    calls = []

    def mutate_during_run(config):
        calls.append(config)
        (skill / "references" / "guide.md").write_text(
            "mutated during generation\n", encoding="utf-8"
        )
        return runner.RunResult("completed", 0, "raw generated answer", "warning", 9)

    monkeypatch.setattr(generate, "run_command", mutate_during_run)
    rows = generate.generate_cases(
        [eval_case()], tmp_path, generation_config(runner, tmp_path), repeats=3
    )

    assert len(calls) == len(rows) == 1
    row = rows[0]
    assert row["output"] == "raw generated answer"
    assert row["stderr"] == "warning"
    assert row["returncode"] == 0
    assert row["status"] == "invalid"
    assert row["source_stable"] is False
    assert row["source_snapshot"] != row["source_snapshot_after"]
    assert "changed during generation" in row["invalid_reason"]


def test_generation_marks_post_run_snapshot_failure_invalid(
    tmp_path, loop_modules, monkeypatch
):
    generate, runner = loop_modules
    make_skill(tmp_path)
    command_finished = False
    original_snapshot = generate._skill_snapshot

    def snapshot(skill):
        if command_finished:
            raise ValueError("injected post-read failure")
        return original_snapshot(skill)

    def fake_run(_config):
        nonlocal command_finished
        command_finished = True
        return runner.RunResult("completed", 0, "preserved output", "", 4)

    monkeypatch.setattr(generate, "_skill_snapshot", snapshot)
    monkeypatch.setattr(generate, "run_command", fake_run)
    rows = generate.generate_cases(
        [eval_case()], tmp_path, generation_config(runner, tmp_path), repeats=2
    )

    assert len(rows) == 1
    assert rows[0]["output"] == "preserved output"
    assert rows[0]["status"] == "invalid"
    assert rows[0]["source_snapshot_after"] is None
    assert rows[0]["source_stable"] is False
    assert "post-run source snapshot failed" in rows[0]["invalid_reason"]
    assert "injected post-read failure" in rows[0]["invalid_reason"]


def test_generation_normalizes_pre_run_file_read_errors(
    tmp_path, loop_modules, monkeypatch
):
    generate, runner = loop_modules
    make_skill(tmp_path)
    original_read_bytes = Path.read_bytes

    def fail_guide(self):
        if self.name == "guide.md":
            raise OSError("injected source read failure")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fail_guide)
    monkeypatch.setattr(
        generate,
        "run_command",
        lambda _config: pytest.fail("pre-run source read failure must not execute"),
    )

    with pytest.raises(ValueError, match="inaccessible"):
        generate.generate_cases(
            [eval_case()], tmp_path, generation_config(runner, tmp_path), repeats=1
        )


def test_generation_rejects_incomplete_snapshot_when_directory_walk_fails(
    tmp_path, loop_modules, monkeypatch
):
    generate, runner = loop_modules
    make_skill(tmp_path)
    monkeypatch.setattr(
        generate,
        "run_command",
        lambda _config: pytest.fail("incomplete snapshot must fail before execution"),
    )

    def inaccessible_walk(*_args, **kwargs):
        onerror = kwargs.get("onerror")
        if onerror is not None:
            onerror(PermissionError("injected directory denial"))
        return iter(())

    monkeypatch.setattr(generate.os, "walk", inaccessible_walk)
    with pytest.raises(ValueError, match="inaccessible"):
        generate.generate_cases(
            [eval_case()],
            tmp_path,
            generation_config(runner, tmp_path),
            repeats=1,
        )


@pytest.mark.parametrize("repeats", [0, -1, True, 1.5, "2"])
def test_generation_rejects_invalid_repeats_before_running(
    tmp_path, loop_modules, monkeypatch, repeats
):
    generate, runner = loop_modules
    make_skill(tmp_path)
    monkeypatch.setattr(
        generate,
        "run_command",
        lambda _config: pytest.fail("invalid repeats must fail before execution"),
    )

    with pytest.raises((TypeError, ValueError), match="repeats"):
        generate.generate_cases(
            [eval_case()],
            tmp_path,
            generation_config(runner, tmp_path),
            repeats=repeats,
        )


@pytest.mark.parametrize(
    "cases, message",
    [
        (["not-a-mapping"], "case"),
        ([eval_case(generator_brief="")], "generator_brief"),
        ([eval_case(case_id="")], "case_id"),
        ([eval_case(target_skill="")], "target_skill"),
        ([eval_case(), eval_case()], "duplicate case_id"),
    ],
)
def test_generation_rejects_malformed_or_repeated_cases_before_running(
    tmp_path, loop_modules, monkeypatch, cases, message
):
    generate, runner = loop_modules
    make_skill(tmp_path)
    monkeypatch.setattr(
        generate,
        "run_command",
        lambda _config: pytest.fail("malformed cases must fail before execution"),
    )

    with pytest.raises((TypeError, ValueError), match=message):
        generate.generate_cases(
            cases,
            tmp_path,
            generation_config(runner, tmp_path),
            repeats=1,
        )


@pytest.mark.parametrize(
    "target_skill",
    ["../outside", "alpha/../alpha", "alpha/child", "alpha\\child", "C:/alpha"],
)
def test_generation_rejects_target_path_traversal(
    tmp_path, loop_modules, monkeypatch, target_skill
):
    generate, runner = loop_modules
    make_skill(tmp_path)
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "SKILL.md").write_text("outside\n", encoding="utf-8")
    monkeypatch.setattr(
        generate,
        "run_command",
        lambda _config: pytest.fail("unsafe source must fail before execution"),
    )

    with pytest.raises(ValueError, match="target_skill"):
        generate.generate_cases(
            [eval_case(target_skill=target_skill)],
            tmp_path,
            generation_config(runner, tmp_path),
            repeats=1,
        )


def test_generation_rejects_source_symlinks(tmp_path, loop_modules, monkeypatch):
    generate, runner = loop_modules
    skill = make_skill(tmp_path)
    link = skill / "references" / "linked.md"
    try:
        os.symlink(skill / "SKILL.md", link)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")
    monkeypatch.setattr(
        generate,
        "run_command",
        lambda _config: pytest.fail("symlink source must fail before execution"),
    )

    with pytest.raises(ValueError, match="symlink"):
        generate.generate_cases(
            [eval_case()],
            tmp_path,
            generation_config(runner, tmp_path),
            repeats=1,
        )
