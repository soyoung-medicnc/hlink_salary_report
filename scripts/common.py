"""공통 유틸: 경로, 레지스트리, 기간 파싱."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW_HTML = ROOT / "raw" / "dashboards"
RAW_DATA = ROOT / "raw" / "data"
WIKI = ROOT / "wiki"
REGISTRY_PATH = ROOT / "scripts" / "registry.yaml"

LOW_N = 10  # 이 값 미만의 표본은 '표본 부족'으로 표시


class RegistryError(Exception):
    pass


def load_registry() -> dict:
    reg = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    reg["specialty_names"] = {v: k for k, v in reg["specialties"].items()}
    reg["region_names"] = {v: k for k, v in reg["regions"].items()}
    reg["hospital_type_names"] = {v: k for k, v in reg["hospital_types"].items()}
    return reg


def slug_of(reg: dict, kind: str, name: str) -> str:
    table = reg[kind]
    if name not in table:
        raise RegistryError(
            f"레지스트리에 없는 {kind} 명칭: '{name}' → scripts/registry.yaml 에 추가하세요."
        )
    return table[name]


PERIOD_RE = re.compile(r"^(\d{4})\.(\d{2})~(\d{2})$")


def parse_period(label: str) -> dict:
    """'2026.01~03' → {label, year, start_month, end_month, slug}"""
    m = PERIOD_RE.match(label)
    if not m:
        raise ValueError(f"알 수 없는 기간 형식: {label}")
    year, s, e = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if s % 3 == 1 and e == s + 2:
        slug = f"{year}q{(s + 2) // 3}"
    elif s == 1 and e == 6:
        slug = f"{year}h1"
    elif s == 7 and e == 12:
        slug = f"{year}h2"
    elif s == 1 and e == 12:
        slug = f"{year}"
    else:
        slug = f"{year}m{s:02d}-{e:02d}"
    return {
        "label": label,
        "label_ko": f"{year}년 {s}~{e}월",
        "year": year,
        "start_month": s,
        "end_month": e,
        "slug": slug,
    }


def load_reports() -> list[dict]:
    """raw/data/*.json 을 기간·진료과 순으로 로드."""
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RAW_DATA.glob("*.json"))]
    reports.sort(key=lambda r: (r["period"]["recent"]["slug"], r["specialty"]["slug"]))
    return reports
