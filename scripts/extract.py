"""대시보드 HTML → 정규화된 JSON (raw/data/<specialty>_<period>.json).

사용법:
    python3 scripts/extract.py                # raw/dashboards/*.html 전체
    python3 scripts/extract.py path/to.html   # 특정 파일만

숫자는 원본 JSON(window.DASHBOARD_DATA)에서 그대로 옮기며, 계산·반올림하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from common import RAW_DATA, RAW_HTML, ROOT, RegistryError, load_registry, parse_period, slug_of

SCHEMA_VERSION = 1
MARKER = "window.DASHBOARD_DATA = "
DEMAND_RE = re.compile(r"^(\S+?)(은|는)\s*(▲|▼|→)\s*([\d.]+)%$")
DIRECTION = {"▲": "up", "▼": "down", "→": "flat"}


def read_dashboard_json(html: str) -> dict:
    i = html.find(MARKER)
    if i < 0:
        raise ValueError("window.DASHBOARD_DATA 를 찾을 수 없습니다.")
    line = html[i + len(MARKER): html.index("\n", i)].strip()
    return json.loads(line.rstrip(";"))


def pick(d: dict, *keys):
    for k in keys:
        if k in d:
            return d[k]
    raise KeyError(keys)


def salary_rows(reg, data: dict, periods: dict, extra: dict) -> list[dict]:
    rows = []
    label_to_key = {periods[k]["label"]: k for k in ("recent", "prev")}
    for region, by_period in data.items():
        for label, v in by_period.items():
            if label not in label_to_key:
                raise ValueError(f"기간 라벨 불일치: {label}")
            rows.append({
                **extra,
                "region": region,
                "region_slug": slug_of(reg, "regions", region),
                "period": label_to_key[label],
                # 표본 0건인데 급여가 0으로 들어온 경우는 결측(null)으로 본다
                "salary": v["salary"] if v["n"] and v["salary"] else None,
                "n": v["n"],
            })
    return rows


def extract(path: Path, reg: dict) -> tuple[dict, list[str]]:
    html = path.read_text(encoding="utf-8")
    raw = read_dashboard_json(html)
    warnings: list[str] = []

    specialty = raw["params"]["title"]
    p = raw["periods"]
    periods = {
        "recent": parse_period(p["recent_label"]),
        "prev": parse_period(pick(p, "prev1_label", "prev_label")),
    }
    spec_slug = slug_of(reg, "specialties", specialty)
    report_id = f"{spec_slug}-{periods['recent']['slug']}"
    end_m, recent_year = periods["recent"]["end_month"], periods["recent"]["year"]

    # fig1: 월별 초빙수요
    demand_monthly = []
    for yd in raw["fig1"]["data"]:
        for m_label, val in zip(yd["months"], yd["values"]):
            month = int(m_label.rstrip("월"))
            if yd["year"] == recent_year and month > end_m:
                warnings.append(f"초빙수요 {yd['year']}-{month:02d} 값({val})은 분석 기간 밖이라 제외")
                continue
            demand_monthly.append({"year": yd["year"], "month": month, "count": val})

    # fig2: 지역별 병원규모 비중(%)
    f2 = raw["fig2"]
    demand_mix = []
    for key, shares in f2["data"].items():
        region, year = key.split("|")
        demand_mix.append({
            "region": region,
            "region_slug": slug_of(reg, "regions", region),
            "year": int(year),
            "shares": {slug_of(reg, "hospital_types", h): v for h, v in shares.items()},
        })
    demand_mix.sort(key=lambda r: (r["region_slug"], r["year"]))

    # fig3: 지역별 NET 평균 급여 (전체 병원)
    salary_by_region = salary_rows(reg, raw["fig3"]["data"], periods, {})

    # fig3_<group>[_clinic]: 권역 × 병원유형
    salary_by_group = []
    for gslug, g in reg["region_groups"].items():
        for suffix, htype in (("", "종합병원"), ("_clinic", "의원")):
            key = f"fig3_{g['fig_key']}{suffix}"
            if key not in raw:
                warnings.append(f"{key} 없음")
                continue
            salary_by_group += salary_rows(reg, raw[key]["data"], periods, {
                "group_slug": gslug,
                "hospital_type_slug": slug_of(reg, "hospital_types", htype),
            })

    # salary_summary 는 fig3_<group> 과 같아야 함 (검증만)
    for skey, hslug in (("salary_summary", "general-hospital"), ("salary_summary_clinic", "clinic")):
        if skey not in raw:
            warnings.append(f"{skey} 없음 (템플릿 구버전) → fig3_*{'_clinic' if hslug == 'clinic' else ''} 값으로 대체")
            continue
        for row in salary_rows(reg, raw[skey], periods, {}):
            match = [r for r in salary_by_group
                     if r["hospital_type_slug"] == hslug and r["region_slug"] == row["region_slug"]
                     and r["period"] == row["period"]]
            if not match or (match[0]["salary"], match[0]["n"]) != (row["salary"], row["n"]):
                warnings.append(f"{skey} 불일치: {row['region']} {row['period']}")

    # fig4: 월별 평균 NET 급여
    salary_monthly = []
    for year, vals in raw["fig4"]["data"].items():
        year = int(year)
        for i, val in enumerate(vals, start=1):
            if year == recent_year and i > end_m:
                if val:
                    warnings.append(f"월별 급여 {year}-{i:02d} 값({val})은 분석 기간 밖이라 제외")
                continue
            if not val:
                warnings.append(f"월별 급여 {year}-{i:02d} 값이 0 → null 처리")
                val = None
            salary_monthly.append({"year": year, "month": i, "salary": val})

    # demand_summary: 권역별 전년 동기 대비 증감 (종합병원 기준)
    demand_yoy, group = [], None
    alias = {}
    for gslug, g in reg["region_groups"].items():
        for name in [g["name"], *g.get("aliases", [])]:
            alias[name] = gslug
    for line in raw.get("demand_summary", []):
        if line.startswith("◆"):
            head = line.lstrip("◆ ").split(" (")[0].strip()
            if head not in alias:
                raise RegistryError(f"알 수 없는 권역 헤더: {line}")
            group = alias[head]
            continue
        m = DEMAND_RE.match(line)
        if m:
            demand_yoy.append({
                "group_slug": group,
                "region": m.group(1),
                "region_slug": slug_of(reg, "regions", m.group(1)),
                "direction": DIRECTION[m.group(3)],
                "pct": float(m.group(4)),
            })
        else:
            demand_yoy.append({"group_slug": group, "region": None, "region_slug": None,
                               "direction": None, "pct": None, "text": line})

    out = {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "source": {
            "file": str(path.resolve().relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "has_clinic_summary": "salary_summary_clinic" in raw,
        },
        "specialty": {"name": specialty, "slug": spec_slug},
        "filters": {"hospital": raw["params"]["hospital"], "region_group": raw["params"]["region_group"]},
        "period": periods,
        "demand_monthly": demand_monthly,
        "demand_mix": demand_mix,
        "salary_by_region": salary_by_region,
        "salary_by_group": salary_by_group,
        "salary_monthly": salary_monthly,
        "demand_yoy": demand_yoy,
        "warnings": warnings,
    }
    return out, warnings


def main(argv: list[str]) -> int:
    reg = load_registry()
    files = [Path(a) for a in argv] or sorted(RAW_HTML.glob("*.html"))
    RAW_DATA.mkdir(parents=True, exist_ok=True)
    ok = True
    for f in files:
        try:
            out, warns = extract(f, reg)
        except (RegistryError, ValueError, KeyError) as e:
            print(f"[실패] {f}: {e}", file=sys.stderr)
            ok = False
            continue
        expected = f"{out['specialty']['slug']}_{out['period']['recent']['slug']}.html"
        if f.name != expected:
            print(f"[경고] {f.name}: 권장 파일명은 {expected} 입니다.")
        dest = RAW_DATA / f"{out['specialty']['slug']}_{out['period']['recent']['slug']}.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[완료] {f.name} → {dest.relative_to(ROOT)} (경고 {len(warns)}건)")
        for w in warns:
            print(f"    - {w}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
