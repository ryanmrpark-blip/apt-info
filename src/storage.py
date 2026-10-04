"""SQLite 마스터 DB 및 Parquet 스냅샷 스토리지 모듈.

이 모듈은 수집된 아파트 매매 실거래가 데이터의 트랜잭션 정합성 보장,
중복 거래 방지(Upsert) 및 분석·배포를 위한 고압축 Parquet 스냅샷 추출 기능을 제공합니다.
모든 경로는 프로젝트 루트 기준의 상대 경로를 준수합니다.
"""

import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from constants import get_sgg_name
from utils import ensure_directory, resolve_relative_path

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH: Path = resolve_relative_path("data/processed/apt_trades.db")
DEFAULT_PARQUET_PATH: Path = resolve_relative_path("data/processed/recent_trades.parquet")


def init_db(db_path: Optional[Path] = None) -> None:
    """SQLite 데이터베이스 스키마 및 고속 조회를 위한 인덱스를 초기화합니다.

    Args:
        db_path (Optional[Path]): 대상 SQLite 데이터베이스 파일 경로 (기본값: data/processed/apt_trades.db).
    """
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    ensure_directory(target_path.parent)

    conn = sqlite3.connect(target_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS apt_trades (
                trade_id TEXT PRIMARY KEY,
                sgg_cd TEXT NOT NULL,
                sido_nm TEXT NOT NULL,
                sgg_nm TEXT NOT NULL,
                umd_nm TEXT NOT NULL,
                apt_nm TEXT NOT NULL,
                jibun TEXT,
                exclu_use_ar REAL NOT NULL,
                pyeong REAL NOT NULL,
                deal_year INTEGER NOT NULL,
                deal_month INTEGER NOT NULL,
                deal_day INTEGER NOT NULL,
                deal_date TEXT NOT NULL,
                deal_amount INTEGER NOT NULL,
                price_per_pyeong REAL NOT NULL,
                floor INTEGER,
                build_year INTEGER,
                dealing_gbn TEXT,
                estate_agent_sgg_nm TEXT,
                rgst_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_deal_date ON apt_trades(deal_date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sido_sgg ON apt_trades(sido_nm, sgg_nm);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_apt_name ON apt_trades(apt_nm);")
        conn.commit()
    finally:
        conn.close()


def generate_trade_id(record: dict) -> str:
    """거래 레코드의 고유 식별자(해시 문자열)를 생성합니다.

    동일한 단지, 일자, 면적, 층, 거래금액을 조합하여 16자리 MD5 해시를 산출함으로써
    매일 반복 수집되는 데이터 파이프라인에서 중복 레코드가 적재되는 것을 방지합니다.

    Args:
        record (dict): 수집된 단일 거래 딕셔너리.

    Returns:
        str: 16자리 16진수 고유 해시 문자열.
    """
    sgg = str(record.get("sggCd", "")).strip()
    year = str(record.get("dealYear", "")).strip()
    month = f"{int(record.get('dealMonth', 0)):02d}"
    day = f"{int(record.get('dealDay', 0)):02d}"
    apt = str(record.get("aptNm", "")).strip()
    ar = str(record.get("excluUseAr", "")).strip()
    floor = str(record.get("floor", "")).strip()
    amount = str(record.get("dealAmount", "")).replace(",", "").strip()

    raw_key = f"{sgg}_{year}{month}{day}_{apt}_{ar}_{floor}_{amount}"
    return hashlib.md5(raw_key.encode("utf-8")).hexdigest()[:16]


def _clean_int(val: object, default: int = 0) -> int:
    """문자열 숫자를 정수형으로 안전하게 변환합니다."""
    if val is None:
        return default
    cleaned = str(val).replace(",", "").strip()
    try:
        return int(cleaned)
    except ValueError:
        return default


def _clean_float(val: object, default: float = 0.0) -> float:
    """문자열 숫자를 실수형으로 안전하게 변환합니다."""
    if val is None:
        return default
    cleaned = str(val).replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return default


def save_trades_to_sqlite(trades: list[dict], db_path: Optional[Path] = None) -> int:
    """수집된 아파트 실거래가 목록을 SQLite 데이터베이스에 적재합니다.

    이미 존재하는 거래건은 `INSERT OR IGNORE` 문을 통해 건너뛰어 중복을 방지합니다.

    Args:
        trades (list[dict]): 수집된 거래 레코드 딕셔너리 리스트.
        db_path (Optional[Path]): 대상 SQLite DB 파일 경로.

    Returns:
        int: 데이터베이스에 신규로 추가된 순수 거래 레코드 건수.
    """
    if not trades:
        return 0

    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    init_db(target_path)

    insert_rows: list[tuple] = []
    for item in trades:
        # 해제된 거래는 스킵
        cdeal = str(item.get("cdealType", "")).strip().upper()
        if cdeal == "O":
            continue

        trade_id = generate_trade_id(item)
        sgg_cd = str(item.get("sggCd", "")).strip()
        sido_nm, sgg_nm = get_sgg_name(sgg_cd)
        umd_nm = str(item.get("umdNm", "")).strip()
        apt_nm = str(item.get("aptNm", "")).strip()
        jibun = str(item.get("jibun", "")).strip()

        exclu_ar = _clean_float(item.get("excluUseAr"))
        # 평형 환산 (1평 = 3.30578 ㎡)
        pyeong = round(exclu_ar / 3.30578, 2) if exclu_ar > 0 else 0.0

        year = _clean_int(item.get("dealYear"))
        month = _clean_int(item.get("dealMonth"))
        day = _clean_int(item.get("dealDay"))
        deal_date = f"{year:04d}-{month:02d}-{day:02d}"

        amount = _clean_int(item.get("dealAmount"))
        price_per_pyeong = round(amount / pyeong, 1) if pyeong > 0 else 0.0

        floor = _clean_int(item.get("floor"))
        build_year = _clean_int(item.get("buildYear"))
        dealing_gbn = str(item.get("dealingGbn", "")).strip()
        estate_agent = str(item.get("estateAgentSggNm", "")).strip()
        rgst_date = str(item.get("rgstDate", "")).strip()

        insert_rows.append(
            (
                trade_id,
                sgg_cd,
                sido_nm,
                sgg_nm,
                umd_nm,
                apt_nm,
                jibun,
                exclu_ar,
                pyeong,
                year,
                month,
                day,
                deal_date,
                amount,
                price_per_pyeong,
                floor,
                build_year,
                dealing_gbn,
                estate_agent,
                rgst_date,
            )
        )

    conn = sqlite3.connect(target_path)
    try:
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT OR IGNORE INTO apt_trades (
                trade_id, sgg_cd, sido_nm, sgg_nm, umd_nm, apt_nm, jibun,
                exclu_use_ar, pyeong, deal_year, deal_month, deal_day, deal_date,
                deal_amount, price_per_pyeong, floor, build_year, dealing_gbn,
                estate_agent_sgg_nm, rgst_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_rows,
        )
        inserted_count = cursor.rowcount
        conn.commit()
    finally:
        conn.close()

    logger.info("SQLite 적재 완료: 전달 %d건 중 신규 %d건 삽입", len(trades), inserted_count)
    return inserted_count


def export_recent_trades_to_parquet(
    days: int = 7,
    db_path: Optional[Path] = None,
    parquet_path: Optional[Path] = None,
) -> int:
    """SQLite 데이터베이스에서 최근 N일치 데이터를 추출하여 배포용 Parquet 스냅샷으로 저장합니다.

    Snappy 고압축 형식을 적용하여 수 MB 내외의 초경량 크기로 압축 저장합니다.

    Args:
        days (int): 추출할 최근 일수 (기본값: 7일, 음수 또는 0일 경우 전체 데이터 추출).
        db_path (Optional[Path]): 원본 SQLite DB 경로.
        parquet_path (Optional[Path]): 저장할 대상 Parquet 파일 경로.

    Returns:
        int: 추출 및 저장된 Parquet 레코드 행 수.
    """
    src_db = Path(db_path) if db_path else DEFAULT_DB_PATH
    out_parquet = Path(parquet_path) if parquet_path else DEFAULT_PARQUET_PATH
    ensure_directory(out_parquet.parent)

    if not src_db.exists():
        logger.warning("SQLite DB 파일이 존재하지 않아 빈 Parquet을 생성합니다: %s", src_db)
        df_empty = pd.DataFrame(
            columns=[
                "trade_id",
                "sgg_cd",
                "sido_nm",
                "sgg_nm",
                "umd_nm",
                "apt_nm",
                "jibun",
                "exclu_use_ar",
                "pyeong",
                "deal_year",
                "deal_month",
                "deal_day",
                "deal_date",
                "deal_amount",
                "price_per_pyeong",
                "floor",
                "build_year",
                "dealing_gbn",
                "estate_agent_sgg_nm",
                "rgst_date",
            ]
        )
        df_empty.to_parquet(out_parquet, compression="snappy", index=False)
        return 0

    conn = sqlite3.connect(src_db)
    try:
        if days > 0:
            threshold_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            query = "SELECT * FROM apt_trades WHERE deal_date >= ? ORDER BY deal_date DESC"
            df = pd.read_sql_query(query, conn, params=[threshold_date])
        else:
            query = "SELECT * FROM apt_trades ORDER BY deal_date DESC"
            df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    table = pa.Table.from_pandas(df)
    pq.write_table(table, out_parquet, compression="snappy")
    logger.info("Parquet 스냅샷 추출 완료: %d건 저장 -> %s", len(df), out_parquet)
    return len(df)
