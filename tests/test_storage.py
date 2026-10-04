"""SQLite 및 Parquet 스토리지 모듈 단위 테스트.

이 모듈은 src/storage.py의 SQLite 테이블 초기화, 거래 레코드 고유 ID 생성,
중복 방지 Upsert 적재, 최근 N일 데이터의 Parquet 스냅샷 추출 기능을 검증합니다.
"""

import sys
import unittest
from pathlib import Path

import duckdb

# 테스트 대상 모듈 경로(src/)를 시스템 경로에 추가
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from storage import (
    export_recent_trades_to_parquet,
    generate_trade_id,
    init_db,
    save_trades_to_sqlite,
)
from utils import resolve_relative_path


class TestStorage(unittest.TestCase):
    """SQLite 및 Parquet 저장소 기능 검증 테스트 케이스 클래스."""

    def setUp(self) -> None:
        """테스트용 SQLite DB 및 Parquet 파일 경로 설정."""
        self.test_db = resolve_relative_path("data/processed/test_trades.db")
        self.test_parquet = resolve_relative_path("data/processed/test_recent.parquet")
        # 기존 잔여 테스트 파일 정리
        if self.test_db.exists():
            self.test_db.unlink()
        if self.test_parquet.exists():
            self.test_parquet.unlink()

    def tearDown(self) -> None:
        """테스트 종료 후 생성된 임시 파일 정리."""
        if self.test_db.exists():
            self.test_db.unlink()
        if self.test_parquet.exists():
            self.test_parquet.unlink()

    def test_generate_trade_id(self) -> None:
        """동일한 거래 레코드에 대해 동일한 16자리 고유 해시 ID가 생성되는지 검증합니다."""
        sample_a = {
            "sggCd": "11680",
            "umdNm": "대치동",
            "aptNm": "은마",
            "excluUseAr": "84.43",
            "dealYear": "2026",
            "dealMonth": "10",
            "dealDay": "03",
            "floor": "7",
            "dealAmount": "280,000",
        }
        sample_b = sample_a.copy()
        id_a = generate_trade_id(sample_a)
        id_b = generate_trade_id(sample_b)
        self.assertEqual(id_a, id_b)
        self.assertEqual(len(id_a), 16)

    def test_save_and_export_trades(self) -> None:
        """SQLite 적재, 중복 저장 방지, Parquet 추출이 정상 작동하는지 검증합니다."""
        init_db(self.test_db)
        sample = [{
            "sggCd": "11680",
            "umdNm": "대치동",
            "aptNm": "은마",
            "jibun": "316",
            "excluUseAr": "84.43",
            "dealYear": "2026",
            "dealMonth": "10",
            "dealDay": "03",
            "dealAmount": "280,000",
            "floor": "7",
            "buildYear": "1979",
            "cdealType": "",
            "dealingGbn": "중개거래",
            "estateAgentSggNm": "서울 강남구",
            "rgstDate": "",
        }]

        # 최초 저장 시 1건 저장
        saved_count = save_trades_to_sqlite(sample, self.test_db)
        self.assertEqual(saved_count, 1)

        # 동일 데이터 재저장 시 0건 저장 (중복 무시)
        dup_count = save_trades_to_sqlite(sample, self.test_db)
        self.assertEqual(dup_count, 0)

        # Parquet 파일 추출
        exported_count = export_recent_trades_to_parquet(
            days=30,
            db_path=self.test_db,
            parquet_path=self.test_parquet,
        )
        self.assertEqual(exported_count, 1)
        self.assertTrue(self.test_parquet.exists())

        # DuckDB를 통한 Parquet 내용 무결성 검증
        row = duckdb.query(
            f"SELECT sgg_nm, apt_nm, deal_amount, pyeong, price_per_pyeong FROM '{self.test_parquet}'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "강남구")
        self.assertEqual(row[1], "은마")
        self.assertEqual(row[2], 280000)
        self.assertAlmostEqual(row[3], 84.43 / 3.30578, places=1)


if __name__ == "__main__":
    unittest.main()
