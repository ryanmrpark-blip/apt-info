# 일자별 아파트 매매 실거래가 상세 조회 및 SQLite 요약 관리 구현 계획서

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 국토교통부 아파트 실거래가 시스템에 SQLite 기반 일자별 요약 테이블(`daily_trade_summary`)을 신설하고, 특정 일자의 실거래 상세 정보(KPI, 시도별/가격대별 차트, 상세 그리드, 필터/다운로드)를 심층 조회할 수 있는 Streamlit 전용 페이지(`pages/1_📅_일자별_거래내역.py`)를 구축합니다.

**Architecture:** SQLite 마스터 DB(`apt_trades.db`)에 일자별 핵심 통계 테이블을 생성하고 데이터 수집 파이프라인에서 자동 집계·Upsert되도록 연동합니다. 비즈니스 쿼리 모듈(`db_queries.py`)을 통해 일자별 요약 및 상세 필터링 데이터를 고속 추출하며, Streamlit 표준 멀티페이지(`pages/`) 구조를 적용하여 반응형 인터랙티브 상세 조회 UI를 제공합니다.

**Tech Stack:** Python 3.12, Streamlit, SQLite3, DuckDB, Pandas, Plotly Express, Pytest, uv

**Spec:** `docs/superpowers/specs/2026-10-05-daily-trade-details-and-summary-design.md`

## Global Constraints

- 모든 Python 가상환경 명령 및 테스트는 `uv run`을 사용합니다.
- 파일 입출력 및 모듈 참조 시 프로젝트 루트 기준 상대 경로(`resolve_relative_path`)를 준수합니다.
- 신규 및 수정되는 Python 코드(`*.py`)는 한국어 Google Style Docstring, 타입 힌트(`typing`), 한글 주석 규칙을 준수합니다.
- 금액 표기는 기존 `format_amount()` 한글 단위(억/만원) 포맷팅 규칙을 일관되게 적용합니다.

## Review Focus

1. **거래 데이터가 전혀 없는 빈 DB 상태**: `init_db()` 후에도 앱이 충돌 없이 안전하게 빈 상태 안내(`st.info` / `st.warning`)를 렌더링해야 함.
2. **거래가 없는 휴일/미수집 일자 선택**: 0건일 때 `ZeroDivisionError` 없이 건수 0, 금액 0으로 정상 처리되어야 함.
3. **기존 `apt_trades`에 이미 데이터가 있는 환경에서의 마이그레이션**: `sync_daily_summary()`가 과거 적재된 데이터까지 누락 없이 일괄 집계해야 함.
4. **동일 일자 데이터 재수집/재동기화 시 정합성**: 중복 행이 생성되지 않고 기존 일자 요약이 정상 갱신(Upsert)되어야 함.
5. **특수 문자 및 한글 단지명 검색**: 검색창에 작은따옴표나 특수문자가 입력되어도 SQL Injection 위험 없이 매개변수화된 쿼리로 안전하게 필터링되어야 함.

---

### Task 1: SQLite `daily_trade_summary` 스키마 및 자동 동기화 모듈 구현

**Files:**
- Create: `tests/test_daily_summary.py`
- Modify: `src/storage.py`

**Interfaces:**
- Consumes: `apt_trades` SQLite 테이블 스키마
- Produces:
  - `init_db(db_path: Optional[Path] = None) -> None`: `daily_trade_summary` 테이블 및 인덱스 생성
  - `sync_daily_summary(db_path: Optional[Path] = None, target_date: Optional[str] = None) -> int`: 요약 테이블 Upsert 집계 실행 및 갱신된 일자 수 반환
  - `get_daily_summary_records(db_path: Optional[Path] = None) -> pd.DataFrame`: 요약 테이블 전체 데이터프레임 반환

- [ ] **Step 1: Write the failing tests for summary schema & sync**

`tests/test_daily_summary.py`에 다음 테스트 작성:
1. `test_init_db_creates_summary_table`: `daily_trade_summary` 테이블 및 인덱스 존재 확인
2. `test_sync_daily_summary_aggregation`: 샘플 실거래 3건 적재 후 `sync_daily_summary()` 실행 시 올바른 집계값(총건수, 총액, 평균가, 최고가 아파트명, 직거래건수 등) 검증
3. `test_sync_daily_summary_upsert`: 동일 일자 데이터 추가 후 재동기화 시 중복 없이 갱신되는지 검증

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_daily_summary.py -v`
Expected: FAIL (테이블 또는 함수 부재)

- [ ] **Step 3: Implement `daily_trade_summary` in `src/storage.py`**

- `init_db()`에 `daily_trade_summary` 테이블 생성 DDL 및 `idx_summary_date` 인덱스 생성문 추가
- `sync_daily_summary(db_path=None, target_date=None) -> int` 구현:
  `apt_trades`에서 `GROUP BY deal_date`로 집계하여 `INSERT OR REPLACE INTO daily_trade_summary` 수행
- `save_trades_to_sqlite()` 함수 말미에 `sync_daily_summary(target_path)` 자동 호출 추가
- `get_daily_summary_records(db_path=None) -> pd.DataFrame` 구현

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_daily_summary.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_daily_summary.py src/storage.py
git commit -m "feat(storage): SQLite 일자별 요약 테이블(daily_trade_summary) 스키마 및 자동 동기화 구현"
```

---

### Task 2: 일자별 상세 거래 및 통계 비즈니스 쿼리 모듈 확장

**Files:**
- Create: `tests/test_daily_queries.py`
- Modify: `src/db_queries.py`

**Interfaces:**
- Consumes: Task 1의 `daily_trade_summary` 및 `apt_trades` 테이블
- Produces:
  - `get_available_deal_dates(db_path: Optional[Path] = None) -> list[str]`: 거래 데이터가 있는 날짜 목록(내림차순)
  - `get_single_day_summary(deal_date: str, db_path: Optional[Path] = None) -> Optional[dict]`: 특정 일자의 핵심 지표 딕셔너리
  - `get_trades_by_date(deal_date: str, sido_filter: Optional[str] = None, sgg_filter: Optional[str] = None, min_amount: Optional[int] = None, max_amount: Optional[int] = None, apt_search: Optional[str] = None, db_path: Optional[Path] = None) -> pd.DataFrame`: 특정 일자의 상세 거래 목록 필터 조회
  - `get_day_region_distribution(deal_date: str, db_path: Optional[Path] = None) -> pd.DataFrame`: 당일 시도별 거래건수 및 평균가
  - `get_day_price_bands(deal_date: str, db_path: Optional[Path] = None) -> pd.DataFrame`: 당일 5단계 금액대별 거래건수 및 비율

- [ ] **Step 1: Write the failing tests for daily queries**

`tests/test_daily_queries.py`에 다음 테스트 작성:
1. `test_get_available_deal_dates`: 일자 목록이 최신순 정렬되어 반환되는지 검증
2. `test_get_single_day_summary`: 특정 일자 레코드 조회 및 필드 정합성 검증
3. `test_get_trades_by_date_with_filters`: 시도 필터 및 단지명 검색 조건 정상 동작 검증
4. `test_get_day_region_and_price_bands`: 시도별 집계 및 금액대별 도넛 분포 데이터 구조 검증

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_daily_queries.py -v`
Expected: FAIL

- [ ] **Step 3: Implement query functions in `src/db_queries.py`**

- `get_available_deal_dates` 구현
- `get_single_day_summary` 구현
- `get_trades_by_date` 매개변수화된 안전한 SQL 필터링 구현
- `get_day_region_distribution` 및 `get_day_price_bands` 구현
- 모든 함수에 한국어 Docstring 및 타입 힌트 철저 적용

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_daily_queries.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_daily_queries.py src/db_queries.py
git commit -m "feat(queries): 일자별 요약 및 상세 거래 내역 조회 쿼리 함수 구현"
```

---

### Task 3: Streamlit 일자별 상세 조회 페이지 (`pages/1_📅_일자별_거래내역.py`) 구현

**Files:**
- Create: `pages/1_📅_일자별_거래내역.py`
- Create: `tests/test_daily_page.py`

**Interfaces:**
- Consumes:
  - Task 1: `sync_daily_summary`, `init_db`
  - Task 2: `get_available_deal_dates`, `get_single_day_summary`, `get_trades_by_date`, `get_day_region_distribution`, `get_day_price_bands`
  - Existing: `format_amount`, `SIDO_LIST`, `SGG_CODE_MAP`
- Produces:
  - 완전한 독립형 Streamlit 상세 조회 페이지

- [ ] **Step 1: Write unit/sanity test for the page module**

`tests/test_daily_page.py`에 페이지 모듈의 핵심 헬퍼 및 함수 import/렌더링 안전성 검증 테스트 작성:
1. `test_page_module_import`: 모듈 구문 오류 없이 로드되는지 확인
2. `test_format_helpers_on_page`: 금액 및 라벨 포맷팅 정상 동작 확인

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_daily_page.py -v`
Expected: FAIL (페이지 파일 부재)

- [ ] **Step 3: Implement `pages/1_📅_일자별_거래내역.py`**

1. 페이지 타이틀 및 아이콘 설정 (`st.set_page_config`)
2. 상단 네비게이션: 최근 거래일 퀵 버튼 칩 (`st.button`) + 캘린더 날짜 셀렉터 + `🔄 요약 갱신` 버튼
3. 당일 5대 KPI 카드 섹션: 총 거래건수, 총 대금, 평균가, 평당 평균가, 최고가 단지/금액
4. 당일 시각화 차트 섹션:
   - 좌측: 시도별 거래 건수 및 평균가 인터랙티브 막대 차트 (Plotly)
   - 우측: 금액대별 거래 비중 도넛 차트 (Plotly)
5. 상세 거래 내역 및 필터 섹션:
   - 시도/시군구 필터, 단지명 검색 입력, 금액대 슬라이더
   - 포맷팅된 데이터프레임(`st.dataframe`) 표출
   - CSV 다운로드 버튼(`st.download_button`)
6. 빈 데이터 및 에러 방어 처리 (`st.info`, `st.warning`)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_daily_page.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pages/1_📅_일자별_거래내역.py tests/test_daily_page.py
git commit -m "feat(ui): Streamlit 일자별 아파트 실거래가 상세 조회 페이지 구현"
```

---

### Task 4: 기존 DB 마이그레이션 동기화 및 E2E 전체 회귀 테스트 검증

**Files:**
- Modify: `tests/test_app.py`
- Modify: `README.md`

- [ ] **Step 1: Existing SQLite database summary sync verification**

로컬의 기존 `data/processed/apt_trades.db`에 이미 적재된 데이터가 있다면 `sync_daily_summary()`를 실행하여 `daily_trade_summary` 테이블을 채우는 스크립트 실행 및 확인

- [ ] **Step 2: Run entire test suite**

Run: `uv run pytest -v`
Expected: All existing tests and new daily summary/query/page tests PASS without regression

- [ ] **Step 3: Update README.md with page structure and daily summary guide**

`README.md`에 새로 추가된 `pages/1_📅_일자별_거래내역.py` 및 SQLite 요약 관리 기능 설명 추가

- [ ] **Step 4: Commit**

```bash
git add README.md tests/test_app.py
git commit -m "docs: 일자별 거래내역 페이지 안내 및 SQLite 요약 관리 문서 갱신"
```
