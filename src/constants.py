"""전국 시군구 코드 및 공통 상수 정의 모듈.

이 모듈은 국토교통부 아파트 매매 실거래가 Open API 호출에 필수적인 전국 250개 시군구
5자리 법정동 코드(`LAWD_CD`), 17개 광역 시도 목록, 지역명 변환 헬퍼 함수를 제공합니다.
"""

import json
from pathlib import Path
from typing import Final, Tuple

from utils import resolve_relative_path

# 전국 17개 광역시도 표준 명칭 목록
SIDO_LIST: Final[list[str]] = [
    "서울특별시",
    "부산광역시",
    "대구광역시",
    "인천광역시",
    "광주광역시",
    "대전광역시",
    "울산광역시",
    "세종특별자치시",
    "경기도",
    "강원특별자치도",
    "충청북도",
    "충청남도",
    "전북특별자치도",
    "전라남도",
    "경상북도",
    "경상남도",
    "제주특별자치도",
]


def _load_sgg_code_map() -> dict[str, dict[str, str]]:
    """`data/raw/sgg_codes.json` 파일에서 250개 시군구 매핑 정보를 로드합니다.

    파일이 존재하지 않는 경우를 대비하여 최소 기본 매핑을 보조로 확보합니다.

    Returns:
        dict[str, dict[str, str]]: 시군구 5자리 코드 -> {'sido': 시도명, 'sgg': 시군구명} 딕셔너리.
    """
    json_path = resolve_relative_path("data/raw/sgg_codes.json")
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # 비상용 기본 서울/수도권 최소 매핑
    return {
        "11110": {"sido": "서울특별시", "sgg": "종로구"},
        "11680": {"sido": "서울특별시", "sgg": "강남구"},
    }


# 전역 시군구 매핑 딕셔너리
SGG_CODE_MAP: Final[dict[str, dict[str, str]]] = _load_sgg_code_map()


def get_sgg_name(sgg_cd: str) -> Tuple[str, str]:
    """5자리 시군구 코드(`LAWD_CD`)를 전달받아 `(시도명, 시군구명)` 튜플을 반환합니다.

    매핑 테이블에 등록되지 않은 비정형 코드가 전달될 경우 안전하게 ('기타', '알수없음')을 반환하여
    파이프라인 중단(KeyError)을 방지합니다.

    Args:
        sgg_cd (str): 5자리 법정동 시군구 코드 (예: '11680').

    Returns:
        Tuple[str, str]: (시도명, 시군구명) 형태의 문자열 튜플.

    Example:
        >>> sido, sgg = get_sgg_name("11680")
        >>> sido
        '서울특별시'
        >>> sgg
        '강남구'
    """
    code_str = str(sgg_cd).strip()
    info = SGG_CODE_MAP.get(code_str)
    if info:
        return info.get("sido", "기타"), info.get("sgg", "알수없음")
    return "기타", "알수없음"
