
import os
import time
import requests
import pandas as pd
import streamlit as st
import xml.etree.ElementTree as ET
from io import StringIO, BytesIO

st.set_page_config(page_title="IBKR Power BI API", layout="wide")
st.title("📊 IBKR → Power BI API")

IBKR_TOKEN = os.getenv("IBKR_TOKEN", "")
IBKR_QUERY_ID = os.getenv("IBKR_QUERY_ID", "")

SEND_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
GET_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"

@st.cache_data(ttl=3600)
def download_ibkr_xml(token: str, query_id: str) -> bytes:
    if not token or not query_id:
        raise ValueError("Faltan variables IBKR_TOKEN o IBKR_QUERY_ID en Railway.")

    # 1) Solicitar statement
    r1 = requests.get(SEND_URL, params={"t": token, "q": query_id, "v": "3"}, timeout=60)
    r1.raise_for_status()

    root = ET.fromstring(r1.content)
    status = root.findtext("Status")
    if status != "Success":
        raise RuntimeError(f"IBKR SendRequest no fue Success: {r1.text[:1000]}")

    ref = root.findtext("ReferenceCode")
    if not ref:
        raise RuntimeError(f"No se recibió ReferenceCode: {r1.text[:1000]}")

    # Pequeña espera por si IBKR tarda en preparar el fichero
    time.sleep(2)

    # 2) Descargar statement
    r2 = requests.get(GET_URL, params={"t": token, "q": ref, "v": "3"}, timeout=60)
    r2.raise_for_status()
    return r2.content

def xml_to_flat_tables(xml_bytes: bytes):
    """
    Convierte el XML de IBKR en tablas simples.
    Como las secciones IBKR pueden variar según tu Flex Query,
    se extraen nodos habituales y se normaliza lo que exista.
    """
    root = ET.fromstring(xml_bytes)
    rows_by_tag = {}

    for elem in root.iter():
        if elem.attrib:
            tag = elem.tag
            rows_by_tag.setdefault(tag, []).append(dict(elem.attrib))

    tables = {}
    for tag, rows in rows_by_tag.items():
        df = pd.DataFrame(rows)
        tables[tag] = df

    return tables

def normalize_tables(tables: dict):
    """
    Crea tablas estándar para Power BI.
    Si faltan columnas porque la Flex Query no las trae, se devuelven vacías.
    """
    def find_table(possible_names):
        for name in possible_names:
            if name in tables:
                return tables[name].copy()
        return pd.DataFrame()

    positions = find_table(["OpenPosition", "Position", "FxPosition"])
    trades = find_table(["Trade"])
    dividends = find_table(["CashTransaction"])
    margin = find_table(["MarginReport", "EquitySummary", "ChangeInNAV"])

    # Opciones: normalmente vienen mezcladas en posiciones/trades con assetCategory=OPT
    options = pd.DataFrame()
    if not positions.empty and "assetCategory" in positions.columns:
        options = positions[positions["assetCategory"].astype(str).str.upper().eq("OPT")].copy()
    elif not trades.empty and "assetCategory" in trades.columns:
        options = trades[trades["assetCategory"].astype(str).str.upper().eq("OPT")].copy()

    for df in [positions, trades, dividends, margin, options]:
        if not df.empty:
            df["Platform"] = "IBKR"

    return {
        "positions": positions,
        "trades": trades,
        "dividends": dividends,
        "margin": margin,
        "options": options
    }

def show_and_download(name, df):
    st.subheader(name)
    if df.empty:
        st.warning(f"{name}: sin datos. Revisa que tu Flex Query incluya esa sección.")
        return
    st.dataframe(df.head(100), use_container_width=True)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(f"Descargar {name}.csv", csv, file_name=f"{name}.csv", mime="text/csv")

try:
    xml_bytes = download_ibkr_xml(IBKR_TOKEN, IBKR_QUERY_ID)
    tables_raw = xml_to_flat_tables(xml_bytes)
    tables = normalize_tables(tables_raw)

    st.success("Datos IBKR descargados correctamente.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tablas XML detectadas", len(tables_raw))
    c2.metric("Positions", len(tables["positions"]))
    c3.metric("Trades", len(tables["trades"]))
    c4.metric("Dividends", len(tables["dividends"]))

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["Positions", "Trades", "Dividends", "Options", "Margin", "Raw tables"]
    )

    with tab1:
        show_and_download("positions", tables["positions"])
    with tab2:
        show_and_download("trades", tables["trades"])
    with tab3:
        show_and_download("dividends", tables["dividends"])
    with tab4:
        show_and_download("options", tables["options"])
    with tab5:
        show_and_download("margin", tables["margin"])
    with tab6:
        st.write(list(tables_raw.keys()))
        for k, v in tables_raw.items():
            with st.expander(k):
                st.dataframe(v.head(50), use_container_width=True)

except Exception as e:
    st.error(str(e))
    st.info("Configura IBKR_TOKEN e IBKR_QUERY_ID en Railway → Variables.")
