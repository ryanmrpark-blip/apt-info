"""일자별 요약 및 상세 거래 조회 쿼리 함수 단위 테스트.

이 모듈은 src/db_queries.py의 일자 목록 조회(get_available_deal_dates),
특정 일자 요약(get_single_day_summary), 특정 일자 필터링 거래 목록(get_trades_by_date),
시도별 분포(get_day_region_distribution), 금액대별 분포(get_day_price_bands) 함수의 유효성을 검증합니다.
"""

import sys
import unittest
from pathlib import Path

# 테스트 대상 모듈 경로(src/) 등록
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from db_queries import (
    get_available_deal_dates,
    get_day_price_bands,
    get_day_region_distribution,
    get_single_day_summary,
    get_trades_by_date,
)
from storage import init_db, save_trades_to_sqlite, sync_daily_summary


class TestDailyQueries(unittest.TestCase):
    """일자별 상세 쿼리 및 통계 집계 검증 테스트 클래스."""

    def setUp(self) -> None:
        """테스트용 SQLite DB 생성 및 더미 거래 데이터 적재."""
        self.test_dir = Path(__file__).resolve().parent / "test_outputs"
        self.test_dir.mkdir(exist_ok=True)
        self.test_db_path = self.test_dir / "test_queries.db"
        if self.test_db_path.exists():
            self.test_db_path.unlink()

        init_db(self.test_db_path)

        # 2026-10-01 (2건), 2026-10-02 (2건)
        trades = [
            {
                "sgg_cd": "11680",
                "umd_nm": "대치동",
                "apt_nm": "은마아파트",
                "jibun": "316",
                "exclu_use_ar": 84.43,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 1,
                "deal_amount": 280000,  # 28억
                "floor": 7,
                "build_year": 1979,
                "dealing_gbn": "중개거래",
            },
            {
                "sgg_cd": "11650",
                "umd_nm": "반포동",
                "apt_nm": "래미안원베일리",
                "jibun": "1-1",
                "exclu_use_ar": 59.9,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 1,
                "deal_amount": 350000,  # 35억 (최고가)
                "floor": 18,
                "build_year": 2023,
                "dealing_gbn": "직거래",
            },
            {
                "sgg_cd": "41135",  # 경기 성남시 분당구
                "umd_nm": "정자동",
                "apt_nm": "파크뷰",
                "jibun": "6",
                "exclu_use_ar": 139.0,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 2,
                "deal_amount": 195000,  # 19.5억
                "floor": 12,
                "build_year": 2004,
                "dealing_gbn": "중개거래",
            },
            {
                "sgg_cd": "28110",  # 인천 중구
                "umd_nm": "중산동",
                "apt_nm": "영종하늘도시",
                "jibun": "1880",
                "exclu_use_ar": 84.0,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 2,
                "deal_amount": 45000,  # 4.5억
                "floor": 5,
                "build_year": 2019,
                "dealing_gbn": "중개거래",
            },
        ]
        save_trades_to_sqlite(trades, db_path=self.test_db_path)
        sync_daily_summary(db_path=self.test_db_path)

    def tearDown(self) -> None:
        """테스트 종료 후 파일 정리."""
        if self.test_db_path.exists():
            try:
                self.test_db_path.unlink()
            except Exception:
                pass

    def test_get_available_deal_dates(self) -> None:
        """거래가 존재하는 일자 목록이 최신순으로 반환되는지 검증합니다."""
        dates = get_available_deal_dates(db_path=self.test_db_path)
        self.assertEqual(dates, ["2026-10-02", "2026-10-01"])

    def test_get_single_day_summary(self) -> None:
        """특정 일자의 요약 지표를 조회하고 주요 필드 정합성을 검증합니다."""
        summary = get_single_day_summary("2026-10-01", db_path=self.test_db_path)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["deal_date"], "2026-10-01")
        self.assertEqual(summary["total_trades"], 2)
        self.assertEqual(summary["total_amount"], 630000)
        self.assertEqual(summary["max_amount"], 350000)
        self.assertEqual(summary["max_apt_name"], "래미안원베일리")
        self.assertEqual(summary["direct_deal_count"], 1)

        # 미존재 일자 조회 시 None 반환
        non_existent = get_single_day_summary("1999-01-01", db_path=self.test_db_path)
        self.assertIsNone(non_existent)

    def test_get_trades_by_date_with_filters(self) -> None:
        """특정 일자의 거래 목록 조회 및 시도/단지명 필터링을 검증합니다."""
        # 전체 2026-10-01
        df_all = get_trades_by_date("2026-10-01", db_path=self.test_db_path)
        self.assertEqual(len(df_all), 2)

        # 단지명 검색 필터 ('은마')
        df_search = get_trades_by_date("2026-10-01", apt_search="은마", db_path=self.test_db_path)
        self.assertEqual(len(df_search), 1)
        self.assertEqual(df_search.iloc[0]["apt_nm"], "은마아파트")

        # 시도 필터 ('서울특별시')
        df_sido = get_trades_by_date("2026-10-02", sido_filter="경기도", db_path=self.test_db_path)
        self.assertEqual(len(df_sido), 1)
        self.assertEqual(df_sido.iloc[0]["apt_nm"], "파크뷰")

    def test_get_day_region_and_price_bands(self) -> None:
        """당일 시도별 분포 및 가격대별 구간 집계 구조를 검증합니다."""
        # 2026-10-02: 경기도 1건, 인천 1건
        df_region = get_day_region_distribution("2026-10-02", db_path=self.test_db_path)
        self.assertEqual(len(df_region), 2)
        self.assertIn("sido_nm", df_region.columns)
        self.assertIn("trade_count", df_region.columns)

        # 2026-10-02 가격대: 4.5억 (3~6억), 19.5억 (15억 초과)
        df_bands = get_day_price_bands("2026-10-02", db_path=self.test_db_path)
        self.assertFalse(df_bands.empty)
        self.assertIn("price_band", df_bands.columns)
        self.assertIn("count", df_bands.columns)


if __name__ == "__main__":
    unittest.main()
