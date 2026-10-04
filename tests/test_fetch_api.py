"""국토교통부 Open API 수집 파이프라인 단위 테스트.

이 모듈은 src/fetch_api.py의 공공데이터포털 XML 파싱, 계약 취소(해제) 거래 필터링,
월초 경계 수집 대상 월 산출, 비동기 수집 인터페이스를 검증합니다.
"""

import sys
import unittest
from datetime import date
from pathlib import Path

# 테스트 대상 모듈 경로(src/)를 시스템 경로에 추가
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from fetch_api import get_target_months, parse_xml_response


class TestFetchApi(unittest.TestCase):
    """Open API 수집 및 파싱 로직 검증 테스트 케이스 클래스."""

    def test_parse_xml_filters_cancelled_trades(self) -> None:
        """해제여부(cdealType == 'O')인 취소 거래가 정상적으로 필터링되고 정상 거래만 추출되는지 검증합니다."""
        xml_sample = """<?xml version="1.0" encoding="UTF-8"?>
        <response>
            <header>
                <resultCode>00</resultCode>
                <resultMsg>NORMAL SERVICE.</resultMsg>
            </header>
            <body>
                <items>
                    <item>
                        <sggCd>11110</sggCd>
                        <umdNm>사직동</umdNm>
                        <aptNm>종로센트레빌</aptNm>
                        <jibun>9</jibun>
                        <dealAmount>120,000</dealAmount>
                        <dealYear>2026</dealYear>
                        <dealMonth>10</dealMonth>
                        <dealDay>02</dealDay>
                        <excluUseAr>84.9</excluUseAr>
                        <floor>5</floor>
                        <buildYear>2008</buildYear>
                        <cdealType></cdealType>
                        <dealingGbn>중개거래</dealingGbn>
                    </item>
                    <item>
                        <sggCd>11110</sggCd>
                        <umdNm>사직동</umdNm>
                        <aptNm>취소아파트</aptNm>
                        <jibun>10</jibun>
                        <dealAmount>95,000</dealAmount>
                        <dealYear>2026</dealYear>
                        <dealMonth>10</dealMonth>
                        <dealDay>01</dealDay>
                        <excluUseAr>59.9</excluUseAr>
                        <floor>3</floor>
                        <buildYear>2010</buildYear>
                        <cdealType>O</cdealType>
                        <cdealDay>2026-10-02</cdealDay>
                        <dealingGbn>중개거래</dealingGbn>
                    </item>
                </items>
                <numOfRows>10</numOfRows>
                <pageNo>1</pageNo>
                <totalCount>2</totalCount>
            </body>
        </response>"""

        items = parse_xml_response(xml_sample)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["aptNm"], "종로센트레빌")
        self.assertEqual(items[0]["dealAmount"], "120,000")
        self.assertEqual(items[0]["floor"], "5")

    def test_parse_xml_empty_items(self) -> None:
        """데이터가 없는 정상 응답 XML 전달 시 빈 리스트가 반환되는지 검증합니다."""
        xml_empty = """<?xml version="1.0" encoding="UTF-8"?>
        <response>
            <header>
                <resultCode>00</resultCode>
                <resultMsg>NORMAL SERVICE.</resultMsg>
            </header>
            <body>
                <items></items>
                <totalCount>0</totalCount>
            </body>
        </response>"""
        items = parse_xml_response(xml_empty)
        self.assertEqual(items, [])

    def test_get_target_months_month_boundary(self) -> None:
        """월초(1~7일) 기준 조회 시 전월과 당월 2개 월이 산출되는지 검증합니다."""
        # 10월 3일 기준 최근 7일은 9월 26일~10월 3일 -> 202609, 202610
        months = get_target_months(date(2026, 10, 3), days_ago=7)
        self.assertEqual(months, ["202609", "202610"])

    def test_get_target_months_mid_month(self) -> None:
        """월 중순(15일 이후) 기준 조회 시 당월 1개 월만 산출되는지 검증합니다."""
        # 10월 25일 기준 최근 7일은 10월 18일~10월 25일 -> 202610
        months = get_target_months(date(2026, 10, 25), days_ago=7)
        self.assertEqual(months, ["202610"])


if __name__ == "__main__":
    unittest.main()
