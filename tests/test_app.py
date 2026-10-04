"""Streamlit 대시보드 애플리케이션 무결성 검증 테스트.

이 모듈은 app.py의 문법적 무결성, 모듈 임포트 가능 여부 및 금액 표기 포맷 헬퍼 함수가
정상 동작하는지 검증합니다.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

# 프로젝트 루트 경로를 시스템 경로에 추가
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))


class TestApp(unittest.TestCase):
    """Streamlit 애플리케이션 모듈 검증 테스트 클래스."""

    def test_app_spec_exists(self) -> None:
        """app.py 파일이 프로젝트 루트에 존재하고 임포트 명세가 유효한지 검증합니다."""
        app_file = ROOT_DIR / "app.py"
        self.assertTrue(app_file.exists(), "app.py 파일이 루트에 존재해야 합니다.")
        spec = importlib.util.spec_from_file_location("app_module", app_file)
        self.assertIsNotNone(spec)

    def test_amount_formatter_logic(self) -> None:
        """만원 단위 금액이 억/만원 한글 단위로 가독성 있게 변환되는지 검증합니다."""
        # 280,000만원 -> 28억 원
        # 8,500만원 -> 8,500만 원
        # 125,400만원 -> 12억 5,400만 원
        from app import format_amount

        self.assertEqual(format_amount(280000), "28억 원")
        self.assertEqual(format_amount(8500), "8,500만 원")
        self.assertEqual(format_amount(125400), "12억 5,400만 원")
        self.assertEqual(format_amount(0), "0원")


if __name__ == "__main__":
    unittest.main()
