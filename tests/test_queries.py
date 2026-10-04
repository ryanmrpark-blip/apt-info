"""DuckDB 기반 인메모리 OLAP 분석 쿼리 엔진 단위 테스트.

이 모듈은 src/db_queries.py의 KPI 메트릭 집계, 시도별 거래량/평당가 통계,
일자별 거래 추이, 랭킹 산출, 신고가/급매 탐지 및 동적 검색 쿼리의 유효성을 검증합니다.
"""

import sys
import unittest
from pathlib import Path

import duckdb
import pandas as pd

# 테스트 대상 모듈 경로(src/)를 시스템 경로에 추가
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from db_queries import (
    get_daily_trend,
    get_kpi_summary,
    get_sido_distribution,
    get_top_rankings,
    search_trades,
)
from utils import resolve_relative_path


class TestDuckDBQueries(unittest.TestCase):
    """DuckDB 분석 쿼리 모듈 검증 테스트 케이스 클래스."""

    def setUp(self) -> None:
        """테스트용 가상 실거래 Parquet 데이터셋 생성."""
        self.con = duckdb.connect(":memory:")
        self.test_parquet = resolve_relative_path("data/processed/test_query_trades.parquet")

        data = [
            {
                "trade_id": "id_01",
                "sgg_cd": "11680",
                "sido_nm": "서울특별시",
                "sgg_nm": "강남구",
                "umd_nm": "대치동",
                "apt_nm": "은마아파트",
                "jibun": "316",
                "exclu_use_ar": 84.43,
                "pyeong": 25.54,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 3,
                "deal_date": "2026-10-03",
                "deal_amount": 280000,
                "price_per_pyeong": 10963.2,
                "floor": 7,
                "build_year": 1979,
                "dealing_gbn": "중개거래",
                "estate_agent_sgg_nm": "서울 강남구",
                "rgst_date": "",
            },
            {
                "trade_id": "id_02",
                "sgg_cd": "41135",
                "sido_nm": "경기도",
                "sgg_nm": "성남시 분당구",
                "umd_nm": "정자동",
                "apt_nm": "파크뷰",
                "jibun": "9",
                "exclu_use_ar": 134.9,
                "pyeong": 40.81,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 2,
                "deal_date": "2026-10-02",
                "deal_amount": 210000,
                "price_per_pyeong": 5145.8,
                "floor": 15,
                "build_year": 2004,
                "dealing_gbn": "중개거래",
                "estate_agent_sgg_nm": "경기 성남시",
                "rgst_date": "",
            },
            {
                "trade_id": "id_03",
                "sgg_cd": "26350",
                "sido_nm": "부산광역시",
                "sgg_nm": "해운대구",
                "umd_nm": "우동",
                "apt_nm": "해운대두산위브더제니스",
                "jibun": "1407",
                "exclu_use_ar": 127.8,
                "pyeong": 38.66,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 2,
                "deal_date": "2026-10-02",
                "deal_amount": 160000,
                "price_per_pyeong": 4138.6,
                "floor": 42,
                "build_year": 2011,
                "dealing_gbn": "직거래",
                "estate_agent_sgg_nm": "",
                "rgst_date": "",
            },
        ]

        df = pd.DataFrame(data)
        df.to_parquet(self.test_parquet, compression="snappy", index=False)

    def tearDown(self) -> None:
        """테스트 종료 후 연결 종료 및 임시 Parquet 파일 삭제."""
        self.con.close()
        if self.test_parquet.exists():
            self.test_parquet.unlink()

    def test_get_kpi_summary(self) -> None:
        """전체 데이터에 대한 KPI 메트릭이 정확히 산출되는지 검증합니다."""
        kpi = get_kpi_summary(self.con, str(self.test_parquet), filters={})
        self.assertEqual(kpi["total_trades"], 3)
        self.assertEqual(kpi["max_price"], 280000)
        self.assertEqual(kpi["max_price_apt"], "은마아파트")
        self.assertAlmostEqual(kpi["avg_pyeong_price"], (10963.2 + 5145.8 + 4138.6) / 3, places=1)

    def test_get_sido_distribution(self) -> None:
        """시도별 거래량 및 평균 평당가 집계가 정확히 수행되는지 검증합니다."""
        df_sido = get_sido_distribution(self.con, str(self.test_parquet), filters={})
        self.assertEqual(len(df_sido), 3)
        # 서울특별시 확인
        seoul_row = df_sido[df_sido["sido_nm"] == "서울특별시"].iloc[0]
        self.assertEqual(seoul_row["trade_count"], 1)
        self.assertAlmostEqual(seoul_row["avg_pyeong_price"], 10963.2, places=1)

    def test_get_daily_trend(self) -> None:
        """일자별 거래량 추이가 올바르게 집계되는지 검증합니다."""
        df_trend = get_daily_trend(self.con, str(self.test_parquet), filters={})
        self.assertEqual(len(df_trend), 2)  # 2026-10-02 (2건), 2026-10-03 (1건)

    def test_get_top_rankings_price(self) -> None:
        """최고 거래금액 기준 Top 랭킹 쿼리가 올바른 순서로 반환되는지 검증합니다."""
        df_top = get_top_rankings(self.con, str(self.test_parquet), rank_by="price", filters={}, limit=2)
        self.assertEqual(len(df_top), 2)
        self.assertEqual(df_top.iloc[0]["apt_nm"], "은마아파트")
        self.assertEqual(df_top.iloc[0]["deal_amount"], 280000)

    def test_search_trades_with_filters(self) -> None:
        """시도 및 단지명 검색 필터링이 정상적으로 적용되는지 검증합니다."""
        filters = {"sido_nm": ["서울특별시"], "apt_query": "은마"}
        results = search_trades(self.con, str(self.test_parquet), filters=filters)
        self.assertEqual(len(results), 1)
        self.assertEqual(results.iloc[0]["apt_nm"], "은마아파트")


if __name__ == "__main__":
    unittest.main()
