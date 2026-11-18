"""위키 점검.

사용법:
    python3 scripts/lint.py

오류(종료 코드 1):
  - 깨진 [[링크]]
  - 필수 frontmatter(type) 누락
  - AUTO 블록이 raw/data 와 불일치 (build.py --check)
경고(종료 코드 0):
  - 고아 페이지(들어오는 링크 없음)
  - 서술 미작성 자리표시 남음
  - 서술 영역의 숫자가 원본 데이터·AUTO 표 어디에도 없음 (환각 의심)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict

from build import AUTO_RE, PLACEHOLDER, split_page
from common import RAW_DATA, ROOT, WIKI

LINK_RE = re.compile(r"\[\[([^\]|#\\]+)(?:#[^\]|\\]*)?(?:\\?\|[^\]]*)?\]\]")
CODE_RE = re.compile(r"```.*?```", re.S)
ANY_NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)")
NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?=\s*(?:만원|건|%|명))")
EXEMPT_ORPHAN = {"index", "log"}


def numbers_in(text: str) -> set[str]:
    return {m.group(1).replace(",", "") for m in NUM_RE.finditer(text)}


def json_numbers() -> set[str]:
    out = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            out.add(f"{v:g}")
            out.add(str(round(v)))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for p in RAW_DATA.glob("*.json"):
        walk(json.loads(p.read_text(encoding="utf-8")))
    return out


def main() -> int:
    errors, warns = [], []
    pages = {p.stem: p for p in WIKI.rglob("*.md")}
    inbound = defaultdict(set)
    texts = {}
    for stem, p in pages.items():
        text = p.read_text(encoding="utf-8")
        fm, body = split_page(text)
        texts[stem] = (fm, body)
        if not fm.get("type"):
            errors.append(f"frontmatter type 누락: {p.relative_to(ROOT)}")
        for target in LINK_RE.findall(CODE_RE.sub("", body)):
            target = target.strip()
            name = target.split("/")[-1].removesuffix(".md")
            if name not in pages:
                errors.append(f"깨진 링크 [[{target}]] in {p.relative_to(ROOT)}")
            elif name != stem:
                inbound[name].add(stem)

    for stem, p in pages.items():
        fm, body = texts[stem]
        if fm.get("type") != "data" and stem not in EXEMPT_ORPHAN and not inbound[stem]:
            warns.append(f"고아 페이지: {p.relative_to(ROOT)}")
        if PLACEHOLDER in body:
            warns.append(f"서술 미작성: {p.relative_to(ROOT)}")

    # 서술 영역 숫자 검증
    known = json_numbers()
    for stem, (fm, body) in texts.items():
        for m in AUTO_RE.finditer(body):
            known |= {x.replace(",", "") for x in ANY_NUM_RE.findall(m.group(2))}
    for stem, (fm, body) in texts.items():
        if fm.get("type") in ("data", "concept"):
            continue
        prose = CODE_RE.sub("", AUTO_RE.sub("", body))
        unknown = sorted(n for n in numbers_in(prose) if n not in known)
        if unknown:
            warns.append(f"출처 불명 숫자 {unknown}: {pages[stem].relative_to(ROOT)}")

    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py"), "--check"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        errors.append("AUTO 블록이 데이터와 불일치 → python3 scripts/build.py 실행 필요\n" + r.stdout)

    for w in warns:
        print(f"[경고] {w}")
    for e in errors:
        print(f"[오류] {e}")
    print(f"점검 완료: 페이지 {len(pages)}개, 오류 {len(errors)}건, 경고 {len(warns)}건")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
