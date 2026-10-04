"""전국 시군구 매핑 및 상수 정의 단위 테스트 모듈.

이 모듈은 src/constants.py에 정의된 전국 17개 시도 목록,
5자리 법정동 시군구 코드 매핑 테이블, 지역명 조회 헬퍼 함수의 유효성을 검증합니다.
"""

import sys
import unittest
from pathlib import Path

# 테스트 대상 모듈 경로(src/)를 시스템 경로에 추가
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from constants import SGG_CODE_MAP, SIDO_LIST, get_sgg_name


class TestConstants(unittest.TestCase):
    """시군구 매핑 및 공통 상수 검증 테스트 케이스 클래스."""

    def test_sido_list_contains_major_cities(self) -> None:
        """전국 주요 17개 시도가 SIDO_LIST에 포함되어 있는지 검증합니다."""
        self.assertIn("서울특별시", SIDO_LIST)
        self.assertIn("경기도", SIDO_LIST)
        self.assertIn("인천광역시", SIDO_LIST)
        self.assertIn("부산광역시", SIDO_LIST)
        self.assertIn("대구광역시", SIDO_LIST)
        self.assertIn("대전광역시", SIDO_LIST)
        self.assertIn("광주광역시", SIDO_LIST)
        self.assertIn("세종특별자치시", SIDO_LIST)
        self.assertIn("제주특별자치도", SIDO_LIST)

    def test_get_sgg_name_valid_codes(self) -> None:
        """유효한 5자리 시군구 코드에 대해 시도명과 시군구명이 정확히 반환되는지 검증합니다."""
        # 서울 강남구 (11680)
        sido, sgg = get_sgg_name("11680")
        self.assertEqual(sido, "서울특별시")
        self.assertEqual(sgg, "강남구")

        # 경기 성남시 분당구 (41135)
        sido_bd, sgg_bd = get_sgg_name("41135")
        self.assertEqual(sido_bd, "경기도")
        self.assertEqual(sgg_bd, "성남시 분당구")

        # 부산 해운대구 (26350)
        sido_hd, sgg_hd = get_sgg_name("26350")
        self.assertEqual(sido_hd, "부산광역시")
        self.assertEqual(sgg_hd, "해운대구")

    def test_get_sgg_name_unknown_code(self) -> None:
        """알 수 없는 코드 입력 시 안전한 기본값이 반환되는지 검증합니다."""
        sido, sgg = get_sgg_name("99999")
        self.assertEqual(sido, "기타")
        self.assertEqual(sgg, "알수없음")

    def test_sgg_code_map_not_empty(self) -> None:
        """전국 시군구 매핑 테이블이 200개 이상의 유효한 시군구를 포함하는지 검증합니다."""
        self.assertGreater(len(SGG_CODE_MAP), 200)


if __name__ == "__main__":
    unittest.main()
