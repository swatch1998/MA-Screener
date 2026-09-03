"""
Screener financiero para research de M&A.
Frontend Streamlit: busca un ticker o nombre de empresa y muestra gráfico de
precio, noticias, estados financieros y ratios, obtenidos en vivo de yfinance.
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

# Cada opción: (período de yfinance, intervalo de vela)
PRICE_RANGES = {
    "1D": ("1d", "5m"),
    "5D": ("5d", "15m"),
    "1M": ("1mo", "1d"),
    "6M": ("6mo", "1d"),
    "1A": ("1y", "1d"),
    "5A": ("5y", "1wk"),
    "Máx": ("max", "1mo"),
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


def period_label(col, period: str) -> str:
    """Etiqueta de columna: solo el año en Anual, fecha completa en Trimestral."""
    if hasattr(col, "strftime"):
        return col.strftime("%Y") if period == "Anual" else col.strftime("%Y-%m-%d")
    return str(col)


def collect_period_labels(dfs, period: str) -> list[str]:
    """Etiquetas únicas de periodo disponibles, en el orden en que aparecen (más reciente primero)."""
    labels: list[str] = []
    for df in dfs:
        if df is None or df.empty:
            continue
        for c in df.columns:
            lbl = period_label(c, period)
            if lbl not in labels:
                labels.append(lbl)
    return labels


def filter_columns_by_labels(df: pd.DataFrame, period: str, selected_labels: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    mask = [period_label(c, period) in selected_labels for c in df.columns]
    return df.loc[:, mask]


def format_financial_df(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Prepara la tabla para mostrar: cabeceras simplificadas y números con separador de miles."""
    display_df = df.copy()
    display_df.columns = [period_label(c, period) for c in display_df.columns]
    formatted = display_df.map(lambda v: format_big_number(v) if pd.notna(v) else "-")
    return formatted


def render_financial_table(df: pd.DataFrame, label: str, period: str, currency: str, key_prefix: str):
    if df is None or df.empty:
        st.info(f"No hay datos de {label.lower()} disponibles para el periodo seleccionado.")
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
    range_label = st.segmented_control(
        "Rango del gráfico", options=list(PRICE_RANGES.keys()), default="1A", key="price_range"
    )
    range_label = range_label or "1A"
    yf_period, yf_interval = PRICE_RANGES[range_label]

    try:
        hist = fetch_price_history(data.ticker, yf_period, yf_interval)
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
            "y pulsa Enter para ver su gráfico, noticias, estados financieros y ratios."
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

    with st.expander("📉 Evolución del precio", expanded=True):
        render_price_chart(data)

    with st.expander("📰 Noticias recientes", expanded=True):
        render_news(data)

    period = st.radio("Periodicidad de los estados financieros", ["Anual", "Trimestral"], horizontal=True)
    st.caption(
        "Nota: yfinance solo distingue periodicidad Anual y Trimestral — las empresas no publican "
        "cuentas mensuales, así que esa granularidad no existe como dato real."
    )

    income_df = data.income_annual if period == "Anual" else data.income_quarterly
    balance_df = data.balance_annual if period == "Anual" else data.balance_quarterly
    cashflow_df = data.cashflow_annual if period == "Anual" else data.cashflow_quarterly

    available_labels = collect_period_labels([income_df, balance_df, cashflow_df], period)
    if available_labels:
        selected_labels = st.multiselect(
            "Periodos a mostrar y descargar",
            options=available_labels,
            default=available_labels,
        )
    else:
        selected_labels = []

    income_df = filter_columns_by_labels(income_df, period, selected_labels)
    balance_df = filter_columns_by_labels(balance_df, period, selected_labels)
    cashflow_df = filter_columns_by_labels(cashflow_df, period, selected_labels)

    with st.expander("💰 Cuenta de resultados", expanded=True):
        render_financial_table(income_df, "Cuenta de resultados", period, data.currency, data.ticker)

    with st.expander("🏦 Balance"):
        render_financial_table(balance_df, "Balance", period, data.currency, data.ticker)

    with st.expander("💵 Cash Flow"):
        render_financial_table(cashflow_df, "Cash Flow", period, data.currency, data.ticker)

    with st.expander("📈 Ratios y múltiplos", expanded=True):
        render_ratios(data)


if __name__ == "__main__":
    main()
