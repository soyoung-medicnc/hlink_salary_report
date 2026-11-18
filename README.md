# 의사 초빙·급여 위키 (hlink_salary_report)

메디게이트 초빙정보 기반 진료과별 **초빙수요·NET 급여 대시보드**를 Obsidian 위키로 정리한 저장소다.
위키는 LLM(Claude)이 `CLAUDE.md`의 규칙에 따라 관리한다.

## Obsidian으로 보기

1. Obsidian에서 **"폴더를 보관소로 열기"** 를 선택하고 이 저장소 폴더를 연다.
2. 커뮤니티 플러그인 **Dataview**를 활성화한다. 목차의 조회 표가 여기에 필요하다.
3. 시작 페이지는 `wiki/index.md`다. 그래프 뷰에서 리포트, 진료과, 지역의 연결을 볼 수 있다.

## 새 리포트 추가하기

1. 대시보드 HTML을 `raw/dashboards/`에 업로드한다.
2. Claude에게 **"새 리포트 ingest 해줘"** 라고 요청한다.

직접 실행하려면 아래 명령을 차례로 실행한다. 표만 갱신되고 서술은 Claude가 작성한다.

```bash
pip install pyyaml
```

```bash
python3 scripts/extract.py
```

```bash
python3 scripts/build.py
```

```bash
python3 scripts/lint.py
```

## 폴더

- `raw/`: 원본 대시보드와 추출 데이터. 원본은 수정하지 않는다.
- `wiki/`: 위키 본문(한글). 파일명은 영문이다.
- `scripts/`: 추출, 빌드, 점검 스크립트와 명칭 레지스트리.
