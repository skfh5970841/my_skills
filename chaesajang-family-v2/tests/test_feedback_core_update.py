import hashlib
import importlib.util
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "chaesajang-core"
SCRIPTS = ROOT / "chaesajang-family-optimizer" / "scripts"
LEGACY_RUNNER = ROOT.parent / "origin" / "analysis" / "trigger_eval" / "run_trigger_eval.py"


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class FeedbackCoreUpdateTests(unittest.TestCase):
    def test_golden_feedback_records_preserve_hashes_and_manual_provenance(self):
        sys.path.insert(0, str(SCRIPTS))
        try:
            from optimizer_loop.evals import load_cases

            expected = {
                "FB-001": (
                    "b0ee737e7c60c2ed04ecebdedbfdb9d61a4a5571a837d3ac8af00dee78fde14c",
                    "chaesajang-family-v2/feedback/completed/FB-001_좋은_문장_뒤_과잉_해설.md",
                    "excerpt_only",
                    "6f0f486af4a33a3416b2da7b676df79a0c9ce6c5c457d6c583bae2c1743f0a32",
                ),
                "FB-002": (
                    "6104c7ad35606311b463779666be01ed1b06f5ddbabcb0e1885895512b830111",
                    "chaesajang-family-v2/feedback/completed/FB-002_SNS_비교_글_종합_리뷰.md",
                    "mutated_snapshot",
                    "618c6aecc912cc78ef34d9a446676a93c180f5af725d3b6b78724334f6a962d8",
                ),
                "FB-003": (
                    "a44520655f0698bdfc36dc3399b0b0891020966614afd8074c47b6ce4a9b8e15",
                    "chaesajang-family-v2/feedback/completed/FB-003_죽음과_유한성_글_종합_리뷰.md",
                    "documented_snapshot",
                    "e828e5d031859818a3ea62886af28f408e44667523d65a305c177623382ae9c8",
                ),
            }
            cases = []
            for case_id in expected:
                path = ROOT / "evals" / "golden" / f"{case_id.lower().replace('-', '_')}.jsonl"
                loaded = load_cases(path, "golden")
                self.assertEqual(len(loaded), 1)
                cases.extend(loaded)

            for case in cases:
                before_hash, relative, mode, source_hash = expected[case.case_id]
                self.assertEqual(case.target_skill, "chaesajang-style")
                self.assertEqual(case.source_group, "feedback/fb-001-003-ap11")
                self.assertEqual(case.before_hash, before_hash)
                self.assertEqual(case.provenance["path"], relative)
                self.assertEqual(case.provenance["mode"], mode)
                self.assertEqual(case.provenance["source_sha256"], source_hash)
                self.assertIn("manual", case.provenance["note"])
                self.assertIn("not_scored", case.provenance["note"])
                normalized = (ROOT.parent / relative).read_text(encoding="utf-8").replace("\r\n", "\n")
                self.assertEqual(
                    hashlib.sha256(normalized.encode("utf-8")).hexdigest(), source_hash
                )
                self.assertEqual(dict(case.deterministic_checks), {"output_present": True})
                with self.assertRaises(TypeError):
                    case.provenance["path"] = "changed"
        finally:
            sys.modules.pop("optimizer_loop.evals", None)
            sys.modules.pop("optimizer_loop", None)
            sys.path.remove(str(SCRIPTS))

    def test_legacy_trigger_runner_blocks_all_external_failures_and_returns_nonzero(self):
        spec = importlib.util.spec_from_file_location("legacy_trigger_runner", LEGACY_RUNNER)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        negative = {"id": 1, "query": "plain request", "should_trigger": False}

        failures = (
            lambda _query: (_ for _ in ()).throw(RuntimeError("boom")),
            lambda _query: (_ for _ in ()).throw(FileNotFoundError("claude missing")),
            lambda _query: (_ for _ in ()).throw(
                subprocess.TimeoutExpired(cmd=("claude",), timeout=1)
            ),
            lambda _query: subprocess.CompletedProcess(("claude",), 0, "{bad", ""),
        )
        for failing_invoke in failures:
            with self.subTest(failure=failing_invoke):
                module.invoke = failing_invoke
                result = module.evaluate_case(negative, runs=1, target="chaesajang-style")
                self.assertEqual(result["status"], "blocked_external")
                self.assertIs(result["passed"], False)

        responses = iter(
            (
                subprocess.CompletedProcess(("claude",), 0, '{"result": "no tools"}', ""),
                RuntimeError("second repeat failed"),
            )
        )

        def incomplete(_query):
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        module.invoke = incomplete
        incomplete_result = module.evaluate_case(
            negative, runs=2, target="chaesajang-style"
        )
        self.assertEqual(incomplete_result["status"], "blocked_external")
        self.assertIs(incomplete_result["passed"], False)
        self.assertEqual(incomplete_result["completed_runs"], 1)

        module.QUERIES = [negative]
        module.invoke = lambda _query: (_ for _ in ()).throw(RuntimeError("boom"))
        self.assertEqual(module.main(["1", "chaesajang-style"]), 1)

    def test_feedback_provenance_rejects_unpaired_or_unsafe_metadata(self):
        sys.path.insert(0, str(SCRIPTS))
        try:
            from optimizer_loop.evals import EvalCase

            base = {
                "case_id": "provenance-test",
                "target_skill": "chaesajang-style",
                "source_group": "feedback/test",
                "generator_brief": "원문 요청 미보존",
                "axes": ["request_fulfillment"],
                "risk": "behavior",
                "deterministic_checks": {"output_present": True},
                "before_hash": "a" * 64,
            }
            with self.assertRaisesRegex(ValueError, "supplied together"):
                EvalCase.from_dict(base, "golden")

            unsafe = {
                **base,
                "provenance": {
                    "path": "C:/outside.md",
                    "mode": "excerpt_only",
                    "source_sha256": "b" * 64,
                    "note": "manual and not_scored",
                },
            }
            with self.assertRaisesRegex(ValueError, "relative POSIX"):
                EvalCase.from_dict(unsafe, "golden")
        finally:
            sys.modules.pop("optimizer_loop.evals", None)
            sys.modules.pop("optimizer_loop", None)
            sys.path.remove(str(SCRIPTS))

    def test_ap11_distinguishes_functional_repetition_from_duplication(self):
        text = read("chaesajang-core/anti_patterns_core.md")

        self.assertIn("## AP-11:", text)
        self.assertRegex(text, r"기능적 반복.*새로운 (?:사례|근거|단계)")
        self.assertRegex(text, r"의미 중복.*새로운 정보")
        self.assertIn("P-RHYTHM-B", text)

    def test_reference_makes_summary_and_recall_conditional(self):
        text = read("chaesajang-core/reference_core.md")

        self.assertIn("### 결론부 절제 — 설명보다 회수", text)
        self.assertRegex(text, r"에세이|칼럼")
        self.assertRegex(text, r"설명형|교양서|책 챕터")
        self.assertIn("정리·공식형", text)

    def test_connection_and_scope_guidance_are_narrow_not_universal(self):
        template = read("chaesajang-core/template_core.md")
        reference = read("chaesajang-core/reference_core.md")

        self.assertRegex(template, r"중간 전제.*복원")
        self.assertRegex(template, r"복원할 수 있다면.*덧붙이지")
        self.assertIn("### 논증의 범위와 깊이", reference)
        self.assertRegex(reference, r"주어.*빈도.*범위")

    def test_gaze_guidance_is_added_only_to_the_distributed_block(self):
        text = read("chaesajang-core/gaze_core.md")
        gaze = re.search(
            r"<!-- CORE:gaze BEGIN -->(.*?)<!-- CORE:gaze END -->", text, re.S
        )
        method = re.search(
            r"<!-- CORE:method BEGIN -->(.*?)<!-- CORE:method END -->", text, re.S
        )

        self.assertIsNotNone(gaze)
        self.assertIsNotNone(method)
        self.assertIn("독자를 믿고 멈춘다", gaze.group(1))
        self.assertNotIn("독자를 믿고 멈춘다", method.group(1))

    def test_skill_self_checks_have_no_stale_hard_coded_count(self):
        text = read("chaesajang-style/SKILL.md")

        self.assertNotIn("여섯 점검", text)
        self.assertIn("**7. 같은 의미가 반복되지 않았는가.**", text)
        self.assertIn("**8. 논증의 연결과 범위가 정확한가.**", text)


if __name__ == "__main__":
    unittest.main()
