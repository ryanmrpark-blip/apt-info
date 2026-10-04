"""공통 유틸리티 및 보조 함수 모듈.

이 모듈은 apt-info 프로젝트 내 파일 경로 탐색, 디렉토리 검증 및 기본 데이터 입출력 처리를 지원하는
보조 함수를 제공합니다. 모든 경로는 프로젝트 루트 기준의 상대 경로를 준수하도록 설계되었습니다.
"""

from pathlib import Path
from typing import Union


def get_project_root() -> Path:
    """프로젝트 루트 디렉토리의 Path 객체를 반환합니다.

    `src/` 디렉토리 기준으로 상위 1단계 디렉토리를 루트로 식별합니다.
    이 방식은 스크립트 실행 위치(CWD)에 구애받지 않고 일관된 상대 경로 기준점을 확보하기 위함입니다.

    Returns:
        Path: 프로젝트 루트 디렉토리 경로.
    """
    # 현재 파일(src/utils.py)의 부모(src)의 부모(루트 디렉토리)를 지정
    return Path(__file__).resolve().parent.parent


def resolve_relative_path(sub_path: Union[str, Path]) -> Path:
    """프로젝트 루트를 기준으로 한 상대 경로를 절대 또는 정규화된 경로로 변환합니다.

    데이터셋 저장소(`data/`), 문서(`docs/`), 결과물(`reports/`) 등 프로젝트 내부의
    모든 하위 리소스에 접근할 때 경로 불일치 문제를 방지하기 위해 사용합니다.

    Args:
        sub_path (Union[str, Path]): 프로젝트 루트로부터의 상대 경로 문자열 또는 Path 객체.

    Returns:
        Path: 프로젝트 루트와 결합된 완전한 경로 객체.

    Raises:
        ValueError: 전달된 sub_path가 빈 문자열일 경우 발생.

    Example:
        >>> raw_data_path = resolve_relative_path("data/raw/sample.csv")
    """
    if not sub_path:
        raise ValueError("경로가 비어 있습니다. 유효한 상대 경로를 지정해야 합니다.")

    root_dir: Path = get_project_root()
    return root_dir / Path(sub_path)


def ensure_directory(dir_path: Union[str, Path]) -> Path:
    """지정된 디렉토리가 존재하는지 확인하고, 없으면 생성합니다.

    데이터 가공 파이프라인이나 차트 생성 작업 중 대상 폴더 미존재로 인한
    `FileNotFoundError`를 사전에 방지하기 위한 안전장치 역할을 수행합니다.

    Args:
        dir_path (Union[str, Path]): 확인할 디렉토리 경로.

    Returns:
        Path: 생성되었거나 이미 존재하는 대상 디렉토리의 Path 객체.
    """
    target_path = Path(dir_path)
    # 부모 디렉토리까지 포함하여 생성하며, 이미 존재하는 경우 오류를 무시함
    target_path.mkdir(parents=True, exist_ok=True)
    return target_path
