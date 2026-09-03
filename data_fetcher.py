"""
Capa de datos del screener financiero.

Descarga estados financieros y ratios desde yfinance para un ticker dado,
con cacheo (TTL 15 min) para evitar golpear la API en cada recarga de Streamlit.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import streamlit as st
import yfinance as yf

CACHE_TTL_SECONDS = 15 * 60  # 15 minutos


class TickerNotFoundError(Exception):
    """El ticker no existe o yfinance no devolvió datos utilizables."""


class DataFetchError(Exception):
    """Fallo al contactar con yfinance (timeout, rate limit, etc.)."""


@dataclass
class CompanyData:
    ticker: str
    info: dict = field(default_factory=dict)
    income_annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    income_quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance_annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance_quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow_annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow_quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)
    fetched_at: dt.datetime = field(default_factory=dt.datetime.now)

    @property
    def name(self) -> str:
        return self.info.get("longName") or self.info.get("shortName") or self.ticker

    @property
    def sector(self) -> str:
        return self.info.get("sector", "N/D")

    @property
    def industry(self) -> str:
        return self.info.get("industry", "N/D")

    @property
    def currency(self) -> str:
        return self.info.get("currency", "")

    @property
    def current_price(self) -> Optional[float]:
        return (
            self.info.get("currentPrice")
            or self.info.get("regularMarketPrice")
            or self.info.get("previousClose")
        )

    def ratios(self) -> dict:
        """Extrae del .info un subconjunto de ratios/múltiplos relevantes para M&A."""
        i = self.info
        return {
            "Market Cap": i.get("marketCap"),
            "Enterprise Value": i.get("enterpriseValue"),
            "P/E (trailing)": i.get("trailingPE"),
            "P/E (forward)": i.get("forwardPE"),
            "PEG ratio": i.get("pegRatio"),
            "Price/Sales": i.get("priceToSalesTrailing12Months"),
            "Price/Book": i.get("priceToBook"),
            "EV/Revenue": i.get("enterpriseToRevenue"),
            "EV/EBITDA": i.get("enterpriseToEbitda"),
            "Gross margin": i.get("grossMargins"),
            "Operating margin": i.get("operatingMargins"),
            "EBITDA margin": i.get("ebitdaMargins"),
            "Net margin": i.get("profitMargins"),
            "ROE": i.get("returnOnEquity"),
            "ROA": i.get("returnOnAssets"),
            "Debt/Equity": i.get("debtToEquity"),
            "Current ratio": i.get("currentRatio"),
            "Quick ratio": i.get("quickRatio"),
            "Revenue growth (YoY)": i.get("revenueGrowth"),
            "Earnings growth (YoY)": i.get("earningsGrowth"),
            "Dividend yield": i.get("dividendYield"),
            "Beta": i.get("beta"),
            "Shares outstanding": i.get("sharesOutstanding"),
            "Total revenue (ttm)": i.get("totalRevenue"),
            "EBITDA (ttm)": i.get("ebitda"),
            "Total debt": i.get("totalDebt"),
            "Total cash": i.get("totalCash"),
        }

    def debt_to_ebitda(self) -> Optional[float]:
        """Deuda/EBITDA no viene directo en .info; se calcula si hay datos suficientes."""
        total_debt = self.info.get("totalDebt")
        ebitda = self.info.get("ebitda")
        if total_debt is None or not ebitda:
            return None
        try:
            return total_debt / ebitda
        except (TypeError, ZeroDivisionError):
            return None


def _safe_df(df) -> pd.DataFrame:
    """yfinance a veces devuelve None; normalizamos a DataFrame vacío."""
    if df is None:
        return pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    return df


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_company_data(ticker: str) -> CompanyData:
    """
    Descarga toda la información financiera de un ticker desde yfinance.

    Lanza TickerNotFoundError si el ticker no existe o no devuelve datos básicos.
    Lanza DataFetchError ante fallos de red/rate limit de yfinance.
    """
    ticker = ticker.strip().upper()
    if not ticker:
        raise TickerNotFoundError("Ticker vacío.")

    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}
    except Exception as e:
        raise DataFetchError(f"Error al contactar yfinance para '{ticker}': {e}") from e

    # yfinance no lanza excepción con tickers inválidos: devuelve un info casi vacío.
    has_name = bool(info.get("longName") or info.get("shortName"))
    has_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    if not has_name and not has_price:
        raise TickerNotFoundError(f"No se encontraron datos para el ticker '{ticker}'.")

    try:
        income_annual = _safe_df(tk.income_stmt)
        income_quarterly = _safe_df(tk.quarterly_income_stmt)
        balance_annual = _safe_df(tk.balance_sheet)
        balance_quarterly = _safe_df(tk.quarterly_balance_sheet)
        cashflow_annual = _safe_df(tk.cashflow)
        cashflow_quarterly = _safe_df(tk.quarterly_cashflow)
    except Exception as e:
        raise DataFetchError(
            f"Error al descargar estados financieros de '{ticker}': {e}"
        ) from e

    return CompanyData(
        ticker=ticker,
        info=info,
        income_annual=income_annual,
        income_quarterly=income_quarterly,
        balance_annual=balance_annual,
        balance_quarterly=balance_quarterly,
        cashflow_annual=cashflow_annual,
        cashflow_quarterly=cashflow_quarterly,
        fetched_at=dt.datetime.now(),
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def resolve_ticker(query: str) -> Optional[str]:
    """
    Resuelve un nombre de empresa (o ticker ya válido) a un ticker de yfinance
    usando la búsqueda de Yahoo Finance. Si `query` ya es un ticker válido, se
    devuelve tal cual sin gastar una llamada de búsqueda.
    """
    query = query.strip()
    if not query:
        return None

    # Si ya parece (y funciona como) un ticker, úsalo directamente.
    try:
        tk = yf.Ticker(query.upper())
        info = tk.info or {}
        if info.get("longName") or info.get("shortName") or info.get("regularMarketPrice"):
            return query.upper()
    except Exception:
        pass

    # Si no, buscar por nombre de empresa.
    try:
        results = yf.Search(query, max_results=5).quotes
    except Exception as e:
        raise DataFetchError(f"Error al buscar '{query}': {e}") from e

    if not results:
        return None

    # Preferir resultados de tipo equity.
    for r in results:
        if r.get("quoteType") == "EQUITY" and r.get("symbol"):
            return r["symbol"]

    return results[0].get("symbol")
