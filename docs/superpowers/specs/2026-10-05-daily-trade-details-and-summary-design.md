# 일자별 아파트 실거래가 상세 조회 페이지 및 SQLite 요약 관리 시스템 설계서

## 1. 개요 (Overview)

본 문서는 국토교통부 아파트 매매 실거래가 시스템에 특정 일자의 거래 상세 내역을 심층 조회할 수 있는 전용 페이지(`pages/1_📅_일자별_거래내역.py`)를 신설하고, SQLite 데이터베이스에 일자별 핵심 통계를 영구 관리하는 요약 테이블(`daily_trade_summary`)을 구축하기 위한 아키텍처 및 구현 명세서입니다.

- **작성일자**: 2026-10-05
- **상태**: 승인됨 (Approved)
- **대상 저장소**: `apt-info`

---

## 2. 요구사항 및 목표 (Requirements & Goals)

### 2.1 기능적 요구사항
1. **별도 페이지 구성**:
   - Streamlit의 표준 멀티페이지 구조(`pages/` 디렉토리)를 활용하여 메인 대시보드와 독립된 상세 조회 페이지(`pages/1_📅_일자별_거래내역.py`)를 제공합니다.
2. **일자별 요약 내용 SQLite 영구 관리**:
   - SQLite DB(`data/processed/apt_trades.db`)에 `daily_trade_summary` 테이블을 생성하여 일자별 거래건수, 총 거래대금, 평균가, 평당 평균가, 최고 거래금액, 최고가 아파트명, 직거래 비율 등을 영구 저장하고 고속 조회합니다.
   - 데이터 적재 시점 및 사용자 수동 요청 시 요약 데이터를 동기화할 수 있는 파이프라인 함수를 제공합니다.
3. **일자별 상세페이지 조회 UX**:
   - **일자 선택**: 실제 거래가 존재하는 날짜 목록 드롭다운, 캘린더 피커, 최근 거래일 퀵 버튼(칩) 제공.
   - **핵심 KPI 요약 카드**: 당일 총 거래건수, 총 거래대금, 평균 거래가, 평당 평균가, 최고가 단지 5대 지표 표출.
   - **시각화 차트**: 시도별 거래 건수 및 평균가(막대 차트), 가격대별 거래 분포(도넛 차트).
   - **상세 거래 그리드 & 필터**: 당일 발생한 전체 실거래 목록을 지역(시도/시군구), 단지명, 금액대로 필터링하고 CSV로 다운로드할 수 있는 데이터프레임 인터페이스 제공.

### 2.2 비기능적 요구사항
- **응답 속도**: 날짜 변경 시 0.1초 이내에 상단 KPI 및 차트 렌더링 (사전 집계된 `daily_trade_summary` 테이블 활용).
- **데이터 무결성**: SQLite 트랜잭션 격리를 통해 요약 갱신 시 원자성 보장.
- **예외 처리**: 미수집 일자나 거래가 없는 일자 선택 시 명확하고 친절한 안내 메시지 표시.
- **코드 문서화 규칙 준수**: 모든 신규 Python 코드 및 모듈에 한국어 Google Style Docstring, 타입 힌트, 상대 경로 적용.

---

## 3. 데이터베이스 아키텍처 (Database Architecture)

### 3.1 테이블 스키마: `daily_trade_summary`

```sql
CREATE TABLE IF NOT EXISTS daily_trade_summary (
    deal_date TEXT PRIMARY KEY,          -- 계약일자 (YYYY-MM-DD)
    total_trades INTEGER NOT NULL,      -- 당일 총 거래 건수
    total_amount INTEGER NOT NULL,      -- 당일 총 거래대금 (만원 단위)
    avg_amount REAL NOT NULL,           -- 건당 평균 거래금액 (만원 단위)
    avg_price_per_pyeong REAL NOT NULL, -- 평균 평당 거래가격 (만원 단위)
    max_amount INTEGER NOT NULL,        -- 당일 최고 거래가 (만원 단위)
    max_apt_name TEXT,                  -- 당일 최고 거래가 아파트명
    max_sgg_nm TEXT,                    -- 당일 최고 거래가 시군구명
    direct_deal_count INTEGER NOT NULL, -- 직거래 건수
    broker_deal_count INTEGER NOT NULL, -- 중개거래 건수
    updated_at TEXT NOT NULL            -- 요약 생성/갱신 일시 (ISO-8601)
);

CREATE INDEX IF NOT EXISTS idx_summary_date ON daily_trade_summary(deal_date DESC);
```

### 3.2 데이터 수명 주기 및 동기화 파이프라인
1. `init_db()`: `daily_trade_summary` 테이블 및 인덱스 자동 생성.
2. `sync_daily_summary(db_path=None, target_date=None) -> int`:
   - `apt_trades` 원본 테이블로부터 `deal_date`별 집계 쿼리를 실행하여 `INSERT OR REPLACE` (Upsert).
   - `target_date` 파라미터로 특정 일자만 부분 갱신하거나 전체 일자 일괄 갱신 지원.
3. `save_trades_to_sqlite()`:
   - 신규 거래 데이터 적재 완료 직후 `sync_daily_summary()`를 내부 자동 호출하여 실시간 동기화 유지.

---

## 4. 모듈 및 비즈니스 로직 설계 (Component Design)

### 4.1 스토리지 모듈 ([src/storage.py](file:///c:/Users/ryanm/OneDrive/문서/antigravity/eda/apt-info/src/storage.py))
- `init_db()`: 스키마 정의 확장.
- `sync_daily_summary()`: 원본 `apt_trades` 기반 집계 및 Upsert 로직 구현.
- `get_daily_summary_records(db_path=None) -> pd.DataFrame`: 요약 테이블 전체를 조회하여 데이터프레임으로 반환.

### 4.2 쿼리 모듈 ([src/db_queries.py](file:///c:/Users/ryanm/OneDrive/문서/antigravity/eda/apt-info/src/db_queries.py))
- `get_available_deal_dates(db_path=None) -> list[str]`: 거래 데이터가 존재하는 일자 리스트를 최신순으로 반환.
- `get_single_day_summary(deal_date: str, db_path=None) -> Optional[dict]`: 특정 일자의 요약 레코드 1건 반환.
- `get_trades_by_date(deal_date: str, sido_filter: Optional[str] = None, sgg_filter: Optional[str] = None, min_amount: Optional[int] = None, max_amount: Optional[int] = None, apt_search: Optional[str] = None, db_path=None) -> pd.DataFrame`: 특정 일자의 상세 거래 내역 필터링 조회.
- `get_day_region_distribution(deal_date: str, db_path=None) -> pd.DataFrame`: 해당 일자의 시도별 거래 건수 및 평균 거래가 집계.
- `get_day_price_bands(deal_date: str, db_path=None) -> pd.DataFrame`: 해당 일자의 5단계 금액대별 거래 비중 집계.

### 4.3 신규 페이지 모듈 (`pages/1_📅_일자별_거래내역.py`)
- **페이지 설정**: `st.set_page_config(page_title="일자별 아파트 실거래가 상세", page_icon="📅", layout="wide")`
- **상단 인터랙션 바**:
  - 최근 거래일 5개 퀵 버튼 (클릭 시 `st.session_state.selected_deal_date` 갱신)
  - 날짜 선택기(Date Picker / Selectbox)
  - 동기화 버튼(`🔄 요약 갱신`)
- **KPI 지표 영역**:
  - `st.columns(5)`를 활용한 5대 카드 (총 거래건수, 총 대금, 평균가, 평당가, 최고가 단지)
- **시각화 영역**:
  - 좌측: 시도별 거래량 및 평균가 복합 막대 차트 (Plotly)
  - 우측: 가격대별 분포 도넛 차트 (Plotly)
- **상세 거래 그리드 & 필터 영역**:
  - 시도, 시군구, 단지명 검색, 금액 범위 슬라이더
  - 정렬 및 스타일링된 `st.dataframe` 표출
  - CSV 다운로드 버튼(`st.download_button`)

---

## 5. 예외 처리 및 방어적 프로그래밍 (Error Handling)

1. **데이터 부재 시 안내**:
   - `apt_trades.db`가 아예 없거나 데이터가 비어 있을 경우: `st.warning("수집된 실거래가 데이터가 없습니다. 메인 페이지에서 데이터를 먼저 수집해 주세요.")` 출력.
   - 선택한 일자에 거래가 0건인 경우: `st.info("해당 일자에는 등록된 아파트 매매 실거래 내역이 없습니다.")` 표출.
2. **분모 0 오류 방지**:
   - 집계 시 `COUNT = 0`인 경우 평균가 계산에서 발생할 수 있는 `ZeroDivisionError` 방어.
3. **트랜잭션 안전성**:
   - SQLite `sync_daily_summary` 작업 도중 오류 발생 시 자동 롤백 적용.

---

## 6. 테스트 및 검증 계획 (Testing & Verification)

### 6.1 단위 테스트 (`tests/test_daily_summary.py`)
- `test_init_db_creates_summary_table`: 테이블 및 인덱스 생성 확인.
- `test_sync_daily_summary_aggregation`: 원본 데이터로부터 건수, 총액, 최고가, 평당가 올바른 계산 검증.
- `test_get_available_deal_dates`: 최신순 정렬 반환 확인.
- `test_get_trades_by_date_filtering`: 특정 날짜 및 시도/단지명 필터링 정확성 검증.

### 6.2 E2E 및 UI 검증
- Streamlit 대시보드 로컬 실행 후 `pages/1_📅_일자별_거래내역.py` 렌더링 확인.
- 날짜 전환 시 반응 속도 및 데이터 일치 여부 확인.
- CSV 다운로드 기능 검증.
