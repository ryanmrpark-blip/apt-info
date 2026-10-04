# 아파트 실거래가 수집 및 Streamlit 대시보드 구축 실행 계획서

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 국토교통부 Open API를 통해 최근 1주일간의 전국 아파트 매매 실거래가를 수집하고, SQLite/Parquet/DuckDB 파이프라인과 Streamlit 대시보드를 구축하여 GitHub Actions로 매일 자동 수집되는 무료 배포 시스템을 완성합니다.

**Architecture:** Open API 비동기 수집 -> SQLite 마스터 DB Upsert (중복 방지) -> Parquet 스냅샷 추출 (초경량 배포용) -> DuckDB 인메모리 OLAP SQL 엔진 -> Streamlit + Plotly 반응형 대시보드 -> GitHub Actions Cron 매일 자동 실행.

**Tech Stack:** Python 3.12, uv, httpx, sqlite3, pyarrow, duckdb, streamlit, plotly, python-dotenv.

**Spec:** [2026-10-04-apt-trades-pipeline-dashboard-design.md](file:///c:/Users/ryanm/OneDrive/문서/antigravity/eda/apt-info/docs/superpowers/specs/2026-10-04-apt-trades-pipeline-dashboard-design.md)

## Global Constraints

- Python 가상환경은 항상 `uv`만 사용 (`.venv`)
- 모든 파일 입출력 및 모듈 참조는 프로젝트 루트(`apt-info`) 기준 **상대 경로** 사용
- 모든 Python 코드는 한국어 Docstring(Google Style)과 타입 힌트(`typing`) 필수 적용
- 대용량 데이터베이스 파일 및 API 인증키는 Git 커밋에서 제외 (`.gitignore` 준수)
- TDD 준수: 각 작업마다 테스트 작성 -> 실패 확인 -> 구현 -> 통과 확인 -> 커밋

## Review Focus

1. **API 호출 월 경계(월초) 처리**: 오늘이 1~7일일 때 전월 및 당월 2개 월을 빠짐없이 수집하여 7일 데이터 누락을 방지하는가?
2. **거래 해제(취소) 건 제외**: `cdealType == 'O'`인 해제 거래가 실거래 집계에 섞이지 않고 엄격히 배제되는가?
3. **SQLite 중복 방지 무결성**: 동일한 거래 데이터가 중복 수집될 때 `trade_id` 해시 키를 통해 완벽히 스킵되는가?
4. **Parquet 압축 크기 및 배포 호환성**: 추출된 Parquet 파일이 Streamlit Cloud 메모리(1GB) 및 GitHub 용량 한도 내에서 초고속 로딩되는가?
5. **DuckDB 쿼리 예외 안전성**: 필터 조건에 따라 데이터가 0건일 때 Streamlit UI에서 오류 없이 빈 상태 안내가 출력되는가?

---

### Task 1: 프로젝트 의존성 추가 및 전국 시군구 매핑 상수 구성

**Files:**
- Modify: `pyproject.toml`
- Create: `data/raw/sgg_codes.json`
- Create: `src/constants.py`
- Test: `tests/test_constants.py`

**Interfaces:**
- Consumes: None
- Produces:
  - `SGG_CODE_MAP: dict[str, str]` (5자리 시군구코드 -> 시도명 + 시군구명)
  - `SIDO_LIST: list[str]` (전국 17개 시도명 목록)
  - `get_sgg_name(sgg_cd: str) -> tuple[str, str]` (시도명, 시군구명 반환 함수)

- [ ] **Step 1: Write the failing test for constants and SGG mapping**

```python
# tests/test_constants.py
import unittest
from src.constants import SGG_CODE_MAP, SIDO_LIST, get_sgg_name

class TestConstants(unittest.TestCase):
    def test_sido_list_contains_major_cities(self) -> None:
        self.assertIn("서울특별시", SIDO_LIST)
        self.assertIn("경기도", SIDO_LIST)
        self.assertIn("부산광역시", SIDO_LIST)

    def test_get_sgg_name(self) -> None:
        sido, sgg = get_sgg_name("11680")
        self.assertEqual(sido, "서울특별시")
        self.assertEqual(sgg, "강남구")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests/test_constants.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.constants'`

- [ ] **Step 3: Update `pyproject.toml` and implement `src/constants.py` and `data/raw/sgg_codes.json`**

Add dependencies to `pyproject.toml` (`httpx`, `streamlit`, `duckdb`, `pyarrow`, `plotly`, `python-dotenv`, `pandas`).
Run `uv sync` to install dependencies.
Populate `data/raw/sgg_codes.json` with standard 250 legal district codes.
Implement `src/constants.py` exporting `SGG_CODE_MAP`, `SIDO_LIST`, `get_sgg_name`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests/test_constants.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock data/raw/sgg_codes.json src/constants.py tests/test_constants.py
git commit -m "feat: 의존성 패키지 추가 및 전국 시군구 매핑 상수 구성"
```

---

### Task 2: SQLite 마스터 DB 및 Parquet 스토리지 계층 구현

**Files:**
- Create: `src/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `src/utils.py` (`resolve_relative_path`, `ensure_directory`), `src/constants.py` (`get_sgg_name`)
- Produces:
  - `init_db(db_path: Path | None = None) -> None`: SQLite 테이블 및 인덱스 초기화
  - `generate_trade_id(record: dict) -> str`: 거래 고유 해시 ID 생성
  - `save_trades_to_sqlite(trades: list[dict], db_path: Path | None = None) -> int`: 중복 없이 Upsert 후 신규 저장 건수 반환
  - `export_recent_trades_to_parquet(days: int = 7, db_path: Path | None = None, parquet_path: Path | None = None) -> int`: Parquet 저장 및 건수 반환

- [ ] **Step 1: Write the failing test for storage layer**

```python
# tests/test_storage.py
import unittest
from pathlib import Path
from src.storage import init_db, save_trades_to_sqlite, export_recent_trades_to_parquet
import duckdb

class TestStorage(unittest.TestCase):
    def test_save_and_export_trades(self) -> None:
        test_db = Path("data/processed/test_trades.db")
        test_parquet = Path("data/processed/test_recent.parquet")
        init_db(test_db)
        sample = [{
            "sggCd": "11680", "umdNm": "대치동", "aptNm": "은마", "jibun": "316",
            "excluUseAr": "84.43", "dealYear": "2026", "dealMonth": "10", "dealDay": "03",
            "dealAmount": "280,000", "floor": "7", "buildYear": "1979", "cdealType": "",
            "dealingGbn": "중개거래", "estateAgentSggNm": "서울 강남구", "rgstDate": ""
        }]
        saved_count = save_trades_to_sqlite(sample, test_db)
        self.assertEqual(saved_count, 1)
        # Duplicate test
        dup_count = save_trades_to_sqlite(sample, test_db)
        self.assertEqual(dup_count, 0)
        # Export parquet
        exported = export_recent_trades_to_parquet(days=7, db_path=test_db, parquet_path=test_parquet)
        self.assertEqual(exported, 1)
        # Verify with duckdb
        res = duckdb.query(f"SELECT COUNT(*) FROM '{test_parquet}'").fetchone()[0]
        self.assertEqual(res, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests/test_storage.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.storage'`

- [ ] **Step 3: Implement `src/storage.py`**

Implement `init_db`, `generate_trade_id`, `save_trades_to_sqlite`, and `export_recent_trades_to_parquet`.
Include cleanup of test files in tearDown.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests/test_storage.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/storage.py tests/test_storage.py
git commit -m "feat: SQLite 마스터 DB 적재 및 Parquet 스냅샷 추출 스토리지 모듈 구현"
```

---

### Task 3: 국토교통부 Open API 수집 파이프라인 구현

**Files:**
- Create: `src/fetch_api.py`
- Test: `tests/test_fetch_api.py`

**Interfaces:**
- Consumes: `src/storage.py` (`save_trades_to_sqlite`, `export_recent_trades_to_parquet`), `src/constants.py` (`SGG_CODE_MAP`)
- Produces:
  - `parse_xml_response(xml_text: str) -> list[dict]`: XML 응답을 딕셔너리 리스트로 변환 및 해제 거래(`cdealType == 'O'`) 필터링
  - `get_target_months(reference_date: date, days_ago: int = 7) -> list[str]`: 수집 대상 YYYYMM 목록 반환
  - `fetch_sgg_trades_async(client: httpx.AsyncClient, sgg_cd: str, deal_ymd: str, api_key: str) -> list[dict]`: 특정 시군구/월 비동기 수집
  - `run_pipeline(api_key: str | None = None, days_ago: int = 7, target_sggs: list[str] | None = None) -> dict`: 전체 수집 및 저장 실행

- [ ] **Step 1: Write the failing test for API fetching & XML parsing**

```python
# tests/test_fetch_api.py
import unittest
from datetime import date
from src.fetch_api import parse_xml_response, get_target_months

class TestFetchApi(unittest.TestCase):
    def test_parse_xml_filters_cancelled_trades(self) -> None:
        xml_sample = """<?xml version="1.0" encoding="UTF-8"?>
        <response>
            <header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
            <body>
                <items>
                    <item>
                        <sggCd>11110</sggCd><aptNm>종로센트레빌</aptNm><dealAmount>120,000</dealAmount>
                        <dealYear>2026</dealYear><dealMonth>10</dealMonth><dealDay>02</dealDay>
                        <excluUseAr>84.9</excluUseAr><floor>5</floor><cdealType></cdealType>
                    </item>
                    <item>
                        <sggCd>11110</sggCd><aptNm>해제아파트</aptNm><dealAmount>90,000</dealAmount>
                        <dealYear>2026</dealYear><dealMonth>10</dealMonth><dealDay>01</dealDay>
                        <excluUseAr>59.9</excluUseAr><floor>3</floor><cdealType>O</cdealType>
                    </item>
                </items>
            </body>
        </response>"""
        items = parse_xml_response(xml_sample)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["aptNm"], "종로센트레빌")

    def test_target_months_month_start(self) -> None:
        # Month start (e.g. 2026-10-03) should return both 202609 and 202610
        months = get_target_months(date(2026, 10, 3), days_ago=7)
        self.assertEqual(months, ["202609", "202610"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests/test_fetch_api.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.fetch_api'`

- [ ] **Step 3: Implement `src/fetch_api.py`**

Implement XML parsing with `xml.etree.ElementTree`, month boundary calculation, async HTTP fetching with semaphore concurrency control, and `run_pipeline`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests/test_fetch_api.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fetch_api.py tests/test_fetch_api.py
git commit -m "feat: 국토교통부 Open API 비동기 수집 파이프라인 및 XML 파서 구현"
```

---

### Task 4: DuckDB 기반 고속 분석 쿼리 엔진 구현

**Files:**
- Create: `src/db_queries.py`
- Test: `tests/test_queries.py`

**Interfaces:**
- Consumes: Parquet 스냅샷 (`data/processed/recent_trades.parquet`)
- Produces:
  - `get_kpi_summary(con: duckdb.DuckDBPyConnection, parquet_path: str, filters: dict) -> dict`: 거래량, 최고가, 평균 평당가 등 집계
  - `get_sido_distribution(con: duckdb.DuckDBPyConnection, parquet_path: str, filters: dict) -> pd.DataFrame`: 시도별 거래량 및 평당가
  - `get_daily_trend(con: duckdb.DuckDBPyConnection, parquet_path: str, filters: dict) -> pd.DataFrame`: 일자별 거래량 추이
  - `get_top_rankings(con: duckdb.DuckDBPyConnection, parquet_path: str, rank_type: str, limit: int = 10) -> pd.DataFrame`: 랭킹 테이블
  - `get_price_alerts(con: duckdb.DuckDBPyConnection, parquet_path: str) -> pd.DataFrame`: 신고가 및 특이 거래 탐지
  - `search_trades(con: duckdb.DuckDBPyConnection, parquet_path: str, filters: dict, limit: int = 100) -> pd.DataFrame`: 검색 테이블

- [ ] **Step 1: Write the failing test for DuckDB queries**

```python
# tests/test_queries.py
import unittest
import duckdb
import pandas as pd
from pathlib import Path
from src.db_queries import get_kpi_summary, get_sido_distribution, search_trades

class TestDuckDBQueries(unittest.TestCase):
    def setUp(self) -> None:
        self.con = duckdb.connect()
        self.parquet_path = "data/processed/test_query_data.parquet"
        df = pd.DataFrame([{
            "sido_nm": "서울특별시", "sgg_nm": "강남구", "apt_nm": "은마",
            "deal_date": "2026-10-03", "deal_amount": 280000, "price_per_pyeong": 10900.0,
            "pyeong": 25.6, "exclu_use_ar": 84.4, "floor": 7, "dealing_gbn": "중개거래"
        }])
        df.to_parquet(self.parquet_path)

    def tearDown(self) -> None:
        p = Path(self.parquet_path)
        if p.exists():
            p.unlink()

    def test_kpi_summary(self) -> None:
        kpi = get_kpi_summary(self.con, self.parquet_path, {})
        self.assertEqual(kpi["total_trades"], 1)
        self.assertEqual(kpi["max_price"], 280000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests/test_queries.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.db_queries'`

- [ ] **Step 3: Implement `src/db_queries.py`**

Implement DuckDB query functions utilizing vectorized operations and parameter-safe filtering.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests/test_queries.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db_queries.py tests/test_queries.py
git commit -m "feat: DuckDB 기반 인메모리 OLAP 분석 쿼리 모듈 구현"
```

---

### Task 5: Streamlit 반응형 대시보드 UI 구현

**Files:**
- Create: `app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `src/db_queries.py`, `src/constants.py`, `data/processed/recent_trades.parquet`
- Produces:
  - Streamlit 메인 대시보드 웹 애플리케이션
  - 사이드바 글로벌 필터 (기간, 시도/시군구, 평형, 가격, 거래유형)
  - 4대 탭: 전국 실거래 현황, 지역 & 단지 랭킹, 신고가/급매 탐지, 데이터 탐색기 & CSV 다운로드

- [ ] **Step 1: Write test to verify app imports and module integrity**

```python
# tests/test_app.py
import unittest
import importlib

class TestApp(unittest.TestCase):
    def test_app_importable(self) -> None:
        # Verify app syntax and imports without crashing
        spec = importlib.util.find_spec("app")
        self.assertIsNotNone(spec)
```

- [ ] **Step 2: Run test to verify it fails before app.py is created**

Run: `uv run python -m unittest tests/test_app.py`
Expected: FAIL with `spec is None`

- [ ] **Step 3: Implement `app.py`**

Implement full Streamlit application:
- Wide layout, theme configuration, clean metrics cards.
- DuckDB connection initialization with `@st.cache_resource`.
- Plotly interactive charts for market overview and rankings.
- 4 Tabs rendering data cleanly with fallback messages when data is empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests/test_app.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: Streamlit 4대 탭 반응형 아파트 실거래가 대시보드 UI 구현"
```

---

### Task 6: GitHub Actions 자동화 워크플로 및 실행 스크립트 통합

**Files:**
- Create: `.github/workflows/daily_fetch.yml`
- Modify: `src/main.py`
- Modify: `README.md`
- Modify: `docs/plan.md`

**Interfaces:**
- Consumes: GitHub Secrets `DATA_GO_KR_API_KEY`
- Produces:
  - 매일 06:00 KST Cron 자동 실행 및 Parquet 갱신
  - `src/main.py` CLI 원클릭 수집 및 대시보드 실행 보조

- [ ] **Step 1: Create `.github/workflows/daily_fetch.yml`**

Define workflow with cron `0 21 * * *` (UTC), `workflow_dispatch`, `astral-sh/setup-uv@v5`, `uv run python src/fetch_api.py`, and conditional Git commit & push.

- [ ] **Step 2: Update `src/main.py` to support `--fetch` and `--serve` CLI arguments**

Allow running data collection or launching streamlit directly from `src/main.py`.

- [ ] **Step 3: Update documentation (`README.md`, `docs/plan.md`)**

Document deployment instructions for Streamlit Community Cloud and GitHub Actions setup.

- [ ] **Step 4: Run all unit tests to ensure zero regressions**

Run: `uv run python -m unittest discover tests`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/daily_fetch.yml src/main.py README.md docs/plan.md
git commit -m "feat: GitHub Actions 매일 자동 수집 워크플로 및 통합 진입점 구성"
```

---

### Task 7: E2E 실제 Open API 수집 및 Streamlit 대시보드 검증

**Files:**
- Output: `data/processed/apt_trades.db`, `data/processed/recent_trades.parquet`
- Modify: `reports/report.md`

**Interfaces:**
- Consumes: `.env`의 `DATA_GO_KR_API_KEY`
- Produces:
  - 실제 국토교통부 아파트 매매 실거래가 데이터 적재 및 Parquet 생성
  - 대시보드 정상 렌더링 확인 및 분석 요약 보고서 업데이트

- [ ] **Step 1: Run real collection pipeline with API key**

Run: `uv run python src/main.py --fetch --days 7 --sample` (서울 등 주요 시군구 우선 실데이터 수집)
Expected: Data successfully fetched, inserted into `apt_trades.db`, and exported to `recent_trades.parquet`.

- [ ] **Step 2: Verify DuckDB query on generated Parquet**

Run: `uv run python -c "import duckdb; print(duckdb.query('SELECT COUNT(*), MIN(deal_date), MAX(deal_date) FROM \'data/processed/recent_trades.parquet\'').df())"`
Expected: Output shows valid trade counts and date ranges.

- [ ] **Step 3: Update `reports/report.md` with initial findings**

Document collection stats (total records, price ranges, major regions).

- [ ] **Step 4: Commit**

```bash
git add reports/report.md
git commit -m "feat: 실제 국토부 실거래가 데이터 수집 검증 및 결과 보고서 업데이트"
```
