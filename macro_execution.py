import streamlit as st
import pandas as pd
import requests
from datetime import datetime

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
st.set_page_config(page_title="Sovereign Macro Engine", layout="wide")
st.title("Sovereign Macro Execution Engine")

api_key = st.secrets.get("FRED_API_KEY")
if not api_key:
    api_key = st.sidebar.text_input("Enter FRED API Key", type="password")

if not api_key:
    st.stop()

start_date = "2015-01-01"
end_date = datetime.now().strftime("%Y-%m-%d")

# --------------------------------------------------
# DATA FETCH
# --------------------------------------------------
@st.cache_data(ttl=86400)
def fetch(series):
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date
    }

    r = requests.get(url, params=params)
    data = r.json()

    df = pd.DataFrame(data["observations"])
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    return df.dropna().set_index("date")["value"]

# --------------------------------------------------
# SERIES
# --------------------------------------------------
SERIES = {
    "DXY": "DTWEXAFEGS",
    "10Y": "DGS10",
    "FED": "WALCL",
    "RRP": "RRPONTSYD",
    "TGA": "WTREGEN",
    "CREDIT": "BAMLH0A0HYM2"
}

dxy = fetch(SERIES["DXY"])
y10 = fetch(SERIES["10Y"])
fed = fetch(SERIES["FED"])
rrp = fetch(SERIES["RRP"])
tga = fetch(SERIES["TGA"])
credit = fetch(SERIES["CREDIT"])

# --------------------------------------------------
# LIQUIDITY ENGINE
# --------------------------------------------------
df = pd.concat([fed, rrp, tga], axis=1).ffill().dropna()
df.columns = ["fed","rrp","tga"]

net_liq = df["fed"] - df["rrp"] - df["tga"]

liq_trend = (
    net_liq.pct_change(30).rolling(5).mean().dropna()
).iloc[-1]

# --------------------------------------------------
# CORE SIGNALS
# --------------------------------------------------
yield_trend = y10.pct_change(60).iloc[-1]
dxy_trend = dxy.pct_change(30).iloc[-1]
credit_trend = credit.pct_change(30).rolling(3).mean().iloc[-1]

# --------------------------------------------------
# BTC PRICE (AUTO)
# --------------------------------------------------
@st.cache_data(ttl=3600)
def get_btc():
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    params = {"vs_currency":"usd","days":"365"}
    data = requests.get(url, params=params).json()
    
    prices = pd.DataFrame(data["prices"], columns=["time","price"])
    prices["time"] = pd.to_datetime(prices["time"], unit="ms")
    return prices.set_index("time")["price"]

btc = get_btc()

btc_price = btc.iloc[-1]
btc_ath = btc.max()
btc_drawdown = (btc_price - btc_ath) / btc_ath

# --------------------------------------------------
# RETAIL SENTIMENT (PROXY)
# --------------------------------------------------
retail_score = 0

if btc_drawdown > -0.2:
    retail_score += 1  # near highs

if btc.pct_change(30).iloc[-1] > 0.3:
    retail_score += 1  # strong rally

if retail_score >= 2:
    sentiment = "EUPHORIA"
elif retail_score == 1:
    sentiment = "NEUTRAL"
else:
    sentiment = "PANIC"

# --------------------------------------------------
# MACRO SCORE
# --------------------------------------------------
macro_score = 0
macro_score += 1 if liq_trend > 0 else -1
macro_score += 1 if yield_trend < 0 else -1
macro_score += 1 if dxy_trend < 0 else -1
macro_score += 1 if credit_trend < 0 else -1

# --------------------------------------------------
# ASSET SCORING
# --------------------------------------------------
scores = {}

scores["BTC"] = liq_trend * 2 - dxy_trend
scores["Gold"] = (-yield_trend) + abs(credit_trend)
scores["Energy"] = liq_trend - yield_trend
scores["Materials"] = liq_trend
scores["Infra"] = 0.5
scores["AI"] = liq_trend * 2 - credit_trend
scores["EM"] = liq_trend - dxy_trend
scores["Cash"] = -liq_trend + abs(dxy_trend)

# --------------------------------------------------
# NORMALIZE → ALLOCATION
# --------------------------------------------------
min_score = min(scores.values())
scores = {k: (v - min_score) + 0.01 for k,v in scores.items()}

total = sum(scores.values())
allocation = {k: round(v/total*100,2) for k,v in scores.items()}

# --------------------------------------------------
# TRIM ENGINE
# --------------------------------------------------
trim_actions = []

if sentiment == "EUPHORIA":
    for k in ["BTC","AI","Energy"]:
        if allocation[k] > 10:
            trim = allocation[k] * 0.2
            allocation[k] -= trim
            allocation["Cash"] += trim
            trim_actions.append(f"Trim {k} → Cash")

# --------------------------------------------------
# DISPLAY
# --------------------------------------------------
def arrow(x):
    return "↑" if x>0 else "↓"

st.subheader("Macro")

c1,c2,c3,c4 = st.columns(4)

c1.metric("Liquidity", f"{liq_trend*100:.2f}%", arrow(liq_trend))
c2.metric("Yield", f"{y10.iloc[-1]:.2f}%", arrow(yield_trend))
c3.metric("DXY", f"{dxy.iloc[-1]:.2f}", arrow(dxy_trend))
c4.metric("Credit", f"{credit.iloc[-1]:.2f}%", arrow(credit_trend))

st.subheader("BTC")
st.metric("Price", f"${btc_price:,.0f}")
st.metric("Drawdown", f"{btc_drawdown*100:.1f}%")

st.subheader("Sentiment")
st.metric("Retail State", sentiment)

st.subheader("Dynamic Allocation")
st.dataframe(pd.DataFrame.from_dict(allocation,orient="index",columns=["%"]))

st.subheader("Trim Actions")
for a in trim_actions:
    st.warning(a)
