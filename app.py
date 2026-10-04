"""전국 아파트 실거래가 Streamlit 종합 대시보드 애플리케이션.

이 모듈은 국토교통부 실거래가 Open API로 수집된 Parquet 데이터를 기반으로,
DuckDB 인메모리 OLAP 질의를 통해 전국 아파트 실거래 현황, 지역/단지 랭킹,
신고가·직거래 탐지 및 상세 데이터 탐색 인터페이스를 제공하는 웹 애플리케이션입니다.
"""

import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# 상대 경로를 통한 모듈 참조 등록
CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from constants import SGG_CODE_MAP, SIDO_LIST
from db_queries import (
    get_daily_trend,
    get_kpi_summary,
    get_price_alerts,
    get_sido_distribution,
    get_top_rankings,
    search_trades,
)
from utils import resolve_relative_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Parquet 기본 데이터 경로
PARQUET_FILE_PATH: Path = resolve_relative_path("data/processed/recent_trades.parquet")


def format_amount(amount_manwon: int) -> str:
    """만원 단위 숫자를 한글 억/만원 단위 문자열로 가독성 있게 포맷팅합니다.

    Args:
        amount_manwon (int): 만원 단위 거래금액 (예: 280000).

    Returns:
        str: 가독성 높은 한글 금액 문자열 (예: '28억 원', '12억 5,400만 원').

    Example:
        >>> format_amount(280000)
        '28억 원'
        >>> format_amount(8500)
        '8,500만 원'
    """
    if not amount_manwon or amount_manwon <= 0:
        return "0원"

    eok = amount_manwon // 10000
    rem = amount_manwon % 10000

    if eok > 0 and rem > 0:
        return f"{eok:,}억 {rem:,}만 원"
    elif eok > 0:
        return f"{eok:,}억 원"
    else:
        return f"{rem:,}만 원"


@st.cache_resource
def get_duckdb_connection() -> duckdb.DuckDBPyConnection:
    """Streamlit 리소스 캐싱을 적용한 인메모리 DuckDB 연결 객체를 반환합니다."""
    return duckdb.connect(":memory:")


def main() -> None:
    """Streamlit 메인 대시보드 렌더링 진입점 함수."""
    st.set_page_config(
        page_title="전국 아파트 실거래가 대시보드",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # 헤더 타이틀 영역
    st.title("🏢 전국 아파트 매매 실거래가 종합 대시보드")
    st.caption("국토교통부 실거래가 Open API 기반 최근 1주일 전국 실거래 데이터 분석 시스템")

    con = get_duckdb_connection()
    parquet_path_str = str(PARQUET_FILE_PATH).replace("\\", "/")

    # 데이터 파일 존재 여부 검사
    if not PARQUET_FILE_PATH.exists() or PARQUET_FILE_PATH.stat().st_size == 0:
        st.warning("⚠️ 실거래가 데이터(`recent_trades.parquet`)가 아직 준비되지 않았습니다.")
        st.info(
            "아래 터미널 명령어를 실행하여 데이터를 먼저 수집해 주세요:\n\n"
            "```bash\nuv run python src/fetch_api.py\n```"
        )
        return

    # ==============================================================================
    # 사이드바: 글로벌 필터 컨트롤
    # ==============================================================================
    with st.sidebar:
        st.header("🔍 검색 및 필터 옵션")

        # 1. 시도 및 시군구 필터
        selected_sido = st.multiselect("시도 선택", options=SIDO_LIST, default=[])

        # 선택된 시도에 따른 시군구 목록 동적 필터링
        available_sgg: list[str] = []
        if selected_sido:
            for info in SGG_CODE_MAP.values():
                if info.get("sido") in selected_sido:
                    available_sgg.append(info.get("sgg", ""))
            available_sgg = sorted(list(set(available_sgg)))
        else:
            available_sgg = sorted(list(set(info.get("sgg", "") for info in SGG_CODE_MAP.values())))

        selected_sgg = st.multiselect("시군구 선택", options=available_sgg, default=[])

        # 2. 거래유형
        selected_gbn = st.selectbox("거래유형", options=["전체", "중개거래", "직거래"], index=0)

        # 3. 평형 범위 슬라이더
        pyeong_range = st.slider("전용 평형 범위 (평)", min_value=5.0, max_value=80.0, value=(5.0, 80.0), step=5.0)

        # 4. 거래금액 범위 슬라이더 (단위: 억원)
        price_range_eok = st.slider("거래금액 범위 (억원)", min_value=0.5, max_value=60.0, value=(0.5, 60.0), step=0.5)

        # 5. 단지명 텍스트 검색
        apt_query = st.text_input("아파트 단지명 검색", placeholder="예: 은마, 래미안, 자이")

        st.divider()
        st.markdown("💡 **데이터 갱신 안내**\n매일 오전 06:00 KST에 GitHub Actions를 통해 자동 업데이트됩니다.")

    # 필터 딕셔너리 구성
    filters: dict[str, Any] = {
        "sido_nm": selected_sido if selected_sido else None,
        "sgg_nm": selected_sgg if selected_sgg else None,
        "dealing_gbn": selected_gbn,
        "min_pyeong": pyeong_range[0],
        "max_pyeong": pyeong_range[1],
        "min_price": int(price_range_eok[0] * 10000),
        "max_price": int(price_range_eok[1] * 10000),
        "apt_query": apt_query,
    }

    # ==============================================================================
    # 상단: 핵심 KPI 지표 카드 4종
    # ==============================================================================
    kpi = get_kpi_summary(con, parquet_path_str, filters)

    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
    with kpi_col1:
        st.metric("총 거래 건수", f"{kpi['total_trades']:,} 건")
    with kpi_col2:
        st.metric("최고 거래가", format_amount(kpi["max_price"]), help=kpi["max_price_apt"])
    with kpi_col3:
        st.metric("평균 평당가", f"{kpi['avg_pyeong_price']:,} 만원/평")
    with kpi_col4:
        st.metric("일평균 거래량", f"{kpi['avg_daily_trades']:,} 건/일")

    st.markdown("---")

    # ==============================================================================
    # 메인 4대 탭 네비게이션
    # ==============================================================================
    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "📊 전국 실거래 현황",
            "🏆 지역 & 단지 랭킹",
            "🔍 신고가 및 특이 거래",
            "📋 실거래가 상세 탐색기",
        ]
    )

    # --------------------------------------------------------------------------
    # 탭 1: 전국 실거래 현황
    # --------------------------------------------------------------------------
    with tab1:
        st.subheader("전국 지역별 거래 분포 및 일자별 추이")
        col_chart1, col_chart2 = st.columns([6, 4])

        with col_chart1:
            df_sido = get_sido_distribution(con, parquet_path_str, filters)
            if not df_sido.empty:
                fig_sido = px.bar(
                    df_sido,
                    x="sido_nm",
                    y="trade_count",
                    color="avg_pyeong_price",
                    title="시도별 거래량 및 평균 평당가 (만원/평)",
                    labels={
                        "sido_nm": "시도",
                        "trade_count": "거래 건수",
                        "avg_pyeong_price": "평균 평당가(만원)",
                    },
                    color_continuous_scale="Viridis",
                )
                fig_sido.update_layout(xaxis_tickangle=-45, margin=dict(l=20, r=20, t=40, b=40))
                st.plotly_chart(fig_sido, use_container_width=True)
            else:
                st.info("선택된 조건에 해당하는 지역별 거래 데이터가 없습니다.")

        with col_chart2:
            df_trend = get_daily_trend(con, parquet_path_str, filters)
            if not df_trend.empty:
                fig_trend = px.area(
                    df_trend,
                    x="deal_date",
                    y="trade_count",
                    title="최근 일자별 거래량 추이",
                    labels={"deal_date": "계약일", "trade_count": "거래 건수"},
                    markers=True,
                )
                fig_trend.update_layout(margin=dict(l=20, r=20, t=40, b=40))
                st.plotly_chart(fig_trend, use_container_width=True)
            else:
                st.info("선택된 조건에 해당하는 일자별 거래 데이터가 없습니다.")

    # --------------------------------------------------------------------------
    # 탭 2: 지역 및 단지 랭킹
    # --------------------------------------------------------------------------
    with tab2:
        st.subheader("최근 거래량 및 최고가 Top 랭킹")
        col_rank1, col_rank2 = st.columns(2)

        with col_rank1:
            st.markdown("##### 📍 최다 거래 시군구 Top 10")
            df_top_sgg = get_top_rankings(con, parquet_path_str, rank_by="volume_sgg", filters=filters, limit=10)
            if not df_top_sgg.empty:
                fig_sgg = px.bar(
                    df_top_sgg,
                    x="trade_count",
                    y="region_name",
                    orientation="h",
                    labels={"trade_count": "거래량", "region_name": "시군구"},
                    color="trade_count",
                    color_continuous_scale="Blues",
                )
                fig_sgg.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig_sgg, use_container_width=True)
            else:
                st.info("시군구 랭킹 데이터가 없습니다.")

        with col_rank2:
            st.markdown("##### 💎 최고 거래금액 아파트 Top 10")
            df_top_price = get_top_rankings(con, parquet_path_str, rank_by="price", filters=filters, limit=10)
            if not df_top_price.empty:
                display_df = df_top_price.copy()
                display_df["거래금액"] = display_df["deal_amount"].apply(format_amount)
                display_df["평당가"] = display_df["price_per_pyeong"].apply(lambda x: f"{x:,.0f}만원")
                display_df["위치"] = display_df["sido_nm"] + " " + display_df["sgg_nm"] + " " + display_df["umd_nm"]
                st.dataframe(
                    display_df[["deal_date", "위치", "apt_nm", "floor", "pyeong", "거래금액", "평당가"]].rename(
                        columns={
                            "deal_date": "계약일",
                            "apt_nm": "단지명",
                            "floor": "층",
                            "pyeong": "평형",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("최고가 랭킹 데이터가 없습니다.")

    # --------------------------------------------------------------------------
    # 탭 3: 신고가 및 특이 거래
    # --------------------------------------------------------------------------
    with tab3:
        st.subheader("직거래 및 고가 거래 모니터링")
        alerts = get_price_alerts(con, parquet_path_str, filters=filters, limit=30)

        alert_col1, alert_col2 = st.columns(2)
        with alert_col1:
            st.markdown("##### ⚠️ 직거래 체결 내역 (시세 왜곡 주의)")
            df_direct = alerts.get("direct_trades", pd.DataFrame())
            if not df_direct.empty:
                df_direct_display = df_direct.copy()
                df_direct_display["거래금액"] = df_direct_display["deal_amount"].apply(format_amount)
                df_direct_display["지역"] = df_direct_display["sido_nm"] + " " + df_direct_display["sgg_nm"]
                st.dataframe(
                    df_direct_display[["deal_date", "지역", "apt_nm", "floor", "pyeong", "거래금액"]].rename(
                        columns={"deal_date": "계약일", "apt_nm": "단지명", "floor": "층", "pyeong": "평형"}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("선택된 조건에서 직거래 체결 건이 없습니다.")

        with alert_col2:
            st.markdown("##### 👑 주요 고액 거래 목록")
            df_top = alerts.get("top_trades", pd.DataFrame())
            if not df_top.empty:
                df_top_display = df_top.copy()
                df_top_display["거래금액"] = df_top_display["deal_amount"].apply(format_amount)
                df_top_display["지역"] = df_top_display["sido_nm"] + " " + df_top_display["sgg_nm"]
                st.dataframe(
                    df_top_display[["deal_date", "지역", "apt_nm", "floor", "pyeong", "거래금액", "dealing_gbn"]].rename(
                        columns={
                            "deal_date": "계약일",
                            "apt_nm": "단지명",
                            "floor": "층",
                            "pyeong": "평형",
                            "dealing_gbn": "유형",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("고액 거래 데이터가 없습니다.")

    # --------------------------------------------------------------------------
    # 탭 4: 실거래가 상세 탐색기
    # --------------------------------------------------------------------------
    with tab4:
        st.subheader("실거래가 상세 검색 및 데이터 다운로드")
        df_search = search_trades(con, parquet_path_str, filters=filters, limit=1000)

        if not df_search.empty:
            st.write(f"검색 결과: 총 **{len(df_search):,}** 건")

            # CSV 다운로드 버튼
            csv_data = df_search.to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                label="📥 필터링된 결과 CSV 다운로드",
                data=csv_data,
                file_name=f"apt_trades_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )

            # 포맷팅 적용 테이블 렌더링
            view_df = df_search.copy()
            view_df["거래금액"] = view_df["deal_amount"].apply(format_amount)
            view_df["평당가(만원)"] = view_df["price_per_pyeong"].apply(lambda x: f"{x:,.0f}")
            st.dataframe(
                view_df[
                    [
                        "deal_date",
                        "sido_nm",
                        "sgg_nm",
                        "umd_nm",
                        "apt_nm",
                        "exclu_use_ar",
                        "pyeong",
                        "floor",
                        "거래금액",
                        "평당가(만원)",
                        "build_year",
                        "dealing_gbn",
                    ]
                ].rename(
                    columns={
                        "deal_date": "계약일",
                        "sido_nm": "시도",
                        "sgg_nm": "시군구",
                        "umd_nm": "법정동",
                        "apt_nm": "단지명",
                        "exclu_use_ar": "전용면적(㎡)",
                        "pyeong": "평형",
                        "floor": "층",
                        "build_year": "건축년도",
                        "dealing_gbn": "거래유형",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("선택된 필터 조건에 일치하는 거래 내역이 없습니다.")


if __name__ == "__main__":
    main()
