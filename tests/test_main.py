"""메인 CLI 진입점(src/main.py) 인자 파싱 및 실행 로직 단위 테스트 모듈.

이 모듈은 CLI 인자(--fetch, --days, --sample, --serve) 파싱 규칙과
파이프라인 실행 옵션이 의도한 대로 동작하는지 검증합니다.
"""

import unittest
from unittest.mock import patch, MagicMock
from src.main import create_parser, run_cli


class TestMainCLI(unittest.TestCase):
    """메인 CLI 인자 및 핸들러 단위 테스트 클래스."""

    def setUp(self) -> None:
        """각 테스트 케이스 전 실행되는 설정 메서드."""
        self.parser = create_parser()

    def test_default_parser_args(self) -> None:
        """기본 인자 없이 실행 시 기본값이 올바르게 설정되는지 검증합니다."""
        args = self.parser.parse_args([])
        self.assertFalse(args.fetch)
        self.assertFalse(args.serve)
        self.assertFalse(args.sample)
        self.assertEqual(args.days, 7)

    def test_custom_parser_args(self) -> None:
        """명시적 플래그 전달 시 인자가 올바르게 파싱되는지 검증합니다."""
        args = self.parser.parse_args(["--fetch", "--days", "14", "--sample"])
        self.assertTrue(args.fetch)
        self.assertEqual(args.days, 14)
        self.assertTrue(args.sample)
        self.assertFalse(args.serve)

    @patch("src.main.run_pipeline")
    def test_run_cli_fetch_called(self, mock_pipeline: MagicMock) -> None:
        """--fetch 플래그 지정 시 run_pipeline이 올바른 인자로 호출되는지 검증합니다."""
        mock_pipeline.return_value = {"total_saved": 5, "new_saved": 5, "total_parquet": 5}
        ret = run_cli(["--fetch", "--days", "3", "--sample"])
        self.assertEqual(ret, 0)
        mock_pipeline.assert_called_once()
        _, kwargs = mock_pipeline.call_args
        self.assertEqual(kwargs.get("days_ago"), 3)
        self.assertIsNotNone(kwargs.get("target_sggs"))


if __name__ == "__main__":
    unittest.main()
