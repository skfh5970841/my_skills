#!/usr/bin/env python3
"""
sync_core.py — 채사장 계열 코어 동기화

마스터 chaesajang-core/의 단일 원본을 4개 스킬에 배포한다.
1) 코어 파일을 각 스킬의 references/에 복사 (매니페스트 기준)
2) gaze_core.md의 마커 블록을 각 SKILL.md의 CORE:gaze 마커 사이에 주입
3) 결과 리포트 출력. 마커 누락·원본 누락 시 즉시 실패.

사용법:
  python3 sync_core.py [--root 작업루트] [--check]
  --check : 파일을 쓰지 않고 드리프트(사본이 마스터와 다른지)만 검사

전제 폴더 구조 (--root 기준):
  chaesajang-core/            # 마스터 (이것만 수정한다)
    persona_core.md
    gaze_core.md
    anti_patterns_core.md
    reference_core.md
    template_core.md
    transformation_core.md
    anti_patterns_youtube.md
    reference_youtube.md
    template_youtube.md
    transformation_youtube.md
  chaesajang-style/SKILL.md
  chaesajang-advisor/SKILL.md
  chaesajang-dialogue/SKILL.md
  chaesajang-style-youtube-scripter/SKILL.md


"""

import argparse
import re
import shutil
import sys
from pathlib import Path

CORE_DIR = "chaesajang-core"

CORES_ALL = [
    "persona_core.md",
    "handoff_core.md",
    "anti_patterns_core.md",
    "reference_core.md",
    "template_core.md",
    "transformation_core.md",
]
DELTAS_YOUTUBE = [
    "anti_patterns_youtube.md",
    "reference_youtube.md",
    "template_youtube.md",
    "transformation_youtube.md",
]

# 스킬별 배포 매니페스트: (받는 코어 목록, gaze 마커 주입 여부)
MANIFEST = {
    "chaesajang-style":                  (CORES_ALL, True),
    "chaesajang-advisor":                (CORES_ALL, False),
    "chaesajang-dialogue":               (["persona_core.md", "handoff_core.md"], False),
    "chaesajang-style-youtube-scripter": (CORES_ALL + DELTAS_YOUTUBE, True),
}

MARKER_RE = re.compile(
    r"<!-- CORE:gaze BEGIN -->.*?<!-- CORE:gaze END -->", re.S
)


def fail(msg: str):
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def load_gaze_block(core: Path) -> str:
    text = (core / "gaze_core.md").read_text(encoding="utf-8")
    m = MARKER_RE.search(text)
    if not m:
        fail("gaze_core.md에서 CORE:gaze 마커 블록을 찾지 못했다.")
    return m.group(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="스킬들과 chaesajang-core가 있는 루트")
    ap.add_argument("--check", action="store_true", help="쓰기 없이 드리프트만 검사")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    core = root / CORE_DIR
    if not core.is_dir():
        fail(f"마스터 폴더가 없다: {core}")

    for f in CORES_ALL + DELTAS_YOUTUBE + ["gaze_core.md"]:
        if not (core / f).exists():
            fail(f"마스터에 원본이 없다: {f}")

    gaze_block = load_gaze_block(core)
    drift = []

    for skill, (files, inject) in MANIFEST.items():
        sdir = root / skill
        if not sdir.is_dir():
            fail(f"스킬 폴더가 없다: {sdir}")
        refs = sdir / "references"

        # 1) 코어/델타 사본 배포
        for f in files:
            src, dst = core / f, refs / f
            if args.check:
                if not dst.exists():
                    drift.append(f"{skill}: {f} 사본 없음")
                elif dst.read_bytes() != src.read_bytes():
                    drift.append(f"{skill}: {f} 마스터와 다름")
            else:
                refs.mkdir(exist_ok=True)
                shutil.copy2(src, dst)
                print(f"[copy] {skill}/references/{f}")

        # 2) gaze 마커 주입
        if inject:
            skill_md = sdir / "SKILL.md"
            text = skill_md.read_text(encoding="utf-8")
            if not MARKER_RE.search(text):
                fail(f"{skill}/SKILL.md에 CORE:gaze 마커가 없다. "
                     f"마커 없는 SKILL.md에 주입하면 본문이 파괴될 수 있어 중단한다.")
            new = MARKER_RE.sub(lambda _: gaze_block, text)
            if args.check:
                if new != text:
                    drift.append(f"{skill}: SKILL.md gaze 블록이 마스터와 다름")
            elif new != text:
                skill_md.write_text(new, encoding="utf-8")
                print(f"[inject] {skill}/SKILL.md ← gaze_core")
            else:
                print(f"[ok] {skill}/SKILL.md gaze 최신 상태")

    if args.check:
        if drift:
            print("드리프트 감지:")
            for d in drift:
                print(" -", d)
            sys.exit(2)
        print("드리프트 없음. 전 스킬이 마스터와 동기화 상태다.")
    else:
        print("\n동기화 완료. 설치는 각 스킬 폴더를 skills 디렉터리로 복사하면 된다.")


if __name__ == "__main__":
    main()
