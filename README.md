# apt-info: 전국 아파트 매매 실거래가 수집 & 대시보드 파이프라인

국토교통부 아파트 매매 실거래가 Open API를 활용하여 최근 7일간의 전국 실거래가를 비동기 수집하고, SQLite 마스터 DB와 Parquet 스냅샷에 저장한 뒤 DuckDB와 Streamlit으로 인터랙티브 대시보드를 제공하는 완전 자동화 프로젝트입니다.

---

## 🌟 주요 특징

1. **국토교통부 Open API 비동기 고속 수집**:
   - `httpx.AsyncClient` 기반 동시성 제어(`asyncio.Semaphore`)로 전국 250개 시군구 데이터를 수 초 내 안전하게 수집.
   - 월 경계(매월 1~7일) 자동 감지하여 이전 달과 당월 데이터를 동시 취합.
   - 거래 취소 건(`cdealType == 'O'`) 자동 필터링 및 거래금액 정수화(`만원 단위`).
2. **SQLite + Parquet + DuckDB 3계층 데이터 아키텍처**:
   - **SQLite**: 중복 없는 고유 거래 ID 기반 영구 마스터 데이터베이스 (`apt_trades`) 및 일자별 핵심 통계 영구 관리 테이블(`daily_trade_summary`).
   - **Parquet**: Streamlit 및 GitHub 무료 배포에 최적화된 Snappy 압축 컬럼형 스냅샷 (초경량).
   - **DuckDB**: 브라우저/서버 메모리 상에서 Parquet 파일을 직접 SQL 쿼리하는 초고속 OLAP 분석 엔진.
3. **Streamlit 멀티페이지 반응형 대시보드**:
   - **종합 대시보드 (`app.py`)**: 4대 탭(전국 실거래 현황, 지역 & 단지 랭킹, 신고가 및 특이 거래, 실거래가 상세 탐색기).
   - **일자별 상세 조회 전용 페이지 (`pages/1_📅_일자별_거래내역.py`)**: 특정 일자 선택 시 5대 KPI 카드(거래량, 대금, 평균가, 평당가, 최고가 단지), 시도별 거래량/평균가 막대 차트, 가격대별 도넛 차트, 다차원 필터링 그리드 및 CSV 내보내기.
4. **GitHub Actions & Streamlit Cloud 무료 자동 배포**:
   - 매일 한국 시간 06:00 (UTC 21:00) GitHub Actions Cron 실행 -> 최신 7일 데이터 수집 -> `recent_trades.parquet` 자동 커밋 & 푸시.
   - Streamlit Community Cloud가 저장소 변경을 감지하여 대시보드 자동 갱신.

---

## 📁 디렉토리 구조

```text
apt-info/
├── .github/
│   └── workflows/
│       └── daily_fetch.yml        # GitHub Actions 매일 06:00 자동 수집 워크플로
├── .venv/                         # uv 기반 Python 가상환경
├── data/
│   ├── raw/
│   │   └── sgg_codes.json         # 전국 250개 시군구 법정동 코드 매핑 테이블
│   └── processed/
│       ├── apt_trades.db          # SQLite 영구 마스터 DB & 일자별 요약 테이블 (로컬 보관)
│       └── recent_trades.parquet  # 최근 7일 실거래가 스냅샷 (GitHub 배포 대상)
├── docs/                          # 프로젝트 설계 명세서 및 구현 계획서
├── pages/
│   └── 1_📅_일자별_거래내역.py   # Streamlit 일자별 상세 실거래 조회 전용 페이지
├── reports/
│   ├── figures/                   # 분석 차트 이미지
│   └── report.md                  # 실거래가 데이터 EDA 종합 분석 보고서
├── src/
│   ├── __init__.py                # 패키지 초기화
│   ├── constants.py               # 시도/시군구 코드 매핑 및 유틸
│   ├── db_queries.py              # DuckDB OLAP 분석 및 일자별 SQLite 쿼리 모듈
│   ├── fetch_api.py               # 국토교통부 Open API 비동기 수집 파이프라인
│   ├── main.py                    # 통합 CLI 실행 진입점
│   ├── storage.py                 # SQLite 적재, 일자별 요약 동기화 및 Parquet 스냅샷 모듈
│   └── utils.py                   # 경로 계산 및 공통 유틸리티
├── tests/                         # 단위 테스트 스위트 (총 34개 테스트)
├── app.py                         # Streamlit 대시보드 메인 웹 애플리케이션
├── pyproject.toml                 # uv 패키지 메타데이터 및 의존성 설정
├── .env.example                   # 환경 변수 템플릿
├── README.md                      # 프로젝트 사용 안내서
└── .gitignore                     # Git 제외 설정 (.env, sqlite 등 보안/용량 제외)
```

---

## 🚀 빠른 시작 (Quick Start)

본 프로젝트는 **`uv`** 패키지 관리자를 사용하여 가상환경 및 의존성을 관리합니다.

### 1. 가상환경 동기화
```bash
# apt-info 프로젝트 디렉토리로 이동
cd apt-info

# uv를 통한 가상환경 및 의존성 동기화
uv sync
```

### 2. API 키 설정 (`.env`)
공공데이터포털([data.go.kr](https://www.data.go.kr/data/15126469/openapi.do))에서 발급받은 '국토교통부_아파트매매 실거래자료' 일반 인증키(Encoding 또는 Decoding 키)를 설정합니다.

```bash
# .env.example을 복사하여 .env 생성
cp .env.example .env
```

`.env` 파일을 열어 인증키를 입력합니다:
```ini
DATA_GO_KR_API_KEY=발급받은_인증키
```

### 3. 데이터 수집 실행 (CLI)

```bash
# 빠른 검증: 서울 주요 5개 구(강남, 서초, 송파 등) 샘플 수집 (최근 7일)
uv run python src/main.py --fetch --sample --days 7

# 전체 수집: 전국 250개 시군구 전체 수집 (최근 7일)
uv run python src/main.py --fetch --days 7
```

### 4. 대시보드 실행

```bash
# 대시보드 웹 서버 실행 (브라우저 자동 오픈: http://localhost:8501)
uv run streamlit run app.py

# 또는 통합 CLI로 실행
uv run python src/main.py --serve
```

### 5. 단위 테스트 실행
```bash
uv run python -m unittest discover tests
```

---

## ☁️ 배포 가이드 (무료 자동화)

### 1. GitHub Actions 설정
1. GitHub 저장소 생성 후 코드 푸시 (`git push origin master`).
2. GitHub 저장소 **Settings > Secrets and variables > Actions** 메뉴로 이동.
3. **New repository secret** 클릭:
   - Name: `DATA_GO_KR_API_KEY`
   - Secret: 공공데이터포털 일반 인증키
4. `.github/workflows/daily_fetch.yml`에 의해 매일 한국 시간 06:00에 자동으로 실행되어 최신 Parquet 데이터가 커밋됩니다.

### 2. Streamlit Community Cloud 배포
1. [share.streamlit.io](https://share.streamlit.io/) 접속 및 GitHub 계정 로그인.
2. **New app** 클릭:
   - Repository: `본인의_깃허브_저장소`
   - Branch: `master` 또는 `main`
   - Main file path: `app.py`
3. **Deploy!** 버튼 클릭 시 전 세계 어디서나 접속 가능한 아파트 실거래가 대시보드가 무료로 호스팅됩니다.
