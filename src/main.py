"""apt-info 메인 실행 진입점 모듈.

이 모듈은 아파트 실거래가 및 부동산 데이터 수집, 정제, 탐색적 데이터 분석(EDA) 파이프라인의
전체 실행 흐름을 관장하는 메인 진입점 스크립트입니다.
"""

import logging
import sys
import time
from pathlib import Path

# 상대 경로를 통한 모듈 참조 보장 (src 디렉토리를 sys.path에 안전하게 등록)
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))

# Windows 콘솔 환경(CP949)에서 한글 및 이모지 출력 시 발생하는 인코딩 오류 방지
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from utils import ensure_directory, get_project_root, resolve_relative_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def initialize_workspace() -> None:
    """프로젝트 실행에 필요한 데이터 및 산출물 디렉토리를 자동 점검하고 생성합니다.

    실행 환경이 새로 클론되었거나 디렉토리가 부재할 경우 발생할 수 있는
    `FileNotFoundError`를 방지하기 위해 사전 실행됩니다.
    """
    ensure_directory(resolve_relative_path("data/raw"))
    ensure_directory(resolve_relative_path("data/processed"))
    ensure_directory(resolve_relative_path("reports/figures"))
    ensure_directory(resolve_relative_path("docs"))


def main() -> int:
    """전체 데이터 수집 및 분석 파이프라인 진입점 함수.

    실행 단계:
    1. 작업 디렉토리 점검 및 초기화 (`initialize_workspace`)
    2. 아파트 데이터 수집 및 전처리 파이프라인 준비 상태 확인
    3. 결과 요약 출력

    Returns:
        int: 정상 수행 시 0 반환, 예외 발생 시 1 반환.
    """
    start_time = time.time()
    root_dir: Path = get_project_root()

    print("=" * 70)
    print("  [apt-info] 아파트 실거래가 및 부동산 종합 EDA 프로젝트")
    print("=" * 70)
    print(f"  * 프로젝트 루트: {root_dir}")
    print("  * 작업 환경 초기화 점검 중...")
    initialize_workspace()

    try:
        print("\n  [INFO] 프로젝트 워크스페이스가 정상적으로 준비되었습니다.")
        print("  * 데이터 원본 폴더: data/raw/")
        print("  * 데이터 가공 폴더: data/processed/")
        print("  * 문서 및 기획서: docs/")
        print("  * 분석 보고서/차트: reports/")
        print("  * 파이썬 소스코드: src/")

        elapsed = time.time() - start_time
        print("\n" + "=" * 70)
        print("  [SUCCESS] 파이프라인 대기 완료!")
        print("=" * 70)
        print(f"  * 소요 시간: {elapsed:.2f}초")
        return 0

    except Exception as e:
        logger.exception("파이프라인 실행 중 오류 발생: %s", e)
        print(f"\n[ERROR] 오류 발생: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
