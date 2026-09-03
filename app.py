"""
Screener financiero para research de M&A.
Frontend Streamlit: busca un ticker o nombre de empresa y muestra estados
financieros, ratios, gráfico de precio y noticias, obtenidos en vivo de yfinance.
"""

import io

import pandas as pd
import streamlit as st

from data_fetcher import (
    CompanyData,
    DataFetchError,
    TickerNotFoundError,
    fetch_company_data,
    fetch_company_news,
    fetch_price_history,
    resolve_ticker,
)

st.set_page_config(page_title="M&A Screener", page_icon="📊", layout="wide")

PRICE_PERIODS = {
    "1 mes": "1mo",
    "6 meses": "6mo",
    "1 año": "1y",
    "5 años": "5y",
    "Máximo": "max",
}


def format_big_number(value):
    """Formatea un número grande con separador de miles, sin abreviar."""
    if value is None or value == "":
        return "N/D"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


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
            return f"{value:,.2f}"
        return f"{value:,}" if isinstance(value, int) else str(value)
    except (TypeError, ValueError):
        return str(value)


def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Datos") -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name[:31])
    return buffer.getvalue()


def format_financial_df(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Prepara la tabla para mostrar: cabeceras simplificadas y números con separador de miles."""
    display_df = df.copy()
    if period == "Anual":
        # Solo el año, sin la fecha completa (día/mes son irrelevantes para el usuario).
        display_df.columns = [
            c.strftime("%Y") if hasattr(c, "strftime") else str(c) for c in display_df.columns
        ]
    else:
        display_df.columns = [
            c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else str(c) for c in display_df.columns
        ]
    formatted = display_df.map(
        lambda v: format_big_number(v) if pd.notna(v) else "-"
    )
    return formatted


def render_financial_table(df: pd.DataFrame, label: str, period: str, currency: str, key_prefix: str):
    if df is None or df.empty:
        st.info(f"No hay datos de {label.lower()} disponibles para este ticker.")
        return

    st.caption(f"Cifras en {currency}" if currency else "Divisa no disponible")
    formatted = format_financial_df(df, period)
    st.dataframe(formatted, use_container_width=True)

    excel_bytes = df_to_excel_bytes(df, sheet_name=label)
    st.download_button(
        label=f"⬇️ Descargar {label} (Excel)",
        data=excel_bytes,
        file_name=f"{key_prefix}_{label.lower().replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"download_{key_prefix}_{label}_{period}",
    )


def render_ratios(data: CompanyData):
    ratios = data.ratios()
    debt_ebitda = data.debt_to_ebitda()
    if debt_ebitda is not None:
        ratios["Debt/EBITDA (calculado)"] = debt_ebitda

    st.caption(f"Cifras monetarias en {data.currency}" if data.currency else "Divisa no disponible")

    cols = st.columns(4)
    for idx, (key, value) in enumerate(ratios.items()):
        with cols[idx % 4]:
            st.metric(key, format_ratio_value(key, value))

    ratios_df = pd.DataFrame(
        [{"Ratio": k, "Valor": v} for k, v in ratios.items()]
    ).set_index("Ratio")
    excel_bytes = df_to_excel_bytes(ratios_df, sheet_name="Ratios")
    st.download_button(
        label="⬇️ Descargar Ratios y múltiplos (Excel)",
        data=excel_bytes,
        file_name=f"{data.ticker}_ratios.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_ratios",
    )


def render_price_chart(data: CompanyData):
    period_label = st.select_slider(
        "Rango del gráfico", options=list(PRICE_PERIODS.keys()), value="1 año"
    )
    try:
        hist = fetch_price_history(data.ticker, PRICE_PERIODS[period_label])
    except DataFetchError as e:
        st.error(str(e))
        return

    if hist is None or hist.empty or "Close" not in hist.columns:
        st.info("No hay histórico de precio disponible para este ticker.")
        return

    st.caption(f"Precio de cierre en {data.currency}" if data.currency else "Divisa no disponible")
    st.line_chart(hist["Close"], use_container_width=True)


def render_news(data: CompanyData):
    try:
        news_items = fetch_company_news(data.ticker)
    except DataFetchError as e:
        st.error(str(e))
        return

    if not news_items:
        st.info("No se han encontrado noticias recientes para esta empresa.")
        return

    for item in news_items:
        title = item.get("title") or "(sin título)"
        link = item.get("link")
        publisher = item.get("publisher") or "Fuente desconocida"
        pub_date = item.get("pub_date") or ""
        summary = item.get("summary") or ""

        if link:
            st.markdown(f"**[{title}]({link})**")
        else:
            st.markdown(f"**{title}**")
        st.caption(f"{publisher} · {pub_date}")
        if summary:
            st.write(summary)
        st.divider()


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


def resolve_and_set_ticker(query: str):
    with st.spinner("Resolviendo ticker..."):
        try:
            resolved = resolve_ticker(query)
        except DataFetchError as e:
            st.session_state.search_error = str(e)
            return
    if resolved:
        st.session_state.current_ticker = resolved
        st.session_state.search_error = None
    else:
        st.session_state.search_error = f"No se pudo resolver '{query}' a un ticker válido."


def main():
    if "current_ticker" not in st.session_state:
        st.session_state.current_ticker = None
    if "last_query" not in st.session_state:
        st.session_state.last_query = ""
    if "search_error" not in st.session_state:
        st.session_state.search_error = None

    st.markdown("### 📊 M&A Screener")
    query = st.text_input(
        "Buscador",
        placeholder="Ticker o nombre de empresa (ej: AAPL, Microsoft, Inditex...) — pulsa Enter",
        label_visibility="collapsed",
    )

    if query and query != st.session_state.last_query:
        st.session_state.last_query = query
        resolve_and_set_ticker(query)

    if st.session_state.search_error:
        st.error(st.session_state.search_error)

    ticker = st.session_state.current_ticker

    if not ticker:
        st.write(
            "Busca una empresa por ticker (ej. `AAPL`) o por nombre (ej. `Microsoft`) "
            "y pulsa Enter para ver sus estados financieros, ratios, gráfico y noticias."
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
        render_financial_table(df, "Cuenta de resultados", period, data.currency, data.ticker)

    with st.expander("🏦 Balance"):
        df = data.balance_annual if period == "Anual" else data.balance_quarterly
        render_financial_table(df, "Balance", period, data.currency, data.ticker)

    with st.expander("💵 Cash Flow"):
        df = data.cashflow_annual if period == "Anual" else data.cashflow_quarterly
        render_financial_table(df, "Cash Flow", period, data.currency, data.ticker)

    with st.expander("📈 Ratios y múltiplos", expanded=True):
        render_ratios(data)

    with st.expander("📉 Evolución del precio", expanded=True):
        render_price_chart(data)

    with st.expander("📰 Noticias recientes"):
        render_news(data)


if __name__ == "__main__":
    main()
