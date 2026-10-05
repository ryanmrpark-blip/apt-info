"""일자별 아파트 매매 실거래가 상세 조회 전용 Streamlit 페이지.

이 모듈은 국토교통부 아파트 매매 실거래가 데이터베이스(SQLite 및 요약 테이블)와 연동하여
특정 계약 일자를 선택했을 때 당일의 핵심 KPI 지표, 시도별 거래량 및 평균가 분포 차트,
금액대별 비중 도넛 차트, 다차원 필터링이 가능한 상세 거래 목록 그리드 및 CSV 내보내기를 제공합니다.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# 상대 경로를 통한 모듈 참조 등록 (src 디렉토리를 sys.path에 안전하게 등록)
PAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PAGE_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from constants import SGG_CODE_MAP, SIDO_LIST
from db_queries import (
    get_available_deal_dates,
    get_day_price_bands,
    get_day_region_distribution,
    get_single_day_summary,
    get_trades_by_date,
)
from storage import DEFAULT_DB_PATH, init_db, sync_daily_summary
from utils import resolve_relative_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def format_amount(amount_manwon: int) -> str:
    """만원 단위 숫자를 한글 억/만원 단위 문자열로 가독성 있게 포맷팅합니다.

    Args:
        amount_manwon (int): 만원 단위 거래금액 (예: 280000).

    Returns:
        str: 가독성 높은 한글 금액 문자열 (예: '28억 원', '12억 5,400만 원').
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


def render_daily_detail_page() -> None:
    """일자별 상세 거래내역 및 요약 분석 화면을 렌더링합니다."""
    st.set_page_config(
        page_title="일자별 아파트 실거래가 상세",
        page_icon="📅",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # 1. 헤더 타이틀 및 설명 영역
    st.title("📅 일자별 아파트 매매 실거래가 상세 분석")
    st.caption("특정 계약일자를 선택하여 당일의 전국 실거래 핵심 KPI, 시도별 분포, 가격대 비중 및 상세 거래 목록을 심층 조회합니다.")

    # DB 초기화 점검
    init_db()

    # 2. 거래 데이터 존재 일자 목록 조회
    available_dates = get_available_deal_dates()

    if not available_dates:
        st.warning("⚠️ 저장된 아파트 실거래가 데이터가 없습니다.")
        st.info("메인 대시보드 또는 CLI(`uv run python src/main.py --fetch`)를 통해 먼저 실거래가 데이터를 수집해 주세요.")
        if st.button("🔄 요약 데이터 강제 동기화 시도"):
            count = sync_daily_summary()
            st.success(f"동기화 완료: {count}개 일자 요약이 생성되었습니다.")
            st.rerun()
        return

    # 3. 상단 일자 선택 및 관리 컨트롤 바
    if "selected_deal_date" not in st.session_state or st.session_state["selected_deal_date"] not in available_dates:
        st.session_state["selected_deal_date"] = available_dates[0]

    st.markdown("#### ⚡ 최근 주요 거래일 바로가기")
    quick_col_count = min(len(available_dates), 5)
    quick_cols = st.columns(quick_col_count)
    for idx in range(quick_col_count):
        d_val = available_dates[idx]
        with quick_cols[idx]:
            btn_label = f"📌 {d_val}" if d_val == st.session_state["selected_deal_date"] else d_val
            if st.button(btn_label, key=f"quick_date_{d_val}", use_container_width=True):
                st.session_state["selected_deal_date"] = d_val
                st.rerun()

    st.divider()

    # 셀렉터 및 동기화 버튼 배치
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([3, 2, 2])
    with ctrl_col1:
        date_index = available_dates.index(st.session_state["selected_deal_date"]) if st.session_state["selected_deal_date"] in available_dates else 0
        selected_date = st.selectbox(
            "조회할 계약 일자 선택",
            options=available_dates,
            index=date_index,
            help="데이터베이스에 실거래가가 기록된 일자 목록입니다.",
        )
        if selected_date != st.session_state["selected_deal_date"]:
            st.session_state["selected_deal_date"] = selected_date
            st.rerun()

    with ctrl_col2:
        st.write("")
        st.write("")
        if st.button("🔄 SQLite 요약 데이터 동기화", use_container_width=True, help="기존 거래 데이터를 기반으로 daily_trade_summary 테이블을 즉시 최신화합니다."):
            with st.spinner("일자별 요약 집계를 갱신 중입니다..."):
                updated = sync_daily_summary()
                st.success(f"요약 동기화 완료 ({updated}개 일자 반영)")
                st.rerun()

    with ctrl_col3:
        st.write("")
        st.write("")
        st.caption(f"총 {len(available_dates)}개 일자 데이터 관리 중")

    selected_date = st.session_state["selected_deal_date"]

    # 4. 당일 요약 통계(KPI) 카드 표출
    summary = get_single_day_summary(selected_date)

    if not summary or summary.get("total_trades", 0) == 0:
        st.info(f"선택하신 일자({selected_date})에는 거래 내역이 존재하지 않습니다.")
        return

    st.markdown(f"### 📊 {selected_date} 거래 핵심 요약")
    kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5 = st.columns(5)

    with kpi_col1:
        st.metric(
            label="당일 총 거래건수",
            value=f"{summary['total_trades']:,} 건",
            help="해당 일자에 신고된 정상 유효 거래 총합",
        )
    with kpi_col2:
        st.metric(
            label="당일 총 거래대금",
            value=format_amount(summary["total_amount"]),
            help="당일 실거래 금액의 단순 합계",
        )
    with kpi_col3:
        st.metric(
            label="건당 평균 거래가",
            value=format_amount(int(summary.get("avg_amount", 0))),
            help="당일 발생한 거래의 평균 매매가",
        )
    with kpi_col4:
        avg_pyeong = int(summary.get("avg_price_per_pyeong", 0))
        st.metric(
            label="평균 평당 가격",
            value=f"{avg_pyeong:,}만 원" if avg_pyeong > 0 else "0원",
            help="전용면적 환산 평당 매매 가격",
        )
    with kpi_col5:
        max_apt = summary.get("max_apt_name", "-")
        max_amt = summary.get("max_amount", 0)
        st.metric(
            label="당일 최고가 단지",
            value=format_amount(max_amt),
            delta=max_apt[:10] + ("..." if len(max_apt) > 10 else ""),
            help=f"단지명: {max_apt} ({summary.get('max_sgg_nm', '')})",
        )

    st.divider()

    # 5. 시각화 분석 영역 (2단 차트)
    chart_col1, chart_col2 = st.columns([1, 1])

    with chart_col1:
        st.subheader("🏙️ 시도별 거래 건수 및 평균가")
        df_region = get_day_region_distribution(selected_date)
        if not df_region.empty:
            fig_bar = px.bar(
                df_region,
                x="sido_nm",
                y="trade_count",
                text="trade_count",
                color="avg_amount",
                labels={"sido_nm": "시도", "trade_count": "거래 건수 (건)", "avg_amount": "평균 거래가 (만원)"},
                color_continuous_scale="Blues",
                title=f"{selected_date} 지역별 거래량 및 평균 매매가",
            )
            fig_bar.update_layout(
                xaxis_title="",
                yaxis_title="거래 건수",
                height=380,
                margin=dict(l=20, r=20, t=50, b=20),
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("지역별 데이터가 없습니다.")

    with chart_col2:
        st.subheader("💰 금액대별 거래 비중")
        df_bands = get_day_price_bands(selected_date)
        if not df_bands.empty:
            fig_donut = px.pie(
                df_bands,
                names="price_band",
                values="count",
                hole=0.45,
                title=f"{selected_date} 가격대별 거래 분포",
                color="price_band",
                color_discrete_map={
                    "3억 이하": "#4575b4",
                    "3억~6억": "#74add1",
                    "6억~9억": "#fee090",
                    "9억~15억": "#f46d43",
                    "15억 초과": "#d73027",
                },
            )
            fig_donut.update_traces(textposition="inside", textinfo="percent+label")
            fig_donut.update_layout(
                height=380,
                margin=dict(l=20, r=20, t=50, b=20),
                showlegend=True,
            )
            st.plotly_chart(fig_donut, use_container_width=True)
        else:
            st.info("금액대별 데이터가 없습니다.")

    st.divider()

    # 6. 상세 거래내역 및 다차원 필터링 영역
    st.subheader(f"📋 {selected_date} 상세 실거래 목록")

    # 필터 컨트롤 (가로 4열 배치)
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        sido_opts = ["전체"] + SIDO_LIST
        filter_sido = st.selectbox("시도 필터", options=sido_opts, index=0)

    with f_col2:
        available_sgg_opts = ["전체"]
        if filter_sido != "전체":
            for info in SGG_CODE_MAP.values():
                if info.get("sido") == filter_sido:
                    available_sgg_opts.append(info.get("sgg", ""))
            available_sgg_opts = ["전체"] + sorted(list(set(available_sgg_opts[1:])))
        filter_sgg = st.selectbox("시군구 필터", options=available_sgg_opts, index=0)

    with f_col3:
        filter_apt = st.text_input("아파트 단지명 검색", placeholder="예: 자이, 힐스테이트")

    with f_col4:
        amount_range_eok = st.slider("금액 범위 (억원)", min_value=0.0, max_value=60.0, value=(0.0, 60.0), step=1.0)

    # 필터 적용 쿼리 호출
    min_amt_filter = int(amount_range_eok[0] * 10000) if amount_range_eok[0] > 0 else None
    max_amt_filter = int(amount_range_eok[1] * 10000) if amount_range_eok[1] < 60.0 else None

    df_trades = get_trades_by_date(
        deal_date=selected_date,
        sido_filter=filter_sido,
        sgg_filter=filter_sgg,
        min_amount=min_amt_filter,
        max_amount=max_amt_filter,
        apt_search=filter_apt,
    )

    if df_trades.empty:
        st.warning("선택하신 조건에 부합하는 실거래 내역이 없습니다. 필터 조건을 변경해 보세요.")
    else:
        # 사용자 가독성을 위한 컬럼 정제 및 한글 금액 추가
        display_df = df_trades.copy()
        display_df["거래금액_한글"] = display_df["deal_amount"].apply(format_amount)
        display_df["평당가격_만"] = display_df["price_per_pyeong"].apply(lambda x: f"{int(x):,}만 원" if x > 0 else "-")

        columns_order = [
            "sido_nm",
            "sgg_nm",
            "umd_nm",
            "apt_nm",
            "exclu_use_ar",
            "pyeong",
            "floor",
            "deal_amount",
            "거래금액_한글",
            "평당가격_만",
            "build_year",
            "dealing_gbn",
        ]
        columns_rename = {
            "sido_nm": "시도",
            "sgg_nm": "시군구",
            "umd_nm": "읍면동",
            "apt_nm": "아파트 단지명",
            "exclu_use_ar": "전용면적(㎡)",
            "pyeong": "평형",
            "floor": "층",
            "deal_amount": "거래금액(만원)",
            "거래금액_한글": "거래금액",
            "평당가격_만": "평당가",
            "build_year": "건축년도",
            "dealing_gbn": "거래유형",
        }

        valid_cols = [c for c in columns_order if c in display_df.columns]
        render_table = display_df[valid_cols].rename(columns=columns_rename)

        st.caption(f"총 {len(render_table):,}건의 거래가 조회되었습니다.")
        st.dataframe(render_table, use_container_width=True, height=450)

        # CSV 내보내기 다운로드 버튼
        csv_data = render_table.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            label=f"📥 {selected_date} 거래내역 CSV 다운로드",
            data=csv_data,
            file_name=f"apt_trades_{selected_date}.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    render_daily_detail_page()
