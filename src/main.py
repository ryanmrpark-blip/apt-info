"""apt-info 메인 실행 진입점 모듈.

이 모듈은 국토교통부 아파트 실거래가 수집 파이프라인 실행, CLI 인자 처리,
디렉토리 환경 초기화 및 Streamlit 대시보드 구동을 총괄하는 통합 진입점 스크립트입니다.
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

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

from dotenv import load_dotenv
from fetch_api import run_pipeline
from utils import ensure_directory, get_project_root, resolve_relative_path

# .env 파일이 존재하는 경우 환경 변수 로드 (API Key 등)
load_dotenv(resolve_relative_path(".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 테스트 또는 빠른 검증용 서울 주요 5개 자치구 법정동 코드
SAMPLE_SGG_CODES: List[str] = [
    "11110",  # 종로구
    "11680",  # 강남구
    "11650",  # 서초구
    "11710",  # 송파구
    "11440",  # 마포구
]


def initialize_workspace() -> None:
    """프로젝트 실행에 필요한 데이터 및 산출물 디렉토리를 자동 점검하고 생성합니다.

    실행 환경이 새로 클론되었거나 디렉토리가 부재할 경우 발생할 수 있는
    `FileNotFoundError`를 방지하기 위해 사전 실행됩니다.
    """
    ensure_directory(resolve_relative_path("data/raw"))
    ensure_directory(resolve_relative_path("data/processed"))
    ensure_directory(resolve_relative_path("reports/figures"))
    ensure_directory(resolve_relative_path("docs"))


def create_parser() -> argparse.ArgumentParser:
    """CLI 실행 인자 파서를 생성하고 반환합니다.

    Returns:
        argparse.ArgumentParser: 설정된 CLI 인자 파서 객체.
    """
    parser = argparse.ArgumentParser(
        prog="apt-info",
        description="국토교통부 아파트 매매 실거래가 수집 파이프라인 및 Streamlit 대시보드",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="국토교통부 Open API로부터 아파트 실거래가 데이터를 수집하여 SQLite 및 Parquet에 갱신합니다.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="최근 N일간의 실거래가 데이터를 수집합니다. (기본값: 7)",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="전국 전체(250개) 대신 서울 주요 자치구(강남, 서초, 송파 등) 5곳만 샘플 수집합니다. (개발/테스트용)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Streamlit 반응형 인터랙티브 대시보드를 로컬 브라우저에서 실행합니다.",
    )
    return parser


def run_cli(args_list: Optional[List[str]] = None) -> int:
    """CLI 인자를 파싱하고 요청된 작업을 순차적으로 실행합니다.

    Args:
        args_list (Optional[List[str]]): 명령행 인자 리스트 (테스트 주입용, 기본값은 sys.argv[1:]).

    Returns:
        int: 작업 성공 시 0, 오류 발생 시 1 반환.
    """
    parser = create_parser()
    args = parser.parse_args(args_list)

    # 1. 작업 공간 무결성 점검
    initialize_workspace()

    # 2. 데이터 수집 파이프라인 실행 요청 시
    if args.fetch:
        target_sggs = SAMPLE_SGG_CODES if args.sample else None
        mode_text = "서울 5개 구 샘플" if args.sample else "전국 250개 시군구"
        print(f"\n[INFO] 국토교통부 아파트 매매 실거래가 수집 시작 ({mode_text}, 최근 {args.days}일)")

        try:
            summary = run_pipeline(days_ago=args.days, target_sggs=target_sggs)
            print(
                f"[SUCCESS] 수집 완료! (총 수집 {summary.get('raw_collected_count', 0)}건 / "
                f"신규 DB적재 {summary.get('new_inserted_count', 0)}건 / "
                f"Parquet 스냅샷 {summary.get('parquet_exported_count', 0)}건)"
            )
        except Exception as e:
            logger.exception("실거래가 데이터 수집 중 오류 발생: %s", e)
            print(f"[ERROR] 실거래가 수집 실패: {e}", file=sys.stderr)
            return 1

    # 3. Streamlit 대시보드 실행 요청 시
    if args.serve:
        print("\n[INFO] Streamlit 대시보드를 시작합니다 (app.py)...")
        app_path = resolve_relative_path("app.py")
        cmd = ["uv", "run", "streamlit", "run", str(app_path)]
        try:
            return subprocess.call(cmd)
        except KeyboardInterrupt:
            print("\n[INFO] 대시보드 서버를 종료했습니다.")
            return 0
        except Exception as e:
            logger.exception("Streamlit 대시보드 실행 실패: %s", e)
            return 1

    # 옵션이 둘 다 주어지지 않은 경우 안내 출력
    if not args.fetch and not args.serve:
        root_dir = get_project_root()
        print("=" * 70)
        print("  [apt-info] 아파트 실거래가 및 부동산 종합 EDA 대시보드")
        print("=" * 70)
        print(f"  * 프로젝트 루트: {root_dir}")
        print("  * 사용 가능한 명령어 예시:")
        print("    - 데이터 수집 (샘플): uv run python src/main.py --fetch --sample --days 7")
        print("    - 데이터 수집 (전국): uv run python src/main.py --fetch --days 7")
        print("    - 대시보드 실행     : uv run python src/main.py --serve")
        print("    - 직접 Streamlit    : uv run streamlit run app.py")
        print("=" * 70)

    return 0


def main() -> int:
    """메인 실행 진입점 함수.

    Returns:
        int: 프로세스 종료 코드.
    """
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
