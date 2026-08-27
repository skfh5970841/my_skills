import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "chaesajang-core"


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class FeedbackCoreUpdateTests(unittest.TestCase):
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
