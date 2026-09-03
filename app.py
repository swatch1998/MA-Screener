"""
Screener financiero para research de M&A.
Frontend Streamlit: busca un ticker o nombre de empresa y muestra estados
financieros, ratios y múltiplos obtenidos en vivo de yfinance.
"""

import pandas as pd
import streamlit as st

from data_fetcher import (
    CompanyData,
    DataFetchError,
    TickerNotFoundError,
    fetch_company_data,
    resolve_ticker,
)

st.set_page_config(page_title="M&A Screener", page_icon="📊", layout="wide")


def format_big_number(value):
    if value is None or value == "":
        return "N/D"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    abs_v = abs(value)
    if abs_v >= 1e12:
        return f"{value / 1e12:.2f}T"
    if abs_v >= 1e9:
        return f"{value / 1e9:.2f}B"
    if abs_v >= 1e6:
        return f"{value / 1e6:.2f}M"
    if abs_v >= 1e3:
        return f"{value / 1e3:.2f}K"
    return f"{value:.2f}"


def format_ratio_value(key: str, value):
    if value is None or value == "":
        return "N/D"
    # Campos que yfinance devuelve como fracción (0.33 == 33%) y hay que escalar x100.
    fraction_pct_keys = ("margin", "roe", "roa", "growth")
    # Campos que yfinance devuelve ya en puntos porcentuales (33.0 == 33%, no 3300%).
    already_pct_keys = ("yield", "debt/equity")
    big_keys = ("market cap", "enterprise value", "revenue", "ebitda", "debt", "cash")
    key_lower = key.lower()
    try:
        if any(p in key_lower for p in fraction_pct_keys):
            return f"{float(value) * 100:.2f}%"
        if any(p in key_lower for p in already_pct_keys):
            return f"{float(value):.2f}%"
        if any(b in key_lower for b in big_keys) and "growth" not in key_lower:
            return format_big_number(value)
        if isinstance(value, float):
            return f"{value:.2f}"
        return f"{value:,}" if isinstance(value, int) else str(value)
    except (TypeError, ValueError):
        return str(value)


def render_financial_table(df: pd.DataFrame, label: str):
    if df is None or df.empty:
        st.info(f"No hay datos de {label.lower()} disponibles para este ticker.")
        return
    display_df = df.copy()
    display_df.columns = [
        c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else str(c) for c in display_df.columns
    ]
    st.dataframe(display_df, use_container_width=True)


def render_ratios(data: CompanyData):
    ratios = data.ratios()
    debt_ebitda = data.debt_to_ebitda()
    if debt_ebitda is not None:
        ratios["Debt/EBITDA (calculado)"] = debt_ebitda

    cols = st.columns(4)
    for idx, (key, value) in enumerate(ratios.items()):
        with cols[idx % 4]:
            st.metric(key, format_ratio_value(key, value))


def render_header(data: CompanyData):
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title(f"{data.name} ({data.ticker})")
        st.caption(f"Sector: {data.sector}  |  Industria: {data.industry}")
    with col2:
        price = data.current_price
        price_str = f"{price:,.2f} {data.currency}" if price is not None else "N/D"
        st.metric("Precio actual", price_str)

    st.caption(f"Última actualización (fetch cacheado): {data.fetched_at.strftime('%Y-%m-%d %H:%M:%S')}")


def main():
    st.sidebar.header("Buscador")
    query = st.sidebar.text_input(
        "Ticker o nombre de empresa",
        placeholder="Ej: AAPL, Microsoft, Inditex...",
    )
    search_clicked = st.sidebar.button("Buscar", type="primary")

    if "current_ticker" not in st.session_state:
        st.session_state.current_ticker = None

    if search_clicked and query:
        with st.spinner("Resolviendo ticker..."):
            try:
                resolved = resolve_ticker(query)
            except DataFetchError as e:
                st.sidebar.error(str(e))
                resolved = None
        if resolved:
            st.session_state.current_ticker = resolved
        else:
            st.sidebar.error(f"No se pudo resolver '{query}' a un ticker válido.")

    ticker = st.session_state.current_ticker

    if not ticker:
        st.title("📊 M&A Screener")
        st.write(
            "Busca una empresa por ticker (ej. `AAPL`) o por nombre (ej. `Microsoft`) "
            "en la barra lateral para ver sus estados financieros y ratios."
        )
        return

    with st.spinner(f"Descargando datos de {ticker}..."):
        try:
            data = fetch_company_data(ticker)
        except TickerNotFoundError as e:
            st.error(str(e))
            return
        except DataFetchError as e:
            st.error(f"Fallo al obtener datos de yfinance: {e}")
            return

    render_header(data)

    period = st.radio("Periodo", ["Anual", "Trimestral"], horizontal=True)

    with st.expander("💰 Cuenta de resultados", expanded=True):
        df = data.income_annual if period == "Anual" else data.income_quarterly
        render_financial_table(df, "cuenta de resultados")

    with st.expander("🏦 Balance"):
        df = data.balance_annual if period == "Anual" else data.balance_quarterly
        render_financial_table(df, "balance")

    with st.expander("💵 Cash Flow"):
        df = data.cashflow_annual if period == "Anual" else data.cashflow_quarterly
        render_financial_table(df, "cash flow")

    with st.expander("📈 Ratios y múltiplos", expanded=True):
        render_ratios(data)


if __name__ == "__main__":
    main()
