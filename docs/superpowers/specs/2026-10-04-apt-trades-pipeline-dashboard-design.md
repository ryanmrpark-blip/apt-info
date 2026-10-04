# 설계 명세서: 국토교통부 전국 아파트 매매 실거래가 수집 및 Streamlit 대시보드

- **작성일시**: 2026-10-04
- **프로젝트**: `apt-info`
- **상태**: 승인됨 (Approved)

---

## 1. 개요 및 목적

본 프로젝트는 공공데이터포털의 **국토교통부 아파트 매매 실거래가 Open API**를 활용하여 **최근 1주일간의 전국 아파트 실거래 데이터**를 매일 자동으로 수집·적재하고, 이를 **Streamlit 기반 반응형 대시보드**로 시각화하여 무료 클라우드 환경(GitHub Actions + Streamlit Community Cloud)에 안정적으로 배포·운영하는 데이터 파이프라인 및 대시보드 시스템을 구축하는 것을 목적으로 합니다.

### 핵심 기술 스택 및 데이터 흐름
- **수집 (ETL)**: Python `httpx` 비동기/배치 통신 기반 Open API 수집
- **마스터 DB**: `SQLite` (트랜잭션 정합성 보장, 중복 거래 방지 Upsert 및 전체 누적 관리)
- **배포 스토리지**: `Parquet` (최근 7일/전체 데이터 Snappy 고압축 스냅샷, Git 커밋 최적화)
- **분석/서빙 엔진**: `DuckDB` (Streamlit 내에서 Parquet 파일을 인메모리 OLAP SQL로 초고속 쿼리)
- **시각화 (UI)**: `Streamlit` + `Plotly` 인터랙티브 차트 및 탐색 테이블
- **자동화/배포**: `GitHub Actions` (매일 06:00 KST Cron 실행) + `Streamlit Community Cloud`

---

## 2. 전체 디렉토리 및 모듈 구조

```text
apt-info/
├── .github/
│   └── workflows/
│       └── daily_fetch.yml            # 매일 자동 수집 및 Parquet 갱신 GitHub Actions
├── data/
│   ├── raw/
│   │   ├── sgg_codes.json             # 전국 250개 시군구 5자리 법정동 코드 매핑 테이블
│   │   └── .gitkeep
│   └── processed/
│       ├── apt_trades.db              # [SQLite] 실거래가 마스터 DB (중복 방지 Upsert)
│       ├── recent_trades.parquet      # [Parquet] 최근 7일 실거래가 초경량 스냅샷
│       └── .gitkeep
├── docs/
│   ├── overview.md
│   ├── plan.md
│   └── superpowers/specs/
│       └── 2026-10-04-apt-trades-pipeline-dashboard-design.md
├── reports/
│   ├── figures/
│   └── report.md
├── src/
│   ├── __init__.py
│   ├── constants.py                   # 시도/시군구 코드 및 공통 상수 정의
│   ├── utils.py                       # 상대 경로 탐색 및 디렉토리 관리 유틸리티
│   ├── fetch_api.py                   # 국토교통부 Open API 수집 파이프라인
│   ├── storage.py                     # SQLite 적재 & Parquet 추출 모듈
│   └── db_queries.py                  # DuckDB 기반 분석 SQL 헬퍼 (집계, 랭킹, 필터링)
├── tests/
│   ├── __init__.py
│   ├── test_utils.py                  # 유틸리티 단위 테스트
│   ├── test_storage.py                # SQLite 및 Parquet 저장소 단위 테스트
│   └── test_queries.py                # DuckDB 쿼리 엔진 단위 테스트
├── app.py                             # Streamlit 대시보드 메인 애플리케이션
├── pyproject.toml                     # uv 패키지 메타데이터 및 의존성 명세
├── README.md
└── .gitignore
```

---

## 3. 데이터 수집 파이프라인 명세 (`src/fetch_api.py`)

### 3.1 Open API 엔드포인트 및 호출 규칙
- **API 명**: 국토교통부_아파트 매매 실거래가 자료
- **엔드포인트**: `https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade`
- **필수 요청 파라미터**:
  - `serviceKey`: 공공데이터포털 발급 일반 인증키 (`.env` 또는 GitHub Secrets `DATA_GO_KR_API_KEY`)
  - `LAWD_CD`: 5자리 지역코드 (예: 서울 종로구 `11110`, 강남구 `11680` 등 전국 250개 시군구)
  - `DEAL_YMD`: 계약년월 6자리 (`YYYYMM`)
  - `numOfRows`: 1000 (시군구/월별 최대 거래량 수용)
  - `pageNo`: 1

### 3.2 수집 대상 기간 및 월 전환 로직
- 기준 시점: 실행일자(당일) 기준 최근 7일 (`today - 7일` ~ `today`)
- **월 경계 처리**:
  - 실행일자가 해당 월의 1~7일 사이인 경우, 최근 7일 데이터가 전월에 걸치므로 `전월(YYYYMM)`과 `당월(YYYYMM)` 2개 월을 모두 조회
  - 그 외의 경우 `당월(YYYYMM)` 1개 월만 조회
- **계약 취소(해제) 거래 필터링**:
  - 응답 필드 중 `cdealType == 'O'`(해제된 거래)는 정상 유효 거래가 아니므로 수집 단계에서 즉시 제외

### 3.3 비동기/배치 병렬 처리
- 전국 250개 시군구를 순차 호출할 경우 1~2초씩 소요되어 총 수분이 걸리므로, `httpx.AsyncClient` 또는 동시성 세마포어(예: 동시 요청 수 10개 제한)를 적용하여 약 1분 이내에 250개 시군구 조회를 안정적으로 완료합니다.

---

## 4. 3단계 스토리지 아키텍처 (SQLite + Parquet + DuckDB)

### 4.1 1단계: SQLite 마스터 DB (`data/processed/apt_trades.db`)
- **역할**: 매일 수집되는 데이터의 중복 적재를 원천 방지하고 장기 히스토리를 누적 관리
- **테이블 스키마**:
```sql
CREATE TABLE IF NOT EXISTS apt_trades (
    trade_id TEXT PRIMARY KEY,        -- sgg_cd + '_' + deal_date + '_' + apt_nm + '_' + exclu_use_ar + '_' + floor + '_' + deal_amount 고유 해시
    sgg_cd TEXT NOT NULL,             -- 시군구 코드 (5자리)
    sido_nm TEXT NOT NULL,            -- 시도명 (예: 서울특별시, 경기도 등)
    sgg_nm TEXT NOT NULL,             -- 시군구명 (예: 강남구, 분당구 등)
    umd_nm TEXT NOT NULL,             -- 법정동명 (예: 대치동)
    apt_nm TEXT NOT NULL,             -- 아파트 단지명
    jibun TEXT,                       -- 지번
    exclu_use_ar REAL NOT NULL,       -- 전용면적 (㎡)
    pyeong REAL NOT NULL,             -- 평형 (exclu_use_ar / 3.30578)
    deal_year INTEGER NOT NULL,       -- 계약년도 (YYYY)
    deal_month INTEGER NOT NULL,      -- 계약월 (MM)
    deal_day INTEGER NOT NULL,        -- 계약일 (DD)
    deal_date TEXT NOT NULL,          -- 계약일자 전체 (YYYY-MM-DD)
    deal_amount INTEGER NOT NULL,     -- 거래금액 (만원)
    price_per_pyeong REAL NOT NULL,   -- 평당 가격 (만원/평 = deal_amount / pyeong)
    floor INTEGER,                    -- 층
    build_year INTEGER,               -- 건축년도
    dealing_gbn TEXT,                 -- 거래유형 (중개거래, 직거래)
    estate_agent_sgg_nm TEXT,         -- 중개사 소재지
    rgst_date TEXT,                   -- 등기일자
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_deal_date ON apt_trades(deal_date);
CREATE INDEX IF NOT EXISTS idx_sido_sgg ON apt_trades(sido_nm, sgg_nm);
CREATE INDEX IF NOT EXISTS idx_apt_name ON apt_trades(apt_nm);
```
- **Upsert 원칙**: `INSERT OR IGNORE INTO apt_trades ...`를 통해 이미 수집된 거래건은 중복 없이 스킵

### 4.2 2단계: Parquet 배포 스냅샷 (`data/processed/recent_trades.parquet`)
- **역할**: GitHub 저장소에 커밋되어 Streamlit Cloud 무료 서버로 배포되는 초경량 분석용 파일
- **생성 로직**:
  - SQLite 마스터 DB에서 최근 7일치(필요시 최근 30일치) 데이터를 추출
  - `pyarrow` 엔진 기반 Snappy 압축 적용 (약 2~5MB 내외로 압축)
  - GitHub 파일 용량 제한(100MB) 및 Streamlit 메모리 제한(1GB)을 전혀 침범하지 않음

### 4.3 3단계: DuckDB 인메모리 OLAP 쿼리 엔진 (`src/db_queries.py`)
- **역할**: Streamlit 애플리케이션 기동 시 Parquet 파일을 즉시 쿼리하여 밀리초(ms) 단위로 필터링 및 집계 수행
- **주요 쿼리 기능**:
  1. `get_kpi_metrics(start_date, end_date, sgg_filter)`: 총 거래건수, 최고 거래가 단지/금액, 전국 평균 평당가
  2. `get_sido_distribution(...)`: 시도별 거래량 및 평균 평당가 집계
  3. `get_top_rankings(rank_type='volume'|'price'|'pyeong')`: 거래량/거래가/평당가 Top 10 시군구 및 단지
  4. `get_new_highs_and_drops(...)`: 단지별 과거 최고가 대비 신고가 경신 및 급매 거래 탐지
  5. `search_trades(...)`: 다중 조건(지역, 면적, 가격대, 단지명) 필터링 검색

---

## 5. Streamlit 대시보드 UI 명세 (`app.py`)

### 5.1 페이지 레이아웃
- `st.set_page_config(page_title="전국 아파트 실거래가 대시보드", layout="wide", page_icon="🏢")`
- 모던 프리미엄 다크/라이트 하모니 스타일링 적용

### 5.2 사이드바 글로벌 필터
- **조회 기간 슬라이더/피커**: 최근 7일 범위 내 시작일/종료일 선택
- **시도 선택 (멀티셀렉트)**: 서울특별시, 경기도, 인천광역시 등 전국 17개 시도 선택
- **시군구 선택 (멀티셀렉트)**: 선택된 시도에 종속되어 동적으로 목록 갱신
- **평형대 필터**: 전체 / ~20평형 / 20~30평형 / 30~40평형 / 40평형 이상
- **거래 금액 범위 슬라이더**: 5천만원 ~ 50억원
- **거래 유형**: 전체 / 중개거래 / 직거래

### 5.3 메인 화면 4대 탭 구조

1. **📊 탭 1: 전국 실거래 현황 (Market Overview)**
   - 최상단 핵심 KPI 카드 4종 (`총 거래량`, `최고 거래가`, `전국 평균 평당가`, `일평균 거래량`)
   - 시도별 거래량 & 평균 평당가 듀얼 축 바/라인 차트 (Plotly)
   - 최근 7일간 일별 거래량 변동 추이 에어리어 차트

2. **🏆 탭 2: 지역 및 단지 랭킹 (Top Rankings)**
   - 최근 7일 최다 거래 시군구 Top 10 (수평 바 차트)
   - 거래금액 최고가 아파트 Top 10 (단지명, 거래일, 층, 전용면적, 거래금액)
   - 평당 가격 최고가 아파트 Top 10

3. **🔍 탭 3: 신고가 및 이상 거래 모니터링 (Price Alerts)**
   - 직전 거래 대비 가격 상승률이 높거나 신고가를 기록한 단지 목록
   - 시세 대비 대폭 하락 또는 직거래 체결된 급매 의심 거래 목록
   - 전용면적별 가격 분포 박스플롯(Box Plot)

4. **📋 탭 4: 상세 실거래가 데이터 탐색기 (Data Explorer)**
   - DuckDB 기반 고속 필터링 데이터테이블 (페이지네이션 지원)
   - 컬럼 정렬 기능 (거래일자순, 거래금액순, 평당가순)
   - 필터링된 전체 결과 **CSV 다운로드 버튼**

---

## 6. GitHub Actions 자동화 및 Streamlit Cloud 배포 전략

### 6.1 GitHub Actions 워크플로 (`.github/workflows/daily_fetch.yml`)
- **트리거**:
  - `schedule`: 매일 UTC 21:00 (한국 시간 새벽 06:00)
  - `workflow_dispatch`: GitHub 웹 콘솔에서 수동 즉시 실행 지원
- **환경 변수 및 시크릿**:
  - `DATA_GO_KR_API_KEY`: GitHub Repository Secrets에 등록
- **실행 단계**:
  1. 저장소 체크아웃 (`actions/checkout@v4`)
  2. Python 3.12 및 `uv` 설치 (`astral-sh/setup-uv@v5`)
  3. 의존성 동기화 (`uv sync`)
  4. 수집 및 저장 파이프라인 실행 (`uv run python src/fetch_api.py`)
  5. 변경 파일 검사 (`git status --porcelain`) 후 `apt_trades.db` 및 `recent_trades.parquet` 자동 커밋 & 푸시

### 6.2 Streamlit Community Cloud 배포
- 무료 계정으로 GitHub 저장소 직접 연결
- 메인 파일: `app.py`
- Git push 발생 시 자동 빌드 및 실시간 배포 갱신
- Parquet 스냅샷만 읽으므로 초기 로딩 속도 1초 미만 보장

---

## 7. 검증 및 테스트 계획

1. **단위 테스트**:
   - `test_storage.py`: SQLite 테이블 생성, 중복 복합키 거래 Upsert 무시 검증, Parquet 변환 및 읽기 유효성 검증
   - `test_queries.py`: DuckDB SQL 쿼리 결과(집계 수치, 평당가 계산, 랭킹 로직) 정확성 검증
2. **Mock API 수집 테스트**:
   - 공공데이터포털 응답 XML을 가상 모킹하여 파싱, 타입 변환, 해제 거래 필터링 검증
3. **E2E 통합 테스트**:
   - 실제 API 키를 통한 1개 대표 지역(예: 서울 강남구 11680) 실거래가 수집 -> SQLite 저장 -> Parquet 생성 -> Streamlit 기동 상태 확인
