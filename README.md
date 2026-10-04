# apt-info: 아파트 실거래가 및 부동산 종합 EDA 프로젝트

아파트 실거래가 및 부동산 데이터의 수집, 전처리, 탐색적 데이터 분석(EDA), 시각화 및 결과 리포트를 수행하기 위한 독립 프로젝트 워크스페이스입니다.

---

## 📁 디렉토리 구조

```text
apt-info/
├── .venv/                     # uv 기반 Python 가상환경
├── data/
│   ├── raw/                   # 수집된 원본 데이터셋 저장소
│   └── processed/             # 정제 및 가공된 분석용 데이터셋
├── docs/
│   ├── overview.md            # 프로젝트 개요 및 명세서
│   └── plan.md                # 단계별 진행 계획서 및 마일스톤
├── reports/
│   ├── figures/               # 시각화 이미지 및 분석 차트
│   └── report.md              # 분석 결과 종합 보고서
├── src/
│   ├── __init__.py            # 소스 패키지 초기화
│   ├── utils.py               # 프로젝트 공통 보조 함수 및 경로 유틸리티
│   └── main.py                # 전체 분석 파이프라인 진입점
├── tests/
│   ├── __init__.py            # 테스트 패키지 초기화
│   └── test_utils.py          # 단위 테스트 스크립트
├── pyproject.toml             # uv 패키지 메타데이터 및 의존성 설정
├── README.md                  # 프로젝트 안내서
└── .gitignore                 # 형상 관리 제외 목록
```

---

## 🚀 빠른 시작 (Quick Start)

본 프로젝트는 **`uv`** 패키지 관리자를 사용하여 가상환경 및 의존성을 관리합니다.

### 1. 가상환경 동기화 및 생성
```bash
# apt-info 프로젝트 디렉토리로 이동
cd apt-info

# 가상환경 동기화
uv sync
```

### 2. 메인 파이프라인 실행
```bash
# uv 가상환경을 통한 메인 스크립트 실행
uv run python src/main.py
```

### 3. 단위 테스트 실행
```bash
# 단위 테스트 실행
uv run python -m unittest discover tests
```

---

## 📋 핵심 규칙 (Principles)

1. **Python 가상환경**: Python 가상환경 관리는 반드시 `uv`만 사용합니다.
2. **상대 경로 준수**: 코드 내 모든 데이터 및 파일 입출력은 프로젝트 루트 기준의 상대 경로(`src/utils.py`의 `resolve_relative_path` 활용)를 사용합니다.
3. **한국어 문서화**: 모든 Python 코드에는 명확한 한국어 Docstring(Google Style) 및 타입 힌트(`typing`)를 적용합니다.
