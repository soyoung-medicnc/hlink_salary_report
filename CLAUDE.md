# 의사 초빙·급여 LLM 위키 — 운영 규칙

이 저장소는 메디게이트 초빙정보 기반 **진료과별 초빙수요·급여 대시보드(HTML)** 를 원천으로 삼는 LLM 위키다. Obsidian으로 열람한다(저장소 루트 = Vault).
LLM(Claude)은 이 문서의 규칙에 따라 위키를 만들고 갱신한다.

## 언어 규칙

- **파일명·폴더명·슬러그**: 영문 소문자와 하이픈만 쓴다(예: `seoul.md`, `ophthalmology-2026q1.md`).
- **위키 본문, frontmatter의 aliases, 사람이 읽는 문서(README, 이 파일, log)**: 모두 **한글**로 쓴다.
- **링크**: 별칭을 붙여 한글로 보이게 쓴다. 예: `[[seoul|서울]]`. 표 안에서는 `[[seoul\|서울]]`로 쓴다.

## 폴더 구조

| 경로 | 내용 | 수정 주체 |
| --- | --- | --- |
| `raw/dashboards/` | 원본 대시보드 HTML. **수정 금지**. 파일명은 `<진료과슬러그>_<기간슬러그>.html` | 사용자 업로드 |
| `raw/data/` | 정규화된 추출 JSON | `extract.py` |
| `scripts/registry.yaml` | 한글 명칭 ↔ 영문 슬러그 (진료과·지역·권역·병원유형) | LLM/사용자 |
| `wiki/reports/` | 리포트(원본 1개)당 1페이지 | 표: 스크립트, 서술: LLM |
| `wiki/specialties/` · `regions/` · `region-groups/` · `hospital-types/` | 엔티티 페이지 | 표: 스크립트, 서술: LLM |
| `wiki/concepts/` | 개념·방법론 | LLM |
| `wiki/analyses/` | 비교 분석, 질의응답 결과 저장 | LLM |
| `wiki/data/` | Dataview 조회용 데이터 | 스크립트 전용 |
| `wiki/index.md` | 목차 + Dataview 조회 | 목록: 스크립트, 나머지: LLM |
| `wiki/log.md` | 변경 이력 (최신이 위) | LLM |

## 핵심 원칙: 숫자는 스크립트, 서술은 LLM

1. **`<!-- AUTO:이름 START -->` ~ `<!-- AUTO:이름 END -->` 블록과 frontmatter 자동 키는 `scripts/build.py`만 쓴다.** LLM은 이 영역을 직접 고치지 않는다.
2. **서술에서 숫자를 쓸 때는 AUTO 표에 있는 값을 그대로 인용한다.** 새로 계산하거나 반올림한 수치를 만들지 않는다. 대략적인 표현이 필요하면 "두 배 이상", "1천 건 안팎"처럼 쓴다.
3. **표본 n<10 값은 근거로 쓸 때 반드시 표본 부족을 함께 밝힌다.** n이 1~3인 값으로는 증감을 해석하지 않는다(→ `wiki/concepts/sample-size.md`).
4. **원인을 단정하지 않는다.** 데이터로 확인되지 않은 원인은 "가능성"으로 쓰고, 확인할 거리로 남긴다.
5. **서술 자리표시 `_(작성 예정 — LLM 서술 영역)_`는 서술을 작성하면서 지운다.**

## 페이지 frontmatter

- **모든 위키 페이지**: `type`이 있어야 한다. 값은 `report | specialty | region | region-group | hospital-type | concept | analysis | data | index | log` 중 하나다.
- **엔티티 페이지**: `aliases`에 한글명을 넣는다.
- **analysis 페이지**: `period`, `specialties`, `sources`(근거 리포트 링크)를 넣는다.

## 워크플로

### 1) Ingest — 새 리포트 추가

1. 새 HTML을 `raw/dashboards/`에 둔다. 파일명은 `<진료과슬러그>_<기간슬러그>.html`(예: `orthopedics_2026q2.html`)로 바꾼다. 슬러그는 `registry.yaml`에서 확인한다.
2. `python3 scripts/extract.py`를 실행한다.
   - "레지스트리에 없는 명칭" 오류가 나면 `scripts/registry.yaml`에 추가하고 다시 실행한다.
   - 경고(기간 밖 값 제외, 결측 처리, 템플릿 차이)를 확인한다.
3. `python3 scripts/build.py`를 실행한다. 새 페이지가 생기고, 기존 페이지의 AUTO 표가 갱신된다.
4. LLM 서술 작업:
   - 새 리포트 페이지의 "요약", "해석 및 시사점"을 쓴다.
   - 새 진료과 페이지라면 "개요", "추세와 특징"을 쓴다.
   - 기존 진료과·지역·권역 페이지의 서술이 새 데이터와 어긋나면 고친다. 예: 시계열이 생겼으면 추세 서술을 갱신한다.
   - 의미 있는 비교가 생기면 `wiki/analyses/`에 페이지를 만든다.
5. `python3 scripts/lint.py`를 실행해 오류 0건, 출처 불명 숫자 경고 0건을 확인한다.
6. `wiki/log.md` 맨 위에 항목을 추가한다(`## YYYY-MM-DD ingest | <리포트>`).
7. 커밋한다.

### 2) Query — 질문에 답하기

- **위키 페이지를 근거로 답하고, 근거 페이지를 `[[링크]]`로 밝힌다.**
- **위키에 없는 내용은** `raw/data/*.json`을 확인한다. 그래도 없으면 "데이터 없음"이라고 답한다.
- **재사용할 가치가 있는 답은** `wiki/analyses/<영문-슬러그>.md`로 저장하고, log에 기록한다.

### 3) Lint — 정기 점검

`python3 scripts/lint.py`를 실행한다. 점검 항목:
- 깨진 링크
- frontmatter 누락
- AUTO 블록과 데이터 불일치
- 고아 페이지
- 서술 미작성
- 서술 속 출처 불명 숫자

경고가 나오면 해당 페이지를 고친다.

## 스크립트 요약

```bash
python3 scripts/extract.py          # HTML → raw/data/*.json
python3 scripts/build.py            # JSON → wiki 표/frontmatter 갱신 (멱등)
python3 scripts/build.py --check    # 갱신 필요 여부만 검사
python3 scripts/lint.py             # 위키 점검
```

필요 패키지는 Python 3.10+와 PyYAML이다.
