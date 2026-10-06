from __future__ import annotations

import io
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
DATA_PATH = APP_DIR / "data" / "sample_spares.csv"

st.set_page_config(
    page_title="Aviation Spares Supplier Intelligence",
    page_icon="✈️",
    layout="wide",
)

st.markdown(
    """
<style>
.block-container {padding-top: 1.7rem; padding-bottom: 2.5rem;}
[data-testid="stMetric"] {border:1px solid #2a3447; border-radius:14px; padding:12px 14px; background:#151d2e;}
.small-note {color:#aab6cb; font-size:.86rem;}
.source-pill {border:1px solid #2a3447; border-radius:999px; padding:4px 9px; display:inline-block; margin-right:6px; font-size:.78rem;}
</style>
""",
    unsafe_allow_html=True,
)

@st.cache_data
def load_sample_data() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH)

@st.cache_data(ttl=3600)
def fx_rates_to_usd(currencies: tuple[str, ...]) -> dict[str, float]:
    """Return multiplier from source currency to USD using Frankfurter.
    Falls back to conservative demo rates if API is unavailable.
    """
    fallback = {
        "USD": 1.0,
        "EUR": 1.17,
        "AED": 0.2723,
        "QAR": 0.2747,
        "SAR": 0.2666,
    }
    rates: dict[str, float] = {}
    for cur in currencies:
        cur = cur.upper()
        if cur == "USD":
            rates[cur] = 1.0
            continue
        try:
            r = requests.get(
                "https://api.frankfurter.app/latest",
                params={"from": cur, "to": "USD"},
                timeout=8,
            )
            r.raise_for_status()
            rates[cur] = float(r.json()["rates"]["USD"])
        except Exception:
            rates[cur] = fallback.get(cur, 1.0)
    return rates

@st.cache_data(ttl=86400)
def geocode_city(city: str, country: str) -> tuple[float | None, float | None]:
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{city}, {country}", "format": "jsonv2", "limit": 1},
            headers={"User-Agent": "AviationSparesSupplierIntelligence/1.0"},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None, None


def normalize_prices(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    currencies = tuple(sorted(set(out["currency"].astype(str).str.upper())))
    rates = fx_rates_to_usd(currencies)
    out["fx_to_usd"] = out["currency"].str.upper().map(rates).fillna(1.0)
    out["price_usd"] = (out["unit_price"].astype(float) * out["fx_to_usd"]).round(2)
    return out


def minmax_inverse(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce").fillna(s.max() if len(s) else 0)
    lo, hi = float(s.min()), float(s.max())
    if math.isclose(lo, hi):
        return pd.Series([100.0] * len(s), index=s.index)
    return 100 - ((s - lo) / (hi - lo) * 100)


def compute_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    price_score = minmax_inverse(out["price_usd"])
    lead_score = minmax_inverse(out["lead_time_days"])
    stock = pd.to_numeric(out["stock_qty"], errors="coerce").fillna(0)
    stock_score = (stock.clip(0, 20) / 20 * 100)
    reliability = pd.to_numeric(out["reliability_score"], errors="coerce").fillna(0).clip(0, 100)
    out["supplier_score"] = (
        price_score * 0.40 + lead_score * 0.30 + stock_score * 0.20 + reliability * 0.10
    ).round(1)
    return out


def secrets_get(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, default))
    except Exception:
        return default


def run_apify_actor(actor_id: str, token: str, run_input: dict[str, Any], max_items: int = 50) -> list[dict[str, Any]]:
    actor = actor_id.replace("/", "~")
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(
        url,
        headers=headers,
        params={"clean": "true", "format": "json", "maxItems": max_items, "timeout": 120},
        json=run_input,
        timeout=135,
    )
    r.raise_for_status()
    payload = r.json()
    return payload if isinstance(payload, list) else payload.get("items", [])


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

# Header
st.title("✈️ Aviation Spares Supplier Intelligence")
st.caption("Supplier sourcing, price normalization, lead-time comparison and decision scoring for aviation materials.")
st.markdown(
    '<span class="source-pill">Python</span><span class="source-pill">Streamlit</span>'
    '<span class="source-pill">Apify-ready</span><span class="source-pill">Public APIs</span>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Search & filters")
    search = st.text_input("Part / description / supplier", placeholder="e.g. brake, AV-4721, Gulf")
    base_df = load_sample_data()
    countries = st.multiselect("Country", sorted(base_df["country"].unique()))
    conditions = st.multiselect("Condition", sorted(base_df["condition"].unique()))
    max_lead = st.slider("Maximum lead time (days)", 1, 60, 30)
    in_stock_only = st.toggle("In-stock only", value=True)
    st.divider()
    st.caption("Scoring weights")
    st.progress(40, text="Price 40%")
    st.progress(30, text="Lead time 30%")
    st.progress(20, text="Stock 20%")
    st.progress(10, text="Reliability 10%")

# Prepare data
raw = load_sample_data()
df = normalize_prices(raw)
df = compute_scores(df)

mask = pd.Series(True, index=df.index)
if search.strip():
    q = search.strip().lower()
    searchable = (
        df["part_number"].astype(str) + " " +
        df["description"].astype(str) + " " +
        df["supplier"].astype(str) + " " +
        df["category"].astype(str)
    ).str.lower()
    mask &= searchable.str.contains(q, regex=False)
if countries:
    mask &= df["country"].isin(countries)
if conditions:
    mask &= df["condition"].isin(conditions)
mask &= pd.to_numeric(df["lead_time_days"], errors="coerce").fillna(999) <= max_lead
if in_stock_only:
    mask &= pd.to_numeric(df["stock_qty"], errors="coerce").fillna(0) > 0

view = df.loc[mask].sort_values(["supplier_score", "price_usd"], ascending=[False, True]).reset_index(drop=True)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Matching offers", f"{len(view)}")
m2.metric("Suppliers", f"{view['supplier'].nunique() if len(view) else 0}")
m3.metric("Countries", f"{view['country'].nunique() if len(view) else 0}")
m4.metric("Best score", f"{view['supplier_score'].max():.1f}/100" if len(view) else "—")

intel_tab, map_tab, collect_tab, about_tab = st.tabs([
    "Supplier intelligence", "Supplier map", "Apify collector", "About"
])

with intel_tab:
    st.subheader("Ranked supplier offers")
    if view.empty:
        st.info("No offers match the current filters.")
    else:
        show_cols = [
            "part_number", "description", "supplier", "country", "condition",
            "unit_price", "currency", "price_usd", "stock_qty", "lead_time_days",
            "reliability_score", "supplier_score", "source_url", "last_checked"
        ]
        st.dataframe(
            view[show_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "price_usd": st.column_config.NumberColumn("USD normalized", format="$%.2f"),
                "unit_price": st.column_config.NumberColumn("Listed price", format="%.2f"),
                "supplier_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
                "source_url": st.column_config.LinkColumn("Source"),
            },
        )
        best = view.iloc[0]
        st.success(
            f"Top ranked offer: {best['supplier']} — {best['part_number']} — "
            f"${best['price_usd']:,.2f} normalized, {int(best['lead_time_days'])}-day lead time, "
            f"score {best['supplier_score']:.1f}/100."
        )
        st.download_button(
            "Download filtered intelligence (CSV)",
            dataframe_to_csv_bytes(view[show_cols]),
            file_name=f"aviation_spares_intelligence_{date.today().isoformat()}.csv",
            mime="text/csv",
        )

with map_tab:
    st.subheader("Supplier geography")
    unique_sites = view[["supplier", "city", "country"]].drop_duplicates().copy()
    coords = []
    with st.spinner("Resolving supplier locations…"):
        for _, row in unique_sites.iterrows():
            lat, lon = geocode_city(str(row["city"]), str(row["country"]))
            coords.append((lat, lon))
    unique_sites[["lat", "lon"]] = pd.DataFrame(coords, index=unique_sites.index)
    mapped = unique_sites.dropna(subset=["lat", "lon"])
    if mapped.empty:
        st.warning("Live geocoding is unavailable right now. Supplier list is still available below.")
    else:
        st.map(mapped[["lat", "lon"]], use_container_width=True)
    st.dataframe(unique_sites, use_container_width=True, hide_index=True)

with collect_tab:
    st.subheader("Optional live collection with Apify")
    st.markdown(
        "Use this only when you have an Apify Actor configured for a supplier/product source. "
        "The demo intelligence above works without Apify."
    )
    default_actor = secrets_get("APIFY_ACTOR_ID", "")
    actor_id = st.text_input("Actor ID", value=default_actor, placeholder="username/actor-name")
    token_from_secret = secrets_get("APIFY_TOKEN", "")
    token = st.text_input(
        "Apify token",
        value=token_from_secret,
        type="password",
        help="For deployment, store APIFY_TOKEN in Streamlit Secrets rather than in code.",
    )
    urls_text = st.text_area(
        "Supplier/product URLs (one per line)",
        placeholder="https://supplier.example.com/search?q=aircraft+spares",
        height=110,
    )
    max_items = st.number_input("Maximum returned items", 1, 200, 25)

    example_input = {
        "startUrls": [{"url": u.strip()} for u in urls_text.splitlines() if u.strip()],
        "maxCrawlPages": int(max_items),
    }
    with st.expander("Actor input preview"):
        st.code(json.dumps(example_input, indent=2), language="json")

    if st.button("Run Apify collector", type="primary"):
        if not actor_id or not token:
            st.error("Actor ID and token are required for a live Apify run.")
        elif not example_input["startUrls"]:
            st.error("Add at least one supplier/product URL.")
        else:
            try:
                with st.spinner("Running Actor and reading dataset…"):
                    items = run_apify_actor(actor_id, token, example_input, int(max_items))
                st.success(f"Collected {len(items)} item(s).")
                if items:
                    live_df = pd.json_normalize(items)
                    st.dataframe(live_df, use_container_width=True, hide_index=True)
                    st.download_button(
                        "Download raw Apify results",
                        dataframe_to_csv_bytes(live_df),
                        file_name=f"apify_supplier_results_{date.today().isoformat()}.csv",
                        mime="text/csv",
                    )
            except Exception as exc:
                st.error(f"Apify run failed: {exc}")

with about_tab:
    st.subheader("What this MVP demonstrates")
    st.markdown(
        """
- Multi-supplier aviation-spares comparison with source traceability.
- Currency normalization to USD using a public exchange-rate API.
- Supplier geography using public geocoding.
- Weighted procurement scoring across price, lead time, stock and reliability.
- Optional Apify Actor integration for live web collection.
- CSV export for sourcing and procurement workflows.
        """
    )
    st.warning(
        "The bundled supplier records are fictional/sample portfolio data. "
        "Verify every live supplier, part number, airworthiness status, certification, price and source before procurement."
    )

st.divider()
st.caption("Portfolio demo by Muhammad Naveed · Aviation Logistics / Materials / Procurement")
