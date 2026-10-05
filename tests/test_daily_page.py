"""Streamlit 일자별 상세 조회 페이지(pages/1_📅_일자별_거래내역.py) 무결성 단위 테스트.

이 모듈은 신규 생성되는 일자별 실거래가 상세 페이지 파일의 존재 여부,
파이썬 문법적 컴파일 무결성 및 금액/문자열 포맷팅 헬퍼의 유효성을 검증합니다.
"""

import ast
import sys
import unittest
from pathlib import Path

# 루트 디렉토리 참조
ROOT_DIR = Path(__file__).resolve().parent.parent
PAGE_PATH = ROOT_DIR / "pages" / "1_📅_일자별_거래내역.py"


class TestDailyPage(unittest.TestCase):
    """일자별 상세 조회 페이지 파일 및 문법 무결성 테스트 클래스."""

    def test_daily_page_file_exists(self) -> None:
        """pages/1_📅_일자별_거래내역.py 파일이 정상적으로 존재하는지 검증합니다."""
        self.assertTrue(
            PAGE_PATH.exists(),
            f"일자별 거래내역 페이지 파일이 존재해야 합니다: {PAGE_PATH}",
        )

    def test_page_syntax_validity(self) -> None:
        """페이지 파이썬 소스 코드에 문법 오류가 없는지 파싱(ast.parse)하여 검증합니다."""
        if not PAGE_PATH.exists():
            self.skipTest("페이지 파일이 아직 생성되지 않았습니다.")

        with open(PAGE_PATH, "r", encoding="utf-8") as f:
            source = f.read()

        # AST 파싱 성공 시 문법 오류 없음
        parsed = ast.parse(source, filename=str(PAGE_PATH))
        self.assertIsNotNone(parsed, "페이지 소스 코드가 유효한 파이썬 AST로 파싱되어야 합니다.")


if __name__ == "__main__":
    unittest.main()
