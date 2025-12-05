import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta

# --- 페이지 설정 ---
st.set_page_config(page_title="고배당 마스터 시뮬레이터 (Pro)", layout="wide")

# --- 스타일링 ---
st.markdown("""
<style>
    .big-font { font-size: 24px !important; font-weight: bold; }
    .stInput > label { font-weight: bold; font-size: 1.05rem; }
    .highlight-box { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #6366f1; }
    .evidence-box { background-color: #fff; border: 1px solid #ddd; padding: 15px; border-radius: 8px; margin-top: 10px; }
    .metric-card { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 15px; box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05); }
</style>
""", unsafe_allow_html=True)

st.title("💸 고배당 마스터 시뮬레이터 (Pro)")
st.markdown("배당 주기를 **자유롭게 변경**하여 미래 수익을 예측해보세요.")

# --- 데이터 로딩 및 분석 함수 ---
@st.cache_data
def get_market_analysis(ticker, period_years):
    stock = yf.Ticker(ticker)
    
    # 1. 주식 데이터 (기간 연동)
    period_str = f"{period_years}y"
    history = stock.history(period=period_str)
    
    is_data_short = False
    actual_years = 0
    
    if history.empty:
        # 데이터가 아예 없으면 max로 재시도
        history = stock.history(period="max")
        is_data_short = True
    
    if not history.empty:
        days_diff = (history.index[-1] - history.index[0]).days
        actual_years = days_diff / 365
        if actual_years < (period_years * 0.8):
            is_data_short = True
        current_price_usd = history['Close'].iloc[-1]
    else:
        current_price_usd = 0
        actual_years = 0

    # 월간 수익률(CAGR) 계산
    if not history.empty:
        monthly_prices = history['Close'].resample('ME').last()
        monthly_returns = monthly_prices.pct_change().dropna()
        avg_monthly_change = monthly_returns.mean() * 100
    else:
        avg_monthly_change = 0

    # 2. 배당 데이터 (최근 1년치 합계 계산 - 연배당률 산정용)
    dividends = stock.dividends
    
    # Timezone 제거 및 최근 1년 데이터 필터링
    if len(dividends) > 0:
        dividends.index = dividends.index.tz_convert(None)
        last_date = dividends.index[-1]
        one_year_ago = last_date - timedelta(days=365)
        last_1y_dividends = dividends[dividends.index >= one_year_ago]
        
        # 최근 1년간 지급된 배당금 총합 (연 배당금)
        annual_div_sum = last_1y_dividends.sum()
        
        # 만약 최근 1년 데이터가 없다면 전체 평균 * 12 (예외처리)
        if annual_div_sum == 0 and len(dividends) > 0:
             annual_div_sum = dividends.mean() * 12
    else:
        annual_div_sum = 0
        
    recent_div_display = dividends.tail(12).sort_index(ascending=False)

    # 3. 환율 데이터
    try:
        exchange = yf.Ticker("KRW=X")
        exchange_rate = exchange.history(period="1d")['Close'].iloc[-1]
    except:
        exchange_rate = 1300.0 # 예외 시 기본값

    return current_price_usd, annual_div_sum, exchange_rate, avg_monthly_change, is_data_short, actual_years, history, recent_div_display

# --- 사이드바: 설정 ---
with st.sidebar:
    st.header("1. 종목 설정")
    ticker_symbol = st.text_input("티커 (Ticker)", value="TSLY")
    
    st.divider()
    st.header("2. 배당 주기 설정")
    # [NEW] 배당 주기 선택 기능
    div_freq_option = st.selectbox(
        "배당 지급 주기 선택", 
        ["월배당 (기본)", "주배당", "분기배당", "반기배당", "연배당"],
        index=0
    )
    
    # 주기별 연간 지급 횟수 및 시뮬레이션 간격(개월) 매핑
    freq_map = {
        "주배당": {"count": 52, "interval": 1, "desc": "월 4.3회분 반영"}, # 시뮬레이션은 월 단위라 근사치 사용
        "월배당 (기본)": {"count": 12, "interval": 1, "desc": "매월 지급"},
        "분기배당": {"count": 4, "interval": 3, "desc": "3개월마다 지급"},
        "반기배당": {"count": 2, "interval": 6, "desc": "6개월마다 지급"},
        "연배당": {"count": 1, "interval": 12, "desc": "1년마다 지급"},
    }
    selected_freq = freq_map[div_freq_option]

    st.caption(f"ℹ️ {div_freq_option}: {selected_freq['desc']}")

    if st.button("🔄 데이터/추세 새로고침"):
        st.cache_data.clear()

    st.divider()
    
    st.header("3. 기간 및 세금")
    years = st.slider("분석 및 투자 기간 (년)", 1, 10, 3)
    tax_rate = st.number_input("배당소득세율 (%)", value=15.0, step=0.1)

# --- 메인 로직 ---
try:
    with st.spinner(f"{ticker_symbol} 데이터를 분석 중입니다..."):
        # 함수에서 annual_div_sum(연간 총 배당금)을 받아옵니다.
        price_usd, annual_div_usd, rate, calculated_change_rate, is_short, real_years, history_df, div_df = get_market_analysis(ticker_symbol, years)

    price_krw = price_usd * rate
    
    # [핵심 로직] 선택한 주기에 따른 1회당 배당금 계산
    # 연간 총 배당금을 사용자가 선택한 주기의 횟수로 나눔
    if selected_freq["count"] == 52: # 주배당
        # 월 단위 시뮬레이션이므로, 한 달에 받는 총량으로 환산 (연배당 / 12)
        div_per_payout_krw = (annual_div_usd * rate) / 12 
        is_weekly_mode = True
    else:
        div_per_payout_krw = (annual_div_usd * rate) / selected_freq["count"]
        is_weekly_mode = False

    # 연 배당률 계산
    current_yield = (annual_div_usd / price_usd * 100) if price_usd > 0 else 0
    
    # 사이드바 결과
    with st.sidebar:
        st.write("---")
        st.subheader("📉 데이터 분석 요약")
        if is_short:
            st.warning(f"⚠️ 데이터 부족: 약 {real_years:.1f}년치 사용")
        
        emoji = "📈" if calculated_change_rate > 0 else "📉"
        real_change_rate = st.number_input(
            f"{emoji} 월평균 등락률 (자동)", 
            value=float(f"{calculated_change_rate:.2f}"), 
            step=0.1, format="%.2f"
        )
        st.caption("이 값을 조정하면 시뮬레이션에 반영됩니다.")

    # 상단 요약
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("현재 주가", f"{price_krw:,.0f} 원")
    
    # 배당금 표시 (선택한 주기에 따라 다르게 표시)
    div_label = "월 환산 배당" if is_weekly_mode else f"1회당 배당 ({div_freq_option.split()[0]})"
    col2.metric(div_label, f"{div_per_payout_krw:,.0f} 원", f"연수익률 {current_yield:.1f}%")
    
    col3.metric("환율", f"{rate:,.0f} 원/$")
    col4.metric("적용 추세", f"{real_change_rate:+.2f}%")

    # 근거 펼쳐보기
    with st.expander("📊 데이터 산출 근거 상세 보기 (클릭)", expanded=False):
        tab_ev1, tab_ev2 = st.tabs(["📉 주가 추세 근거", "💰 배당금 내역"])
        with tab_ev1:
            st.line_chart(history_df['Close'])
            st.caption(f"최근 {years}년 주가 흐름을 분석하여 월평균 변동률 {real_change_rate:.2f}%를 도출했습니다.")
        with tab_ev2:
            st.dataframe(div_df, use_container_width=True)
            st.caption(f"* 최근 1년 총 배당금 합계(USD): ${annual_div_usd:.2f}")

    st.write("") 

    # 탭 구성
    tab1, tab2 = st.tabs(["📊 수익 예측 (시뮬레이션)", "🎯 목표 금액 역산 & 월 적립 계획"])

    # ==============================================================================
    # TAB 1: 수익 예측 시뮬레이션
    # ==============================================================================
    with tab1:
        st.subheader(f"💰 {div_freq_option} 기준 시뮬레이션")
        c1, c2 = st.columns(2)
        initial_invest_input = c1.number_input("초기 투자금 (만원)", value=1000, step=100, key="sim_init")
        monthly_contrib_input = c2.number_input("매달 추가 납입 (만원)", value=50, step=10, key="sim_monthly")
        
        initial_invest_krw = initial_invest_input * 10000
        monthly_contrib_krw = monthly_contrib_input * 10000
        
        if st.button("🚀 수익률 예측하기", type="primary"):
            months = years * 12
            current_shares = initial_invest_krw / price_krw
            current_price = price_krw
            total_invested = initial_invest_krw 
            accumulated_div = 0 
            
            data_asset = []    
            data_invested = [] 
            data_labels = []
            break_even_month = None

            # 시뮬레이션 루프 (월 단위)
            for i in range(months + 1):
                # 0개월차 초기값 세팅
                if i == 0:
                    data_asset.append(int(current_shares * current_price))
                    data_invested.append(total_invested)
                    data_labels.append("시작")
                    continue
                
                # --- 배당 지급 로직 (주기 반영) ---
                gross_div = 0
                
                if is_weekly_mode:
                    # 주배당: 월 단위 근사치로 매달 지급 (연배당/12)
                    gross_div = current_shares * div_per_payout_krw
                else:
                    # 월/분기/반기/연: 해당 주기에만 지급
                    interval = selected_freq["interval"]
                    # 현재 월(i)이 주기의 배수일 때 지급 (예: 분기면 3, 6, 9월...)
                    if i % interval == 0:
                        gross_div = current_shares * div_per_payout_krw
                
                net_div = gross_div * (1 - tax_rate/100)
                accumulated_div += net_div

                # 멘징 체크
                if break_even_month is None and accumulated_div >= total_invested:
                    break_even_month = i

                # --- 자산 변동 및 재투자 ---
                current_price = current_price * (1 + real_change_rate/100)
                
                # 매수 자금 = (받은 배당금) + (월 적립금)
                buy_amount = net_div + monthly_contrib_krw
                new_shares = buy_amount / current_price
                current_shares += new_shares
                total_invested += monthly_contrib_krw
                
                asset_value = int(current_shares * current_price)
                data_asset.append(asset_value)
                data_invested.append(total_invested)
                data_labels.append(f"{i}개월")

            # 그래프
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=data_labels, y=data_asset, mode='lines', name='평가 자산', fill='tozeroy', line=dict(color='#6366f1', width=3)))
            fig.add_trace(go.Scatter(x=data_labels, y=data_invested, mode='lines', name='투입 원금', line=dict(color='#9ca3af', dash='dot')))
            fig.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20), hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

            # 결과 계산
            final_asset = data_asset[-1]
            final_invested = data_invested[-1]
            total_profit = final_asset - final_invested
            roi = (total_profit / final_invested) * 100
            price_impact = total_profit - accumulated_div

            # 1. 핵심 요약 카드
            rc1, rc2, rc3 = st.columns(3)
            with rc1:
                st.markdown(f"""<div class="highlight-box"><div style="color:gray;">총 투입 원금</div><div style="font-size:1.5rem; font-weight:bold;">{final_invested/10000:,.0f} 만원</div></div>""", unsafe_allow_html=True)
            with rc2:
                color = "#ef4444" if total_profit < 0 else "#22c55e"
                st.markdown(f"""<div class="highlight-box" style="border-left-color:{color};"><div style="color:gray;">최종 평가 자산</div><div style="font-size:1.5rem; font-weight:bold; color:{color};">{final_asset/10000:,.0f} 만원</div></div>""", unsafe_allow_html=True)
            with rc3:
                st.markdown(f"""<div class="highlight-box" style="border-left-color:#3b82f6;"><div style="color:gray;">최종 수익률</div><div style="font-size:1.5rem; font-weight:bold; color:#3b82f6;">{roi:+.2f}%</div></div>""", unsafe_allow_html=True)

            st.write("")

            # 2. 상세 분석 섹션
            st.info(f"🔍 **수익 상세 ({div_freq_option} 기준)**")
            d1, d2 = st.columns(2)
            with d1:
                st.metric(label="💰 기간 내 받은 총 배당금 (세후)", value=f"{accumulated_div:,.0f} 원", help="재투자된 금액 포함")
            with d2:
                p_color = "inverse" if price_impact > 0 else "normal"
                st.metric(label="📉 주가 변동 손익", value=f"{price_impact:,.0f} 원", delta_color=p_color)

            # 3. 멘징 메시지
            if break_even_month:
                st.success(f"🎉 **원금 회수(Free Ride) 달성!**\n투자 시작 후 **{break_even_month}개월** 만에 배당금 누적액이 내 원금을 넘어섰습니다.")
            else:
                st.warning(f"⚠️ **원금 회수 미달성**\n{years}년 동안 배당금이 원금 증가 속도를 따라잡지 못했습니다.")

    # ==============================================================================
    # TAB 2: 목표 계산
    # ==============================================================================
    with tab2:
        st.subheader("🎯 목표를 달성하려면 얼마가 필요할까?")
        st.markdown(f"설정한 **{years}년 뒤**에 원하는 **월 평균 수령액**을 받기 위한 플랜입니다.")
        
        target_monthly_div_input = st.number_input("목표 월 배당금 (만원)", value=100, step=10, help="세후 기준으로 매달(혹은 월 환산으로) 받고 싶은 금액")
        
        if st.button("🧮 필요 자금 및 월 적립액 계산", type="primary"):
            future_months = years * 12
            
            # 미래 주가 및 배당 예측 (월 추세 반영)
            decay_factor = (1 + real_change_rate/100) ** future_months
            est_future_price = price_krw * decay_factor
            
            # 미래의 '연간' 배당금 예측 (주당)
            current_annual_dps = annual_div_usd * rate
            est_future_annual_dps = current_annual_dps * decay_factor
            
            # 목표 금액 (월 * 12 = 연간 목표 배당금)
            target_annual_div_won = target_monthly_div_input * 10000 * 12
            
            if est_future_annual_dps <= 0:
                 st.error("⚠️ 예상 배당금이 0원이 되어 계산할 수 없습니다. 주가 하락률을 조정하세요.")
            else:
                # 필요 주식 수 = 연간 목표 배당금 / (미래의 주당 연배당금 * 세후)
                needed_shares = target_annual_div_won / (est_future_annual_dps * (1 - tax_rate/100))
                needed_asset_future = needed_shares * est_future_price
                
                # 월 수익률 계산 (Total Return)
                # 월 환산 배당수익률
                monthly_yield_rate = (current_annual_dps / 12) / price_krw * 100
                total_monthly_return_rate = (real_change_rate + monthly_yield_rate) / 100
                
                # 적립액 계산 (연금 미래가치 역산 공식)
                if total_monthly_return_rate == 0:
                    monthly_savings_needed = needed_asset_future / future_months
                else:
                    monthly_savings_needed = needed_asset_future * total_monthly_return_rate / ((1 + total_monthly_return_rate)**future_months - 1)
                
                st.divider()
                st.markdown(f"""
                <div style="text-align: center; padding: 25px; background-color: #f0f7ff; border-radius: 15px; border: 2px solid #3b82f6; margin-bottom: 20px;">
                    <div style="color: #6b7280; font-size: 1.1rem; margin-bottom: 5px;">{years}년 뒤, 월 {target_monthly_div_input}만원(연 {target_monthly_div_input*12:,}만원)을 받으려면</div>
                    <div style="color: #1d4ed8; font-size: 2.5rem; font-weight: bold;">{needed_asset_future/10000:,.0f} 만원</div>
                    <div style="color: #6b7280; font-size: 0.9rem;">만큼의 계좌 잔고(평가금)가 있어야 합니다.</div>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown(f"""
                <div style="text-align: center; padding: 25px; background-color: #fff1f2; border-radius: 15px; border: 2px solid #e11d48;">
                    <div style="color: #6b7280; font-size: 1.1rem; margin-bottom: 5px;">🔥 당장 이번 달부터</div>
                    <div style="color: #be123c; font-size: 2.5rem; font-weight: bold;">월 {monthly_savings_needed/10000:,.0f} 만원씩</div>
                    <div style="color: #6b7280; font-size: 0.9rem;">종목을 매수하고 배당을 재투자해야 합니다.</div>
                </div>
                """, unsafe_allow_html=True)
                
                with st.expander("📌 참고: 배당 주기에 따른 실제 수령액"):
                    per_payout_target = (target_monthly_div_input * 12) / selected_freq["count"]
                    st.write(f"현재 **{div_freq_option}** 설정을 기준으로 하면, 목표 달성 시")
                    st.write(f"**{selected_freq['desc']}** 때마다 **약 {per_payout_target:,.0f} 만원 (세후)** 씩 입금됩니다.")

except Exception as e:
    st.error("데이터를 불러오는 중 오류가 발생했습니다. 티커를 확인하거나 잠시 후 다시 시도해주세요.")
    st.error(f"Error Details: {e}")