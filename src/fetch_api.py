"""국토교통부 아파트 매매 실거래가 Open API 비동기 수집 파이프라인 모듈.

이 모듈은 공공데이터포털의 국토교통부 아파트매매 실거래가 자료 Open API와 연동하여
전국 시군구 단위의 최근 실거래 데이터를 비동기(httpx/asyncio)로 고속 수집하고,
계약 취소(해제) 거래를 필터링하여 SQLite 마스터 DB 및 Parquet 스냅샷으로 적재합니다.
"""

import asyncio
import logging
import os
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from dotenv import load_dotenv

from constants import SGG_CODE_MAP
from storage import export_recent_trades_to_parquet, save_trades_to_sqlite
from utils import resolve_relative_path

# .env 환경 변수 로드
load_dotenv(resolve_relative_path(".env"))

logger = logging.getLogger(__name__)

# 국토교통부 아파트 매매 실거래가 표준 엔드포인트 URL
API_ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"


def parse_xml_response(xml_text: str) -> list[dict]:
    """공공데이터포털의 응답 XML 문자열을 파싱하여 정제된 거래 딕셔너리 리스트로 변환합니다.

    계약 해제 여부(`cdealType == 'O'`)가 확인된 취소 거래는 분석 데이터 왜곡 방지를 위해 즉시 제외합니다.

    Args:
        xml_text (str): Open API 응답 XML 본문 문자열.

    Returns:
        list[dict]: 정상 유효 거래 데이터 딕셔너리 리스트.
    """
    if not xml_text or not xml_text.strip():
        return []

    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as e:
        logger.error("XML 파싱 실패: %s (응답 앞 200자: %s)", e, xml_text[:200])
        return []

    # 응답 헤더 확인
    header = root.find("header")
    if header is not None:
        result_code = header.findtext("resultCode", "")
        result_msg = header.findtext("resultMsg", "")
        if result_code not in ("00", "000", "NORMAL_SERVICE"):
            logger.warning("API 비정상 응답: [%s] %s", result_code, result_msg)
            return []

    items_container = root.find(".//items")
    if items_container is None:
        return []

    valid_trades: list[dict] = []
    for item in items_container.findall("item"):
        # 계약 해제여부 확인 (해제 거래는 건너뜀)
        cdeal_type = (item.findtext("cdealType") or "").strip().upper()
        if cdeal_type == "O":
            continue

        trade_record: dict[str, str] = {}
        for child in item:
            trade_record[child.tag] = (child.text or "").strip()

        # 필수 필드(단지명, 거래금액, 계약일) 존재 여부 검증
        if trade_record.get("aptNm") and trade_record.get("dealAmount"):
            valid_trades.append(trade_record)

    return valid_trades


def get_target_months(reference_date: Optional[date] = None, days_ago: int = 7) -> list[str]:
    """기준일로부터 지정된 일수(days_ago) 범위에 해당하는 고유한 계약년월(YYYYMM) 목록을 계산합니다.

    월초(예: 1~7일)에 조회할 경우 최근 7일 데이터가 전월에 걸치므로 전월과 당월이 모두 산출됩니다.

    Args:
        reference_date (Optional[date]): 조회 기준일 (기본값: 오늘).
        days_ago (int): 과거 조회 범위 일수 (기본값: 7).

    Returns:
        list[str]: 오름차순 정렬된 6자리 계약년월 문자열 리스트 (예: ['202609', '202610']).
    """
    ref = reference_date if reference_date else date.today()
    start_dt = ref - timedelta(days=days_ago)

    months_set: set[str] = set()
    curr = start_dt
    while curr <= ref:
        months_set.add(curr.strftime("%Y%m"))
        # 다음 날짜로 이동
        curr += timedelta(days=1)

    return sorted(list(months_set))


async def fetch_sgg_trades_async(
    client: httpx.AsyncClient,
    sgg_cd: str,
    deal_ymd: str,
    api_key: str,
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """특정 시군구 및 계약년월에 대한 아파트 매매 실거래가를 비동기 호출합니다.

    공공데이터포털 서버의 동시 연결 제한 및 과부하를 방지하기 위해 세마포어로 동시 요청 수를 제한합니다.

    Args:
        client (httpx.AsyncClient): 비동기 HTTP 클라이언트 세션.
        sgg_cd (str): 5자리 법정동 시군구 코드 (`LAWD_CD`).
        deal_ymd (str): 6자리 계약년월 (`YYYYMM`).
        api_key (str): 공공데이터포털 발급 서비스키.
        semaphore (asyncio.Semaphore): 동시성 제어 세마포어.

    Returns:
        list[dict]: 수집 및 파싱된 해당 지역/월 거래 목록.
    """
    # 이미 URL 인코딩된 키인 경우 이중 인코딩 방지 처리
    decoded_key = urllib.parse.unquote(api_key.strip())

    params = {
        "serviceKey": decoded_key,
        "LAWD_CD": sgg_cd,
        "DEAL_YMD": deal_ymd,
        "numOfRows": 1000,
        "pageNo": 1,
    }

    async with semaphore:
        for attempt in range(3):
            try:
                response = await client.get(API_ENDPOINT, params=params, timeout=15.0)
                if response.status_code == 200:
                    return parse_xml_response(response.text)
                logger.warning(
                    "[%s-%s] HTTP 응답 코드 %d (재시도 %d/3)",
                    sgg_cd,
                    deal_ymd,
                    response.status_code,
                    attempt + 1,
                )
            except Exception as e:
                logger.warning(
                    "[%s-%s] 요청 실패: %s (재시도 %d/3)",
                    sgg_cd,
                    deal_ymd,
                    e,
                    attempt + 1,
                )
            await asyncio.sleep(0.5 * (attempt + 1))

    logger.error("[%s-%s] 3회 재시도 실패로 수집 생략", sgg_cd, deal_ymd)
    return []


async def _run_batch_collection(
    api_key: str,
    target_sggs: list[str],
    target_months: list[str],
    max_concurrency: int = 10,
) -> list[dict]:
    """전국 대상 시군구 및 월 조합에 대해 병렬 비동기 수집 태스크를 실행합니다."""
    semaphore = asyncio.Semaphore(max_concurrency)
    all_collected: list[dict] = []

    async with httpx.AsyncClient() as client:
        tasks = [
            fetch_sgg_trades_async(client, sgg_cd, ym, api_key, semaphore)
            for sgg_cd in target_sggs
            for ym in target_months
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for res in results:
        if isinstance(res, list):
            all_collected.extend(res)
        elif isinstance(res, Exception):
            logger.error("비동기 수집 중 예외 반환: %s", res)

    return all_collected


def collect_recent_nationwide_trades(
    api_key: Optional[str] = None,
    days_ago: int = 7,
    target_sggs: Optional[list[str]] = None,
    max_concurrency: int = 10,
) -> dict:
    """전국(또는 지정된) 시군구의 최근 실거래가를 수집하여 SQLite 및 Parquet에 적재합니다.

    Args:
        api_key (Optional[str]): 공공데이터포털 API 키 (미지정 시 .env의 DATA_GO_KR_API_KEY 사용).
        days_ago (int): 수집 대상 최근 일수 (기본값: 7).
        target_sggs (Optional[list[str]]): 수집 대상 시군구 목록 (미지정 시 전국 250개 전체).
        max_concurrency (int): 동시 비동기 연결 수 (기본값: 10).

    Returns:
        dict: 수집 및 적재 결과 통계 (총 수집건수, 신규 적재건수, Parquet 추출건수).
    """
    key = api_key or os.getenv("DATA_GO_KR_API_KEY", "")
    if not key or key == "your_api_key_here":
        raise ValueError("유효한 공공데이터포털 API 인증키(DATA_GO_KR_API_KEY)가 설정되지 않았습니다.")

    sgg_list = target_sggs if target_sggs else list(SGG_CODE_MAP.keys())
    target_months = get_target_months(date.today(), days_ago=days_ago)

    logger.info(
        "수집 시작: %d개 시군구, 대상 월: %s (최근 %d일)",
        len(sgg_list),
        target_months,
        days_ago,
    )

    # 비동기 수집 실행
    collected_trades = asyncio.run(
        _run_batch_collection(key, sgg_list, target_months, max_concurrency=max_concurrency)
    )

    # SQLite 마스터 DB에 적재 (중복 무시)
    new_inserted = save_trades_to_sqlite(collected_trades)

    # Parquet 스냅샷 추출 (최근 days_ago일 기준)
    exported_parquet = export_recent_trades_to_parquet(days=days_ago)

    summary = {
        "target_sgg_count": len(sgg_list),
        "target_months": target_months,
        "raw_collected_count": len(collected_trades),
        "new_inserted_count": new_inserted,
        "parquet_exported_count": exported_parquet,
        "completed_at": datetime.now().isoformat(),
    }
    logger.info("수집 및 적재 완료 요약: %s", summary)
    return summary


# 외부 호출 편의성을 위한 파이프라인 진입점 별칭(alias)
run_pipeline = collect_recent_nationwide_trades
