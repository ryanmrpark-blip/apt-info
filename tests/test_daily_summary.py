"""일자별 실거래 요약 테이블(daily_trade_summary) 스토리지 및 동기화 단위 테스트.

이 모듈은 src/storage.py의 daily_trade_summary 테이블 초기화,
거래 데이터 기반 일자별 집계 동기화(sync_daily_summary), Upsert 무결성,
그리고 요약 레코드 조회 함수를 검증합니다.
"""

import sqlite3
import sys
import unittest
from pathlib import Path

# 테스트 대상 모듈 경로(src/) 등록
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from storage import (
    get_daily_summary_records,
    init_db,
    save_trades_to_sqlite,
    sync_daily_summary,
)


class TestDailySummaryStorage(unittest.TestCase):
    """일자별 요약 테이블 생성 및 동기화 로직 검증 테스트 클래스."""

    def setUp(self) -> None:
        """테스트용 인메모리 또는 임시 SQLite 파일 경로 설정."""
        self.test_dir = Path(__file__).resolve().parent / "test_outputs"
        self.test_dir.mkdir(exist_ok=True)
        self.test_db_path = self.test_dir / "test_trades.db"
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def tearDown(self) -> None:
        """테스트 종료 후 생성된 임시 DB 파일 정리."""
        if self.test_db_path.exists():
            try:
                self.test_db_path.unlink()
            except Exception:
                pass

    def test_init_db_creates_summary_table(self) -> None:
        """init_db 호출 시 daily_trade_summary 테이블 및 인덱스가 생성되는지 검증합니다."""
        init_db(self.test_db_path)

        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()

        # 테이블 존재 확인
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_trade_summary'"
        )
        table = cursor.fetchone()
        self.assertIsNotNone(table, "daily_trade_summary 테이블이 생성되어야 합니다.")

        # 인덱스 존재 확인
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_summary_date'"
        )
        index = cursor.fetchone()
        self.assertIsNotNone(index, "idx_summary_date 인덱스가 생성되어야 합니다.")
        conn.close()

    def test_sync_daily_summary_aggregation(self) -> None:
        """실거래 데이터를 적재한 후 sync_daily_summary() 집계 통계가 정확한지 검증합니다."""
        init_db(self.test_db_path)

        # 2026-10-01 일자 거래 2건, 2026-10-02 일자 거래 1건 준비
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
                "cdeal_type": "",
            },
            {
                "sgg_cd": "11680",
                "umd_nm": "개포동",
                "apt_nm": "디에이치퍼스티어아이파크",
                "jibun": "138",
                "exclu_use_ar": 84.99,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 1,
                "deal_amount": 320000,  # 32억 (최고가)
                "floor": 15,
                "build_year": 2024,
                "dealing_gbn": "직거래",
                "cdeal_type": "",
            },
            {
                "sgg_cd": "11650",
                "umd_nm": "반포동",
                "apt_nm": "아크로리버파크",
                "jibun": "2-12",
                "exclu_use_ar": 84.95,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 2,
                "deal_amount": 420000,  # 42억
                "floor": 10,
                "build_year": 2016,
                "dealing_gbn": "중개거래",
                "cdeal_type": "",
            },
        ]

        # 원본 데이터 삽입
        save_trades_to_sqlite(trades, db_path=self.test_db_path)

        # 요약 동기화 실행
        updated_dates = sync_daily_summary(db_path=self.test_db_path)
        self.assertEqual(updated_dates, 2, "총 2개 일자의 요약이 생성되어야 합니다.")

        df = get_daily_summary_records(db_path=self.test_db_path)
        self.assertEqual(len(df), 2)

        # 2026-10-01 검증
        row_1001 = df[df["deal_date"] == "2026-10-01"].iloc[0]
        self.assertEqual(row_1001["total_trades"], 2)
        self.assertEqual(row_1001["total_amount"], 600000)
        self.assertEqual(row_1001["avg_amount"], 300000.0)
        self.assertEqual(row_1001["max_amount"], 320000)
        self.assertEqual(row_1001["max_apt_name"], "디에이치퍼스티어아이파크")
        self.assertEqual(row_1001["direct_deal_count"], 1)
        self.assertEqual(row_1001["broker_deal_count"], 1)

    def test_sync_daily_summary_upsert(self) -> None:
        """동일 일자에 추가 거래가 적재되었을 때 중복 행 없이 정확히 갱신되는지 검증합니다."""
        init_db(self.test_db_path)

        initial_trade = [
            {
                "sgg_cd": "11680",
                "umd_nm": "대치동",
                "apt_nm": "은마아파트",
                "jibun": "316",
                "exclu_use_ar": 84.43,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 1,
                "deal_amount": 250000,
                "floor": 5,
                "build_year": 1979,
                "dealing_gbn": "중개거래",
                "cdeal_type": "",
            }
        ]
        save_trades_to_sqlite(initial_trade, db_path=self.test_db_path)
        sync_daily_summary(db_path=self.test_db_path)

        df1 = get_daily_summary_records(db_path=self.test_db_path)
        self.assertEqual(len(df1), 1)
        self.assertEqual(df1.iloc[0]["total_trades"], 1)

        # 동일 일자 2026-10-01에 다른 아파트 거래 추가
        additional_trade = [
            {
                "sgg_cd": "11680",
                "umd_nm": "도곡동",
                "apt_nm": "타워팰리스",
                "jibun": "467",
                "exclu_use_ar": 120.0,
                "deal_year": 2026,
                "deal_month": 10,
                "deal_day": 1,
                "deal_amount": 380000,
                "floor": 20,
                "build_year": 2002,
                "dealing_gbn": "중개거래",
                "cdeal_type": "",
            }
        ]
        save_trades_to_sqlite(additional_trade, db_path=self.test_db_path)
        sync_daily_summary(db_path=self.test_db_path)

        df2 = get_daily_summary_records(db_path=self.test_db_path)
        self.assertEqual(len(df2), 1, "동일 일자는 행이 늘어나지 않고 갱신되어야 합니다.")
        self.assertEqual(df2.iloc[0]["total_trades"], 2)
        self.assertEqual(df2.iloc[0]["max_amount"], 380000)
        self.assertEqual(df2.iloc[0]["max_apt_name"], "타워팰리스")


if __name__ == "__main__":
    unittest.main()
