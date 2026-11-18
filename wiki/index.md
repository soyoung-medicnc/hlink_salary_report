---
type: index
aliases:
- 목차
- 홈
tags:
- index
---

# 의사 초빙·급여 위키

메디게이트 초빙정보 기반 진료과별 초빙수요·NET 급여 대시보드를 정리한 위키입니다.
운영 규칙은 저장소 루트의 `CLAUDE.md`, 변경 이력은 [[log|변경 이력]]을 참고하세요.

## 리포트 (최신순)

<!-- AUTO:reports START (자동 생성 — 직접 수정 금지) -->
- [[pulmonology-2026q1|호흡기내과 2026년 1~3월]]
- [[ophthalmology-2026q1|안과 2026년 1~3월]]
<!-- AUTO:reports END -->

## 진료과

<!-- AUTO:specialties START (자동 생성 — 직접 수정 금지) -->
- [[ophthalmology|안과]]
- [[pulmonology|호흡기내과]]
<!-- AUTO:specialties END -->

## 지역 · 권역 · 병원유형

<!-- AUTO:entities START (자동 생성 — 직접 수정 금지) -->
- 지역: [[seoul|서울]] · [[busan|부산]] · [[daegu|대구]] · [[incheon|인천]] · [[gwangju|광주]] · [[daejeon|대전]] · [[ulsan|울산]] · [[sejong|세종]] · [[gyeonggi|경기]] · [[gangwon|강원]] · [[chungbuk|충북]] · [[chungnam|충남]] · [[jeonbuk|전북]] · [[jeonnam|전남]] · [[gyeongbuk|경북]] · [[gyeongnam|경남]] · [[jeju|제주]]
- 권역: [[capital-area|수도권]] · [[yeongnam-area|영남권]] · [[jeju-area|제주권]]
- 병원유형: [[general-hospital|종합병원]] · [[hospital|병원]] · [[nursing-hospital|요양병원]] · [[clinic|의원]]
<!-- AUTO:entities END -->

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
