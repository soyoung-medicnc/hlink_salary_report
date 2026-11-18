"""raw/data/*.json → wiki/ 페이지 생성·갱신.

사용법:
    python3 scripts/build.py           # 페이지 생성/갱신
    python3 scripts/build.py --check   # 변경 없이 검사만 (갱신 필요 시 exit 1)

규칙
- 스크립트는 frontmatter 의 자동 키와 <!-- AUTO:이름 START --> ~ <!-- AUTO:이름 END --> 블록만 다시 쓴다.
- 그 밖의 본문(LLM/사용자 서술)은 절대 건드리지 않는다.
- 페이지가 없으면 서술 섹션 자리표시와 함께 새로 만든다.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from common import LOW_N, WIKI, load_registry, load_reports

AUTO_RE = re.compile(r"<!-- AUTO:([\w-]+) START.*?-->\n(.*?)<!-- AUTO:\1 END -->", re.S)
PLACEHOLDER = "_(작성 예정 — LLM 서술 영역)_"
HTYPES = ["general-hospital", "hospital", "nursing-hospital", "clinic"]


# ───────────────────────── 포맷 도우미 ─────────────────────────

def fmt_num(v, digits=0):
    if v is None:
        return "–"
    return f"{v:,.{digits}f}" if isinstance(v, float) and digits else f"{round(v):,}"


def fmt_salary(salary, n):
    """급여(만원) + 표본수, 표본 부족 시 ⚠️"""
    if salary is None:
        return f"– (n={n})" if n else "–"
    warn = " ⚠️" if n < LOW_N else ""
    return f"{salary:,} (n={n}){warn}"


def fmt_delta(prev, recent, unit="만원"):
    if prev is None or recent is None or prev == 0:
        return "–"
    d = recent - prev
    pct = d / prev * 100
    arrow = "▲" if d > 0 else ("▼" if d < 0 else "→")
    return f"{arrow} {abs(d):,}{unit} ({pct:+.1f}%)"


def fmt_pct(v):
    return "–" if v is None else f"{v:g}%"


WIKILINK_PIPE = re.compile(r"(\[\[[^\]|]+)\|([^\]]+\]\])")


def cell(v) -> str:
    """표 안의 [[링크|별칭]] 은 Obsidian 규칙대로 [[링크\\|별칭]] 으로 이스케이프."""
    return WIKILINK_PIPE.sub(r"\1\\|\2", str(v))


def table(headers: list[str], rows: list[list], align: list[str] | None = None) -> str:
    headers = [cell(h) for h in headers]
    rows = [[cell(c) for c in r] for r in rows]
    align = align or ["---"] + ["--:"] * (len(headers) - 1)
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(align) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def link(slug, label=None):
    return f"[[{slug}|{label}]]" if label else f"[[{slug}]]"


# ───────────────────────── 페이지 입출력 ─────────────────────────

def split_page(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.index("\n---\n", 4)
        return yaml.safe_load(text[4:end]) or {}, text[end + 5:]
    return {}, text


def dump_frontmatter(fm: dict) -> str:
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=1000) + "---\n"


def auto_block(name: str, content: str) -> str:
    return f"<!-- AUTO:{name} START (자동 생성 — 직접 수정 금지) -->\n{content.rstrip()}\n<!-- AUTO:{name} END -->"


def render_page(path: Path, fm: dict, blocks: dict[str, str], template: str) -> str:
    """기존 페이지가 있으면 frontmatter 병합 + AUTO 블록 교체, 없으면 template 로 생성."""
    if path.exists():
        old_fm, body = split_page(path.read_text(encoding="utf-8"))
        merged = {**old_fm, **fm}
        seen = set()

        def repl(m):
            name = m.group(1)
            seen.add(name)
            return auto_block(name, blocks[name]) if name in blocks else m.group(0)

        body = AUTO_RE.sub(repl, body)
        for name in blocks:
            if name not in seen:  # 새로 생긴 블록은 끝에 추가
                body = body.rstrip() + "\n\n" + auto_block(name, blocks[name]) + "\n"
        return dump_frontmatter(merged) + body
    body = template
    for name, content in blocks.items():
        body = body.replace("{{" + name + "}}", auto_block(name, content))
    return dump_frontmatter(fm) + body


# ───────────────────────── 데이터 도우미 ─────────────────────────

def period_sum(report, year):
    s, e = report["period"]["recent"]["start_month"], report["period"]["recent"]["end_month"]
    vals = [r["count"] for r in report["demand_monthly"] if r["year"] == year and s <= r["month"] <= e]
    return sum(vals) if vals else None


def period_salary_mean(report, year):
    s, e = report["period"]["recent"]["start_month"], report["period"]["recent"]["end_month"]
    vals = [r["salary"] for r in report["salary_monthly"]
            if r["year"] == year and s <= r["month"] <= e and r["salary"] is not None]
    return round(sum(vals) / len(vals)) if vals else None


def region_salary(report, region_slug, period, htype=None):
    rows = report["salary_by_group"] if htype else report["salary_by_region"]
    for r in rows:
        if r["region_slug"] == region_slug and r["period"] == period and (
                htype is None or r["hospital_type_slug"] == htype):
            return r["salary"], r["n"]
    return None, 0


def low_sample_stats(report):
    ns = [r["n"] for r in report["salary_by_region"] + report["salary_by_group"]
          if r["salary"] is not None]
    return (min(ns) if ns else None), sum(1 for n in ns if n < LOW_N)


def rlabel(reg, slug):
    return reg["region_names"][slug]


def hlabel(reg, slug):
    return reg["hospital_type_names"][slug]


def report_title(rep):
    return f"{rep['specialty']['name']} {rep['period']['recent']['label_ko']}"


# ───────────────────────── 리포트 페이지 ─────────────────────────

def build_report(reg, rep) -> tuple[Path, str]:
    rid = rep["report_id"]
    spec = rep["specialty"]
    pr, pp = rep["period"]["recent"], rep["period"]["prev"]
    min_n, low_cnt = low_sample_stats(rep)
    fm = {
        "type": "report",
        "specialty": spec["slug"],
        "specialty_name": spec["name"],
        "period": pr["slug"],
        "period_label": pr["label"],
        "prev_period_label": pp["label"],
        "source_html": rep["source"]["file"],
        "min_n": min_n,
        "low_sample_count": low_cnt,
        "aliases": [f"{spec['name']} {pr['label_ko']} 리포트"],
        "tags": ["report", f"specialty/{spec['slug']}", f"period/{pr['slug']}"],
    }

    meta = (
        f"- 진료과: {link(spec['slug'], spec['name'])}\n"
        f"- 분석 기간: **{pr['label']}** (비교: {pp['label']}, 전년 동기)\n"
        f"- 병원 필터: {rep['filters']['hospital']} / 지역 범위: {rep['filters']['region_group']}\n"
        f"- 원본 대시보드: [{Path(rep['source']['file']).name}](../../{rep['source']['file']})\n"
        f"- 추출 데이터: [{spec['slug']}_{pr['slug']}.json](../../raw/data/{spec['slug']}_{pr['slug']}.json)"
        f" · Dataview 데이터: {link('data-' + rid)}\n"
        f"- 출처·방법론: {link('methodology', '데이터 방법론')} · 표본수 기준: {link('sample-size', '표본수 해석')}\n"
    )

    d_prev, d_rec = period_sum(rep, pp["year"]), period_sum(rep, pr["year"])
    s_prev, s_rec = period_salary_mean(rep, pp["year"]), period_salary_mean(rep, pr["year"])
    kpi = table(
        ["지표", pp["label"], pr["label"], "증감"],
        [
            [f"{link('recruitment-demand', '초빙수요')} 합계(건)", fmt_num(d_prev), fmt_num(d_rec),
             fmt_delta(d_prev, d_rec, "건")],
            [f"전국 {link('net-salary', 'NET 급여')} 월평균(만원)*", fmt_num(s_prev), fmt_num(s_rec),
             fmt_delta(s_prev, s_rec)],
        ],
    ) + "\n\\* 월별 평균 NET 급여(fig4)의 해당 월 값을 단순 평균한 참고치입니다.\n"

    years = sorted({r["year"] for r in rep["demand_monthly"]})
    dm = {(r["year"], r["month"]): r["count"] for r in rep["demand_monthly"]}
    sm = {(r["year"], r["month"]): r["salary"] for r in rep["salary_monthly"]}
    months = range(1, 13)
    demand_monthly = table(["월"] + [f"{y}년" for y in years],
                           [[f"{m}월"] + [fmt_num(dm.get((y, m))) for y in years] for m in months])
    demand_monthly += mermaid_lines("월별 초빙수요(건)", years, dm)
    salary_monthly = table(["월"] + [f"{y}년" for y in years],
                           [[f"{m}월"] + [fmt_num(sm.get((y, m))) for y in years] for m in months])
    salary_monthly += mermaid_lines("월별 평균 NET 급여(만원)", years, sm)

    mix_rows = []
    for r in sorted(rep["demand_mix"], key=lambda r: (list(reg["region_names"]).index(r["region_slug"]), r["year"])):
        mix_rows.append([link(r["region_slug"], r["region"]), r["year"]] +
                        [fmt_pct(r["shares"].get(h)) for h in HTYPES])
    demand_mix = table(["지역", "연도"] + [link(h, hlabel(reg, h)) for h in HTYPES], mix_rows,
                       ["---", "---"] + ["--:"] * 4)

    yoy_rows = []
    for r in rep["demand_yoy"]:
        g = reg["region_groups"][r["group_slug"]]["name"]
        if r["region"] is None:
            yoy_rows.append([link(r["group_slug"], g), "–", r.get("text", "–")])
        else:
            arrow = {"up": "▲ 증가", "down": "▼ 감소", "flat": "→ 변화 없음"}[r["direction"]]
            yoy_rows.append([link(r["group_slug"], g), link(r["region_slug"], r["region"]),
                             f"{arrow} {r['pct']:g}%"])
    demand_yoy = table(["권역", "지역", f"{pp['label']} → {pr['label']}"], yoy_rows, ["---", "---", "---"])
    demand_yoy += "\n대시보드 원문 기준 **종합병원 초빙수요**의 전년 동기 대비 증감률입니다.\n"

    sal_rows = []
    for slug in reg["region_names"]:
        sp, np_ = region_salary(rep, slug, "prev")
        sr, nr = region_salary(rep, slug, "recent")
        if sp is None and sr is None and not (np_ or nr):
            continue
        sal_rows.append([link(slug, rlabel(reg, slug)), fmt_salary(sp, np_), fmt_salary(sr, nr), fmt_delta(sp, sr)])
    salary_region = table(["지역", pp["label"], pr["label"], "증감"], sal_rows)
    salary_region += f"\n단위: 만원(월, NET). n=표본 공고 수, ⚠️ = n<{LOW_N}.\n"

    grp_parts = []
    for gslug, g in reg["region_groups"].items():
        for h in ("general-hospital", "clinic"):
            rows = []
            for name in g["regions"]:
                slug = reg["regions"][name]
                sp, np_ = region_salary(rep, slug, "prev", h)
                sr, nr = region_salary(rep, slug, "recent", h)
                rows.append([link(slug, name), fmt_salary(sp, np_), fmt_salary(sr, nr), fmt_delta(sp, sr)])
            grp_parts.append(f"**{link(gslug, g['name'])} · {link(h, hlabel(reg, h))}**\n\n" +
                             table(["지역", pp["label"], pr["label"], "증감"], rows))
    salary_group = "\n".join(grp_parts)

    warnings = "\n".join(f"- {w}" for w in rep["warnings"]) or "- 없음"

    blocks = {
        "meta": meta, "kpi": kpi, "demand-monthly": demand_monthly, "demand-mix": demand_mix,
        "demand-yoy": demand_yoy, "salary-region": salary_region, "salary-group": salary_group,
        "salary-monthly": salary_monthly, "processing-notes": warnings,
    }
    template = f"""
# {spec['name']} 의사 초빙·급여 리포트 ({pr['label_ko']})

{{{{meta}}}}

## 요약

{PLACEHOLDER}

## 핵심 지표

{{{{kpi}}}}

## 월별 초빙수요

{{{{demand-monthly}}}}

## 지역별 병원 규모별 초빙수요 비중

{{{{demand-mix}}}}

## 권역별 초빙수요 증감

{{{{demand-yoy}}}}

## 지역별 NET 평균 급여 (전체 병원)

{{{{salary-region}}}}

## 권역·병원유형별 NET 평균 급여

{{{{salary-group}}}}

## 월별 평균 NET 급여 추이

{{{{salary-monthly}}}}

## 해석 및 시사점

{PLACEHOLDER}

## 데이터 처리 노트

{{{{processing-notes}}}}
"""
    return WIKI / "reports" / f"{rid}.md", (fm, blocks, template)


def mermaid_lines(title, years, values: dict) -> str:
    lines = []
    for y in years:
        pts = [values.get((y, m)) for m in range(1, 13)]
        while pts and pts[-1] is None:
            pts.pop()
        if not pts or any(p is None for p in pts):
            continue
        lines.append(f"    line [{', '.join(str(p) for p in pts)}]")
    if not lines:
        return ""
    xs = ", ".join(f'"{m}월"' for m in range(1, 13))
    legend = ", ".join(f"{i + 1}번째 선={y}년" for i, y in enumerate(years))
    return (f"\n```mermaid\nxychart-beta\n    title \"{title}\"\n    x-axis [{xs}]\n"
            + "\n".join(lines) + f"\n```\n\n범례: {legend}\n")


# ───────────────────────── 엔티티 페이지 ─────────────────────────

def build_specialty(reg, slug, reps):
    name = reg["specialty_names"][slug]
    fm = {"type": "specialty", "specialty": slug, "specialty_name": name,
          "report_count": len(reps), "latest_period": reps[-1]["period"]["recent"]["slug"],
          "aliases": [name], "tags": ["specialty", f"specialty/{slug}"]}
    rows = []
    for r in reps:
        pr, pp = r["period"]["recent"], r["period"]["prev"]
        d_prev, d_rec = period_sum(r, pp["year"]), period_sum(r, pr["year"])
        s_prev, s_rec = period_salary_mean(r, pp["year"]), period_salary_mean(r, pr["year"])
        rows.append([link(r["report_id"], pr["label"]), fmt_num(d_rec), fmt_delta(d_prev, d_rec, "건"),
                     fmt_num(s_rec), fmt_delta(s_prev, s_rec)])
    reports = table(["리포트(기간)", "초빙수요 합계", "전년 동기 대비", "NET 월평균*", "전년 동기 대비"], rows)
    reports += "\n\\* 월별 평균 NET 급여의 단순 평균(만원), 참고치.\n"

    labels = [r["period"]["recent"]["label"] for r in reps]
    rows = []
    for rslug in reg["region_names"]:
        cells = [fmt_salary(*region_salary(r, rslug, "recent")) for r in reps]
        if all(c == "–" for c in cells):
            continue
        rows.append([link(rslug, rlabel(reg, rslug))] + cells)
    salary = table(["지역"] + labels, rows) + f"\n전체 병원 기준 NET 평균 급여(만원). ⚠️ = n<{LOW_N}.\n"

    blocks = {"reports": reports, "salary-by-region": salary}
    template = f"""
# {name}

## 개요

{PLACEHOLDER}

## 리포트 목록

{{{{reports}}}}

## 지역별 NET 평균 급여 (기간별)

{{{{salary-by-region}}}}

## 추세와 특징

{PLACEHOLDER}
"""
    return WIKI / "specialties" / f"{slug}.md", (fm, blocks, template)


def group_of(reg, region_name):
    for gslug, g in reg["region_groups"].items():
        if region_name in g["regions"]:
            return gslug
    return None


def build_region(reg, slug, reports):
    name = rlabel(reg, slug)
    gslug = group_of(reg, name)
    fm = {"type": "region", "region": slug, "region_name": name,
          "region_group": gslug, "aliases": [name], "tags": ["region", f"region/{slug}"]}

    rows = []
    for r in reports:
        pr = r["period"]["recent"]
        sp, np_ = region_salary(r, slug, "prev")
        sr, nr = region_salary(r, slug, "recent")
        g = [region_salary(r, slug, "recent", h) for h in ("general-hospital", "clinic")]
        rows.append([link(r["specialty"]["slug"], r["specialty"]["name"]), link(r["report_id"], pr["label"]),
                     fmt_salary(sr, nr), fmt_delta(sp, sr)] +
                    [fmt_salary(*x) if gslug else "–" for x in g])
    salary = table(["진료과", "기간", "전체 병원", "전년 동기 대비", "종합병원", "의원"], rows,
                   ["---", "---", "--:", "--:", "--:", "--:"])
    salary += f"\nNET 평균 급여(만원/월). ⚠️ = n<{LOW_N}. 종합병원·의원 구분은 권역(수도권·영남권·제주권) 지역만 제공됩니다.\n"

    rows = []
    for r in reports:
        for m in sorted((x for x in r["demand_mix"] if x["region_slug"] == slug), key=lambda x: x["year"]):
            rows.append([link(r["specialty"]["slug"], r["specialty"]["name"]), link(r["report_id"], r["period"]["recent"]["label"]),
                         m["year"]] + [fmt_pct(m["shares"].get(h)) for h in HTYPES])
    mix = table(["진료과", "리포트", "연도"] + [hlabel(reg, h) for h in HTYPES], rows,
                ["---", "---", "---"] + ["--:"] * 4) if rows else "- 데이터 없음\n"

    rows = []
    for r in reports:
        for y in r["demand_yoy"]:
            if y["region_slug"] == slug:
                arrow = {"up": "▲", "down": "▼", "flat": "→"}[y["direction"]]
                rows.append([link(r["specialty"]["slug"], r["specialty"]["name"]),
                             f"{r['period']['prev']['label']} → {r['period']['recent']['label']}", f"{arrow} {y['pct']:g}%"])
    yoy = (table(["진료과", "비교", "종합병원 초빙수요 증감"], rows, ["---", "---", "--:"]) if rows
           else "- 대시보드에 해당 지역의 증감 요약이 없습니다.\n")

    group_line = f"- 권역: {link(gslug, reg['region_groups'][gslug]['name'])}\n" if gslug else "- 권역: 대시보드 권역 구분 밖 지역\n"
    blocks = {"info": group_line, "salary": salary, "demand-mix": mix, "demand-yoy": yoy}
    template = f"""
# {name}

{{{{info}}}}

## 개요

{PLACEHOLDER}

## 진료과별 NET 평균 급여

{{{{salary}}}}

## 병원 규모별 초빙수요 비중

{{{{demand-mix}}}}

## 초빙수요 증감 (종합병원)

{{{{demand-yoy}}}}
"""
    return WIKI / "regions" / f"{slug}.md", (fm, blocks, template)


def build_region_group(reg, gslug, reports):
    g = reg["region_groups"][gslug]
    fm = {"type": "region-group", "region_group": gslug, "region_group_name": g["name"],
          "aliases": [g["name"]], "tags": ["region-group"]}
    info = "- 포함 지역: " + ", ".join(link(reg["regions"][n], n) for n in g["regions"]) + "\n"
    parts = []
    for r in reports:
        pr, pp = r["period"]["recent"], r["period"]["prev"]
        rows = []
        for n in g["regions"]:
            s = reg["regions"][n]
            for h in ("general-hospital", "clinic"):
                sp, np_ = region_salary(r, s, "prev", h)
                sr, nr = region_salary(r, s, "recent", h)
                rows.append([link(s, n), hlabel(reg, h), fmt_salary(sp, np_), fmt_salary(sr, nr), fmt_delta(sp, sr)])
        parts.append(f"**{link(r['report_id'], report_title(r))}**\n\n" +
                     table(["지역", "병원유형", pp["label"], pr["label"], "증감"], rows, ["---", "---", "--:", "--:", "--:"]))
    blocks = {"info": info, "salary": "\n".join(parts)}
    template = f"""
# {g['name']}

{{{{info}}}}

## 개요

{PLACEHOLDER}

## 리포트별 종합병원·의원 NET 평균 급여

{{{{salary}}}}
"""
    return WIKI / "region-groups" / f"{gslug}.md", (fm, blocks, template)


def build_hospital_type(reg, hslug, reports):
    name = hlabel(reg, hslug)
    fm = {"type": "hospital-type", "hospital_type": hslug, "hospital_type_name": name,
          "aliases": [name], "tags": ["hospital-type"]}
    parts = []
    for r in reports:
        ry = r["period"]["recent"]["year"]
        py = r["period"]["prev"]["year"]
        by = defaultdict(dict)
        for m in r["demand_mix"]:
            by[m["region_slug"]][m["year"]] = m["shares"].get(hslug)
        rows = [[link(s, rlabel(reg, s)), fmt_pct(by[s].get(py)), fmt_pct(by[s].get(ry))]
                for s in reg["region_names"] if s in by]
        parts.append(f"**{link(r['report_id'], report_title(r))}**\n\n" + table(["지역", f"{py}년", f"{ry}년"], rows))
    mix = "\n".join(parts) + f"\n각 지역 초빙수요 중 {name} 비중(%).\n"
    blocks = {"demand-share": mix}
    template = f"""
# {name}

## 개요

{PLACEHOLDER}

## 지역별 초빙수요 중 {name} 비중

{{{{demand-share}}}}
"""
    return WIKI / "hospital-types" / f"{hslug}.md", (fm, blocks, template)


def build_data_page(reg, rep):
    rid = rep["report_id"]
    pr = rep["period"]
    sp = rep["specialty"]["slug"]
    fm = {"type": "data", "report": rid, "specialty": sp, "period": pr["recent"]["slug"],
          "tags": ["data"]}

    def item(kind, region, hosp, period, **vals):
        fields = f"[report:: {rid}] [metric:: {kind}] [specialty:: {sp}] [region:: {region}] [hospital:: {hosp}] " \
                 f"[period:: {pr[period]['slug']}] [period_label:: {pr[period]['label']}] [period_kind:: {period}]"
        fields += "".join(f" [{k}:: {v}]" for k, v in vals.items() if v is not None)  # 결측은 필드 생략
        return "- " + fields

    lines = []
    for r in rep["salary_by_region"]:
        lines.append(item("salary", r["region_slug"], "all", r["period"], salary=r["salary"], n=r["n"],
                          low_sample=str(r["n"] < LOW_N).lower()))
    for r in rep["salary_by_group"]:
        lines.append(item("salary", r["region_slug"], r["hospital_type_slug"], r["period"], salary=r["salary"],
                          n=r["n"], low_sample=str(r["n"] < LOW_N).lower()))
    for r in rep["demand_yoy"]:
        if r["region_slug"]:
            sign = {"up": 1, "down": -1, "flat": 0}[r["direction"]]
            lines.append(item("demand_yoy", r["region_slug"], "general-hospital", "recent", pct=sign * r["pct"]))
    body = (f"\n# 데이터: {report_title(rep)}\n\n"
            f"Dataview 조회용 원시 데이터입니다. 원본 리포트: {link(rid)}\n\n"
            "{{rows}}\n")
    return WIKI / "data" / f"data-{rid}.md", (fm, {"rows": "\n".join(lines)}, body)


def build_index(reg, reports, specs):
    fm = {"type": "index", "aliases": ["목차", "홈"], "tags": ["index"]}
    rep_list = "\n".join(f"- {link(r['report_id'], report_title(r))}" for r in reversed(reports))
    spec_list = "\n".join(f"- {link(s, reg['specialty_names'][s])}" for s in specs)
    region_list = " · ".join(link(s, n) for s, n in reg["region_names"].items())
    group_list = " · ".join(link(g, v["name"]) for g, v in reg["region_groups"].items())
    htype_list = " · ".join(link(h, n) for h, n in reg["hospital_type_names"].items())
    blocks = {"reports": rep_list, "specialties": spec_list,
              "entities": f"- 지역: {region_list}\n- 권역: {group_list}\n- 병원유형: {htype_list}\n"}
    template = """
# 의사 초빙·급여 위키

메디게이트 초빙정보 기반 진료과별 초빙수요·NET 급여 대시보드를 정리한 위키입니다.
운영 규칙은 저장소 루트의 `CLAUDE.md`, 변경 이력은 [[log|변경 이력]]을 참고하세요.

## 리포트 (최신순)

{{reports}}

## 진료과

{{specialties}}

## 지역 · 권역 · 병원유형

{{entities}}

## 개념

- [[net-salary|NET 급여]] · [[recruitment-demand|초빙수요]] · [[methodology|데이터 방법론]] · [[sample-size|표본수 해석]]

## 분석

```dataview
LIST
FROM "wiki/analyses"
SORT file.mtime DESC
```

## Dataview 조회

### 리포트 현황

```dataview
TABLE specialty_name AS "진료과", period_label AS "기간", min_n AS "최소 표본", low_sample_count AS "표본 부족 항목"
FROM "wiki/reports"
SORT period DESC, specialty ASC
```

### 지역·진료과별 최신 NET 급여 (전체 병원)

```dataview
TABLE WITHOUT ID L.specialty AS "진료과", L.region AS "지역", L.period_label AS "기간", L.salary AS "급여(만원)", L.n AS "n"
FROM "wiki/data"
FLATTEN file.lists AS L
WHERE L.metric = "salary" AND L.hospital = "all" AND L.period_kind = "recent" AND L.salary != null
SORT L.salary DESC
```

### 표본 부족(n<10) 급여 값

```dataview
TABLE WITHOUT ID L.report AS "리포트", L.region AS "지역", L.hospital AS "병원유형", L.period_label AS "기간", L.salary AS "급여", L.n AS "n"
FROM "wiki/data"
FLATTEN file.lists AS L
WHERE L.metric = "salary" AND L.low_sample = true AND L.salary != null
SORT L.n ASC
```

### 최근 수정된 페이지

```dataview
TABLE type AS "유형", file.mtime AS "수정"
FROM "wiki"
WHERE type != "data"
SORT file.mtime DESC
LIMIT 10
```
"""
    return WIKI / "index.md", (fm, blocks, template)


# ───────────────────────── 메인 ─────────────────────────

def plan(reg) -> list[tuple[Path, tuple]]:
    reports = load_reports()
    jobs = []
    by_spec = defaultdict(list)
    for r in reports:
        jobs.append(build_report(reg, r))
        jobs.append(build_data_page(reg, r))
        by_spec[r["specialty"]["slug"]].append(r)
    for s, reps in by_spec.items():
        jobs.append(build_specialty(reg, s, reps))
    for s in reg["region_names"]:
        jobs.append(build_region(reg, s, reports))
    for g in reg["region_groups"]:
        jobs.append(build_region_group(reg, g, reports))
    for h in reg["hospital_type_names"]:
        jobs.append(build_hospital_type(reg, h, reports))
    jobs.append(build_index(reg, reports, sorted(by_spec)))
    return jobs


def main(argv) -> int:
    check = "--check" in argv
    reg = load_registry()
    changed = []
    for path, (fm, blocks, template) in plan(reg):
        new = render_page(path, fm, blocks, template)
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if new != old:
            changed.append(path)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(new, encoding="utf-8")
    log = WIKI / "log.md"
    if not log.exists() and not check:
        log.write_text(dump_frontmatter({"type": "log", "aliases": ["변경 이력"]}) +
                       "\n# 변경 이력\n\n새 항목은 위에 추가합니다. 형식: `## YYYY-MM-DD 작업 | 대상`\n", encoding="utf-8")
    for p in changed:
        print(f"{'[갱신 필요]' if check else '[갱신]'} {p.relative_to(WIKI.parent)}")
    print(f"{'검사' if check else '빌드'} 완료: 변경 {len(changed)}건")
    return 1 if (check and changed) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
