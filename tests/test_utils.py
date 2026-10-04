"""공통 유틸리티 단위 테스트 모듈.

이 모듈은 src/utils.py에 정의된 프로젝트 루트 식별, 상대 경로 변환 및 디렉토리 생성
헬퍼 함수의 동작 유효성을 검증합니다.
"""

import sys
import unittest
from pathlib import Path

# 테스트 대상 모듈 경로(src/)를 시스템 경로에 추가
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from utils import ensure_directory, get_project_root, resolve_relative_path


class TestUtils(unittest.TestCase):
    """src/utils.py 모듈 함수 검증 테스트 케이스 클래스."""

    def test_get_project_root(self) -> None:
        """프로젝트 루트 디렉토리가 올바르게 식별되는지 검증합니다."""
        root = get_project_root()
        # 프로젝트 루트는 폴더명 'apt-info'이어야 함
        self.assertEqual(root.name, "apt-info")
        # 루트 경로 하위에 pyproject.toml이 존재하는지 검증
        self.assertTrue((root / "pyproject.toml").exists())

    def test_resolve_relative_path(self) -> None:
        """상대 경로를 프로젝트 루트 기준으로 올바르게 결합하는지 검증합니다."""
        resolved = resolve_relative_path("data/raw")
        expected = get_project_root() / "data" / "raw"
        self.assertEqual(resolved, expected)

    def test_resolve_relative_path_empty_error(self) -> None:
        """빈 경로 전달 시 ValueError 예외가 발생하는지 검증합니다."""
        with self.assertRaises(ValueError):
            resolve_relative_path("")

    def test_ensure_directory(self) -> None:
        """디렉토리가 정상적으로 생성되거나 확인되는지 검증합니다."""
        test_dir = resolve_relative_path("data/raw/test_temp")
        created = ensure_directory(test_dir)
        self.assertTrue(created.exists())
        self.assertTrue(created.is_dir())
        # 테스트 후 임시 디렉토리 정리
        test_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
