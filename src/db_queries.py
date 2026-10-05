"""DuckDB 기반 인메모리 OLAP 분석 쿼리 모듈.

이 모듈은 Parquet 스냅샷 파일을 기반으로 DuckDB를 활용하여
Streamlit 대시보드에 필요한 핵심 KPI, 지역별 분포, 거래 추이, 랭킹 및 상세 검색 쿼리를
밀리초(ms) 단위의 초고속 벡터화 연산으로 수행합니다.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

from storage import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)


def _build_where_clause(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """전달된 필터 딕셔너리를 파싱하여 안전한 SQL WHERE 절과 바인딩 파라미터를 생성합니다.

    Args:
        filters (dict[str, Any]): Streamlit 사이드바에서 선택된 필터 조건.

    Returns:
        tuple[str, list[Any]]: SQL WHERE 절 문자열 및 바인딩 파라미터 리스트.
    """
    conditions: list[str] = []
    params: list[Any] = []

    # 1. 시도 필터
    sido_list = filters.get("sido_nm")
    if sido_list and isinstance(sido_list, list) and len(sido_list) > 0:
        placeholders = ", ".join(["?"] * len(sido_list))
        conditions.append(f"sido_nm IN ({placeholders})")
        params.extend(sido_list)

    # 2. 시군구 필터
    sgg_list = filters.get("sgg_nm")
    if sgg_list and isinstance(sgg_list, list) and len(sgg_list) > 0:
        placeholders = ", ".join(["?"] * len(sgg_list))
        conditions.append(f"sgg_nm IN ({placeholders})")
        params.extend(sgg_list)

    # 3. 일자 범위 필터
    start_date = filters.get("start_date")
    if start_date:
        conditions.append("deal_date >= ?")
        params.append(str(start_date))

    end_date = filters.get("end_date")
    if end_date:
        conditions.append("deal_date <= ?")
        params.append(str(end_date))

    # 4. 가격 범위 필터 (단위: 만원)
    min_price = filters.get("min_price")
    if min_price is not None:
        conditions.append("deal_amount >= ?")
        params.append(int(min_price))

    max_price = filters.get("max_price")
    if max_price is not None:
        conditions.append("deal_amount <= ?")
        params.append(int(max_price))

    # 5. 평형 범위 필터
    min_pyeong = filters.get("min_pyeong")
    if min_pyeong is not None:
        conditions.append("pyeong >= ?")
        params.append(float(min_pyeong))

    max_pyeong = filters.get("max_pyeong")
    if max_pyeong is not None:
        conditions.append("pyeong <= ?")
        params.append(float(max_pyeong))

    # 6. 거래유형 필터 (전체, 중개거래, 직거래)
    dealing_gbn = filters.get("dealing_gbn")
    if dealing_gbn and dealing_gbn != "전체":
        conditions.append("dealing_gbn = ?")
        params.append(str(dealing_gbn))

    # 7. 단지명 검색어
    apt_query = filters.get("apt_query")
    if apt_query and str(apt_query).strip():
        conditions.append("apt_nm LIKE ?")
        params.append(f"%{str(apt_query).strip()}%")

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_sql, params


def get_kpi_summary(
    con: duckdb.DuckDBPyConnection,
    parquet_path: str,
    filters: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """선택된 필터 조건에 따른 주요 거래 지표(총 거래수, 최고가, 평균 평당가 등)를 요약합니다.

    Args:
        con (duckdb.DuckDBPyConnection): DuckDB 커넥션 객체.
        parquet_path (str): 대상 Parquet 파일 경로.
        filters (Optional[dict[str, Any]]): 적용할 필터 딕셔너리.

    Returns:
        dict[str, Any]: 총 거래량, 최고 거래가, 최고가 아파트명, 평균 평당가 요약 딕셔너리.
    """
    p_path = Path(parquet_path)
    if not p_path.exists():
        return {
            "total_trades": 0,
            "max_price": 0,
            "max_price_apt": "-",
            "avg_pyeong_price": 0.0,
            "avg_daily_trades": 0.0,
        }

    where_sql, params = _build_where_clause(filters or {})
    norm_path = str(p_path).replace("\\", "/")

    query = f"""
    SELECT
        COUNT(*) AS total_trades,
        COALESCE(MAX(deal_amount), 0) AS max_price,
        COALESCE(AVG(price_per_pyeong), 0.0) AS avg_pyeong_price,
        COUNT(DISTINCT deal_date) AS unique_days
    FROM '{norm_path}'
    {where_sql}
    """
    row = con.execute(query, params).fetchone()
    total_trades = row[0] if row else 0
    max_price = row[1] if row else 0
    avg_pyeong = float(row[2]) if row else 0.0
    unique_days = row[3] if row and row[3] > 0 else 1

    # 최고가 거래 단지명 및 지역 조회
    max_apt_name = "-"
    max_region = "-"
    if max_price > 0:
        max_apt_query = f"""
        SELECT apt_nm, sido_nm, sgg_nm FROM '{norm_path}'
        {where_sql} {'AND' if where_sql else 'WHERE'} deal_amount = ?
        LIMIT 1
        """
        apt_row = con.execute(max_apt_query, params + [max_price]).fetchone()
        if apt_row:
            max_apt_name = str(apt_row[0])
            max_region = f"{apt_row[1]} {apt_row[2]}"

    return {
        "total_trades": total_trades,
        "max_price": max_price,
        "max_price_apt": max_apt_name,
        "max_price_region": max_region,
        "avg_pyeong_price": round(avg_pyeong, 1),
        "avg_daily_trades": round(total_trades / unique_days, 1) if unique_days else 0.0,
    }


def get_sido_distribution(
    con: duckdb.DuckDBPyConnection,
    parquet_path: str,
    filters: Optional[dict[str, Any]] = None,
) -> pd.DataFrame:
    """시도별 거래 건수 및 평균 평당가를 집계하여 반환합니다.

    Args:
        con (duckdb.DuckDBPyConnection): DuckDB 커넥션 객체.
        parquet_path (str): 대상 Parquet 파일 경로.
        filters (Optional[dict[str, Any]]): 적용할 필터 딕셔너리.

    Returns:
        pd.DataFrame: 시도별 거래량 내림차순 정렬된 데이터프레임.
    """
    p_path = Path(parquet_path)
    if not p_path.exists():
        return pd.DataFrame(columns=["sido_nm", "trade_count", "avg_pyeong_price", "avg_price"])

    where_sql, params = _build_where_clause(filters or {})
    norm_path = str(p_path).replace("\\", "/")

    query = f"""
    SELECT
        sido_nm,
        COUNT(*) AS trade_count,
        ROUND(AVG(price_per_pyeong), 1) AS avg_pyeong_price,
        ROUND(AVG(deal_amount), 0) AS avg_price
    FROM '{norm_path}'
    {where_sql}
    GROUP BY sido_nm
    ORDER BY trade_count DESC
    """
    return con.execute(query, params).df()


def get_daily_trend(
    con: duckdb.DuckDBPyConnection,
    parquet_path: str,
    filters: Optional[dict[str, Any]] = None,
) -> pd.DataFrame:
    """일자별 거래량 및 평균 거래금액 변동 추이를 집계합니다.

    Args:
        con (duckdb.DuckDBPyConnection): DuckDB 커넥션 객체.
        parquet_path (str): 대상 Parquet 파일 경로.
        filters (Optional[dict[str, Any]]): 적용할 필터 딕셔너리.

    Returns:
        pd.DataFrame: 거래일자 오름차순 정렬된 시계열 데이터프레임.
    """
    p_path = Path(parquet_path)
    if not p_path.exists():
        return pd.DataFrame(columns=["deal_date", "trade_count", "avg_price"])

    where_sql, params = _build_where_clause(filters or {})
    norm_path = str(p_path).replace("\\", "/")

    query = f"""
    SELECT
        deal_date,
        COUNT(*) AS trade_count,
        ROUND(AVG(deal_amount), 0) AS avg_price
    FROM '{norm_path}'
    {where_sql}
    GROUP BY deal_date
    ORDER BY deal_date ASC
    """
    return con.execute(query, params).df()


def get_top_rankings(
    con: duckdb.DuckDBPyConnection,
    parquet_path: str,
    rank_by: str = "price",
    filters: Optional[dict[str, Any]] = None,
    limit: int = 10,
) -> pd.DataFrame:
    """지정된 기준(거래가, 평당가, 거래량)에 따라 상위 N개 랭킹 데이터를 추출합니다.

    Args:
        con (duckdb.DuckDBPyConnection): DuckDB 커넥션 객체.
        parquet_path (str): 대상 Parquet 파일 경로.
        rank_by (str): 랭킹 정렬 기준 ('price': 최고거래가, 'pyeong': 최고평당가, 'volume_sgg': 최다거래시군구).
        filters (Optional[dict[str, Any]]): 적용할 필터 조건.
        limit (int): 반환할 최대 레코드 수 (기본값: 10).

    Returns:
        pd.DataFrame: 랭킹 결과 데이터프레임.
    """
    p_path = Path(parquet_path)
    if not p_path.exists():
        return pd.DataFrame()

    where_sql, params = _build_where_clause(filters or {})
    norm_path = str(p_path).replace("\\", "/")

    if rank_by == "volume_sgg":
        query = f"""
        SELECT
            sido_nm || ' ' || sgg_nm AS region_name,
            COUNT(*) AS trade_count,
            ROUND(AVG(price_per_pyeong), 1) AS avg_pyeong_price
        FROM '{norm_path}'
        {where_sql}
        GROUP BY sido_nm, sgg_nm
        ORDER BY trade_count DESC
        LIMIT {limit}
        """
    elif rank_by == "pyeong":
        query = f"""
        SELECT
            deal_date, sido_nm, sgg_nm, umd_nm, apt_nm, exclu_use_ar,
            pyeong, floor, deal_amount, price_per_pyeong, dealing_gbn
        FROM '{norm_path}'
        {where_sql}
        ORDER BY price_per_pyeong DESC
        LIMIT {limit}
        """
    else:  # 기본값: 'price'
        query = f"""
        SELECT
            deal_date, sido_nm, sgg_nm, umd_nm, apt_nm, exclu_use_ar,
            pyeong, floor, deal_amount, price_per_pyeong, dealing_gbn
        FROM '{norm_path}'
        {where_sql}
        ORDER BY deal_amount DESC
        LIMIT {limit}
        """

    return con.execute(query, params).df()


def get_price_alerts(
    con: duckdb.DuckDBPyConnection,
    parquet_path: str,
    filters: Optional[dict[str, Any]] = None,
    limit: int = 50,
) -> dict[str, pd.DataFrame]:
    """직거래 등 특이 거래와 최고가 거래 알림 데이터를 분류 추출합니다.

    Args:
        con (duckdb.DuckDBPyConnection): DuckDB 커넥션 객체.
        parquet_path (str): 대상 Parquet 파일 경로.
        filters (Optional[dict[str, Any]]): 적용할 필터 조건.
        limit (int): 반환할 최대 행 수.

    Returns:
        dict[str, pd.DataFrame]: {'direct_trades': 직거래 목록, 'top_trades': 고가 거래 목록}.
    """
    p_path = Path(parquet_path)
    if not p_path.exists():
        return {"direct_trades": pd.DataFrame(), "top_trades": pd.DataFrame()}

    where_sql, params = _build_where_clause(filters or {})
    norm_path = str(p_path).replace("\\", "/")

    # 직거래 추출
    direct_where = f"{where_sql} {'AND' if where_sql else 'WHERE'} dealing_gbn = '직거래'"
    query_direct = f"""
    SELECT deal_date, sido_nm, sgg_nm, umd_nm, apt_nm, exclu_use_ar, pyeong, floor, deal_amount, price_per_pyeong
    FROM '{norm_path}'
    {direct_where}
    ORDER BY deal_date DESC, deal_amount DESC
    LIMIT {limit}
    """
    df_direct = con.execute(query_direct, params).df()

    # 상위 10% 고가 거래 추출
    query_top = f"""
    SELECT deal_date, sido_nm, sgg_nm, umd_nm, apt_nm, exclu_use_ar, pyeong, floor, deal_amount, price_per_pyeong, dealing_gbn
    FROM '{norm_path}'
    {where_sql}
    ORDER BY deal_amount DESC
    LIMIT {limit}
    """
    df_top = con.execute(query_top, params).df()

    return {"direct_trades": df_direct, "top_trades": df_top}


def search_trades(
    con: duckdb.DuckDBPyConnection,
    parquet_path: str,
    filters: Optional[dict[str, Any]] = None,
    limit: int = 500,
) -> pd.DataFrame:
    """다양한 조건으로 필터링된 전체 거래 내역을 정렬하여 반환합니다.

    Args:
        con (duckdb.DuckDBPyConnection): DuckDB 커넥션 객체.
        parquet_path (str): 대상 Parquet 파일 경로.
        filters (Optional[dict[str, Any]]): 적용할 상세 필터.
        limit (int): 반환할 최대 거래 건수 (기본값: 500).

    Returns:
        pd.DataFrame: 필터링된 거래 내역 데이터프레임.
    """
    p_path = Path(parquet_path)
    if not p_path.exists():
        return pd.DataFrame()

    where_sql, params = _build_where_clause(filters or {})
    norm_path = str(p_path).replace("\\", "/")

    query = f"""
    SELECT
        deal_date,
        sido_nm,
        sgg_nm,
        umd_nm,
        apt_nm,
        exclu_use_ar,
        pyeong,
        floor,
        deal_amount,
        price_per_pyeong,
        build_year,
        dealing_gbn,
        estate_agent_sgg_nm
    FROM '{norm_path}'
    {where_sql}
    ORDER BY deal_date DESC, deal_amount DESC
    LIMIT {limit}
    """
    return con.execute(query, params).df()


def get_available_deal_dates(db_path: Optional[Path] = None) -> list[str]:
    """일자별 요약 테이블 또는 원본 거래 테이블에서 거래 데이터가 존재하는 날짜 목록을 최신순으로 반환합니다.

    Args:
        db_path (Optional[Path]): SQLite DB 파일 경로 (기본값: data/processed/apt_trades.db).

    Returns:
        list[str]: 최신순으로 정렬된 일자(YYYY-MM-DD) 문자열 리스트.
    """
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not target_path.exists():
        return []

    conn = sqlite3.connect(target_path)
    try:
        cursor = conn.cursor()
        # 1. 일자별 요약 테이블에서 일자 목록 조회
        try:
            cursor.execute("SELECT deal_date FROM daily_trade_summary ORDER BY deal_date DESC")
            rows = cursor.fetchall()
            if rows:
                return [row[0] for row in rows]
        except sqlite3.OperationalError:
            pass

        # 2. 요약 테이블이 아직 없을 경우 원본 apt_trades 테이블에서 조회
        try:
            cursor.execute("SELECT DISTINCT deal_date FROM apt_trades ORDER BY deal_date DESC")
            rows = cursor.fetchall()
            return [row[0] for row in rows]
        except sqlite3.OperationalError:
            return []
    finally:
        conn.close()


def get_single_day_summary(deal_date: str, db_path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """지정된 일자의 집계 요약 레코드 1건을 딕셔너리로 반환합니다.

    요약 테이블에 레코드가 없더라도 원본 apt_trades에 거래가 있다면 실시간 집계하여 반환합니다.

    Args:
        deal_date (str): 조회할 계약 일자 (YYYY-MM-DD 형식).
        db_path (Optional[Path]): SQLite DB 파일 경로.

    Returns:
        Optional[dict[str, Any]]: 일자별 핵심 통계 딕셔너리 (해당 일자 데이터가 없으면 None).
    """
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not target_path.exists():
        return None

    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        # 1. 요약 테이블 조회
        try:
            cursor.execute("SELECT * FROM daily_trade_summary WHERE deal_date = ?", (deal_date,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        except sqlite3.OperationalError:
            pass

        # 2. 요약 테이블에 없는 경우 apt_trades에서 즉석 집계
        cursor.execute(
            """
            SELECT 
                COUNT(*) as total_trades,
                COALESCE(SUM(deal_amount), 0) as total_amount,
                COALESCE(ROUND(AVG(deal_amount), 2), 0) as avg_amount,
                COALESCE(ROUND(AVG(price_per_pyeong), 2), 0) as avg_price_per_pyeong,
                COALESCE(MAX(deal_amount), 0) as max_amount,
                COALESCE(SUM(CASE WHEN dealing_gbn = '직거래' THEN 1 ELSE 0 END), 0) as direct_deal_count,
                COALESCE(SUM(CASE WHEN dealing_gbn != '직거래' THEN 1 ELSE 0 END), 0) as broker_deal_count
            FROM apt_trades
            WHERE deal_date = ?
            """,
            (deal_date,),
        )
        agg = cursor.fetchone()
        if not agg or agg["total_trades"] == 0:
            return None

        # 최고 거래가 아파트명 및 시군구명 조회
        cursor.execute(
            "SELECT apt_nm, sgg_nm FROM apt_trades WHERE deal_date = ? AND deal_amount = ? LIMIT 1",
            (deal_date, agg["max_amount"]),
        )
        top = cursor.fetchone()
        res = dict(agg)
        res["deal_date"] = deal_date
        res["max_apt_name"] = top["apt_nm"] if top else ""
        res["max_sgg_nm"] = top["sgg_nm"] if top else ""
        return res
    finally:
        conn.close()


def get_trades_by_date(
    deal_date: str,
    sido_filter: Optional[str] = None,
    sgg_filter: Optional[str] = None,
    min_amount: Optional[int] = None,
    max_amount: Optional[int] = None,
    apt_search: Optional[str] = None,
    limit: int = 1000,
    db_path: Optional[Path] = None,
) -> pd.DataFrame:
    """특정 일자의 상세 아파트 실거래 목록을 필터링 조건에 맞춰 반환합니다.

    Args:
        deal_date (str): 조회 대상 계약 일자 (YYYY-MM-DD).
        sido_filter (Optional[str]): 시도명 필터.
        sgg_filter (Optional[str]): 시군구명 필터.
        min_amount (Optional[int]): 최소 거래금액 (만원).
        max_amount (Optional[int]): 최대 거래금액 (만원).
        apt_search (Optional[str]): 아파트 단지명 검색어 (부분 일치).
        limit (int): 최대 조회 행 수 (기본값: 1000).
        db_path (Optional[Path]): SQLite DB 파일 경로.

    Returns:
        pd.DataFrame: 필터링 및 정렬된 실거래 상세 데이터프레임.
    """
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not target_path.exists():
        return pd.DataFrame()

    query = "SELECT * FROM apt_trades WHERE deal_date = ?"
    params: list[Any] = [deal_date]

    if sido_filter and sido_filter != "전체":
        query += " AND sido_nm = ?"
        params.append(sido_filter)

    if sgg_filter and sgg_filter != "전체":
        query += " AND sgg_nm = ?"
        params.append(sgg_filter)

    if min_amount is not None and min_amount > 0:
        query += " AND deal_amount >= ?"
        params.append(min_amount)

    if max_amount is not None and max_amount > 0:
        query += " AND deal_amount <= ?"
        params.append(max_amount)

    if apt_search and apt_search.strip():
        query += " AND apt_nm LIKE ?"
        params.append(f"%{apt_search.strip()}%")

    query += " ORDER BY deal_amount DESC LIMIT ?"
    params.append(limit)

    conn = sqlite3.connect(target_path)
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def get_day_region_distribution(deal_date: str, db_path: Optional[Path] = None) -> pd.DataFrame:
    """특정 일자의 시도별 거래 건수 및 평균 거래금액 집계를 반환합니다.

    Args:
        deal_date (str): 조회 대상 계약 일자.
        db_path (Optional[Path]): SQLite DB 파일 경로.

    Returns:
        pd.DataFrame: 시도별 거래량(trade_count) 및 평균가(avg_amount) 데이터프레임.
    """
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not target_path.exists():
        return pd.DataFrame()

    query = """
    SELECT 
        sido_nm,
        COUNT(*) as trade_count,
        ROUND(AVG(deal_amount), 1) as avg_amount,
        ROUND(AVG(price_per_pyeong), 1) as avg_pyeong_price
    FROM apt_trades
    WHERE deal_date = ?
    GROUP BY sido_nm
    ORDER BY trade_count DESC, avg_amount DESC
    """
    conn = sqlite3.connect(target_path)
    try:
        return pd.read_sql_query(query, conn, params=[deal_date])
    finally:
        conn.close()


def get_day_price_bands(deal_date: str, db_path: Optional[Path] = None) -> pd.DataFrame:
    """특정 일자의 거래를 5대 금액 구간(3억 이하, 3~6억, 6~9억, 9~15억, 15억 초과)으로 분류하여 집계합니다.

    Args:
        deal_date (str): 조회 대상 계약 일자.
        db_path (Optional[Path]): SQLite DB 파일 경로.

    Returns:
        pd.DataFrame: 금액 구간(price_band)별 거래 건수(count) 데이터프레임.
    """
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not target_path.exists():
        return pd.DataFrame()

    query = """
    SELECT 
        CASE 
            WHEN deal_amount <= 30000 THEN '3억 이하'
            WHEN deal_amount <= 60000 THEN '3억~6억'
            WHEN deal_amount <= 90000 THEN '6억~9억'
            WHEN deal_amount <= 150000 THEN '9억~15억'
            ELSE '15억 초과'
        END AS price_band,
        COUNT(*) AS count
    FROM apt_trades
    WHERE deal_date = ?
    GROUP BY price_band
    ORDER BY 
        CASE price_band
            WHEN '3억 이하' THEN 1
            WHEN '3억~6억' THEN 2
            WHEN '6억~9억' THEN 3
            WHEN '9억~15억' THEN 4
            WHEN '15억 초과' THEN 5
            ELSE 6
        END
    """
    conn = sqlite3.connect(target_path)
    try:
        return pd.read_sql_query(query, conn, params=[deal_date])
    finally:
        conn.close()
