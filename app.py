import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime
import time

st.set_page_config(page_title="NSE Pro Algo Terminal", layout="wide", page_icon="⚡")

# -------------------------------------------------------------
# Multi-Stock Universe & Token Map (NSE)
# -------------------------------------------------------------
WATCHLIST = {
    "SBIN": {"token": 779521, "base": 820.0},
    "RELIANCE": {"token": 738561, "base": 2950.0},
    "TCS": {"token": 2953216, "base": 3880.0},
    "INFY": {"token": 408065, "base": 1780.0},
    "HDFCBANK": {"token": 341249, "base": 1640.0}
}

# -------------------------------------------------------------
# Session State Initialization
# -------------------------------------------------------------
if "capital" not in st.session_state:
    st.session_state.capital = 100000.0  # ₹1,00,000 starting account
if "positions" not in st.session_state:
    st.session_state.positions = {}  # {symbol: position_dict}
if "trade_log" not in st.session_state:
    st.session_state.trade_log = []
if "market_data" not in st.session_state:
    st.session_state.market_data = {}
    
    # Initialize 60 bars of 5-min OHLCV with synthetic baseline
    np.random.seed(42)
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    times = [now - datetime.timedelta(minutes=5 * (60 - i)) for i in range(60)]
    
    for sym, meta in WATCHLIST.items():
        base = meta["base"]
        drift = np.random.normal(0, base * 0.0008, 60).cumsum()
        closes = base + drift
        highs = closes + np.random.uniform(0.5, base * 0.002, 60)
        lows = closes - np.random.uniform(0.5, base * 0.002, 60)
        opens = [closes[0]] + list(closes[:-1])
        vols = np.random.randint(5000, 35000, 60)
        
        df_sym = pd.DataFrame({
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols
        })
        st.session_state.market_data[sym] = df_sym

# -------------------------------------------------------------
# Technical Calculations (EMA, ATR, VWAP)
# -------------------------------------------------------------
def calculate_indicators(df):
    data = df.copy()
    data['ema9'] = data['close'].ewm(span=9, adjust=False).mean()
    data['ema21'] = data['close'].ewm(span=21, adjust=False).mean()
    
    # ATR (14)
    hl = data['high'] - data['low']
    hc = (data['high'] - data['close'].shift()).abs()
    lc = (data['low'] - data['close'].shift()).abs()
    data['atr'] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()
    
    # Intraday VWAP (Volume Weighted Average Price)
    typical_price = (data['high'] + data['low'] + data['close']) / 3
    data['vwap'] = (typical_price * data['volume']).cumsum() / data['volume'].cumsum()
    return data

def get_signal(df):
    data = calculate_indicators(df)
    if len(data) < 25:
        return "HOLD", 0.0, 0.0
    
    prev_fast = data['ema9'].iloc[-2]
    curr_fast = data['ema9'].iloc[-1]
    prev_slow = data['ema21'].iloc[-2]
    curr_slow = data['ema21'].iloc[-1]
    close = data['close'].iloc[-1]
    vwap = data['vwap'].iloc[-1]
    atr = data['atr'].iloc[-1]
    
    # Bullish: 9 EMA crosses above 21 EMA AND price is above VWAP
    if prev_fast <= prev_slow and curr_fast > curr_slow and close > vwap:
        return "BUY", atr, vwap
    # Bearish: 9 EMA crosses below 21 EMA AND price is below VWAP
    elif prev_fast >= prev_slow and curr_fast < curr_slow and close < vwap:
        return "SELL", atr, vwap
        
    return "HOLD", atr, vwap

# -------------------------------------------------------------
# Sidebar: Risk, Settings & Live Controls
# -------------------------------------------------------------
st.sidebar.title("Algo Control Panel")
auto_execute = st.sidebar.toggle("🤖 Auto-Execution Mode", value=False)
live_mode = st.sidebar.selectbox("Broker Mode", ["Paper Trading (Mock)", "Live Broker (Kite API)"])

st.sidebar.markdown("---")
risk_pct = st.sidebar.slider("Risk Per Trade (%)", 0.5, 2.5, 1.0, 0.25) / 100.0
rr_ratio = st.sidebar.slider("Target Multiple (R:R)", 1.5, 3.5, 2.0, 0.5)
trail_sl_enabled = st.sidebar.checkbox("Enable Trailing Stop-Loss", value=True)

auto_refresh = st.sidebar.checkbox("Auto-Refresh Loop (every 3s)", value=False)

st.sidebar.markdown("---")
st.sidebar.write(f"**Available Capital:** ₹{st.session_state.capital:,.2f}")
current_clock = datetime.datetime.now().time()
st.sidebar.write(f"**Market Clock:** {current_clock.strftime('%H:%M:%S')} IST")

# -------------------------------------------------------------
# Top Section: Multi-Stock Live Screener Desk
# -------------------------------------------------------------
st.title("NSE Professional Intraday Desk")

screener_cols = st.columns(len(WATCHLIST))
screener_results = {}

for idx, (sym, _) in enumerate(WATCHLIST.items()):
    df_sym = calculate_indicators(st.session_state.market_data[sym])
    sig, atr_val, vwap_val = get_signal(st.session_state.market_data[sym])
    ltp = df_sym['close'].iloc[-1]
    change = ltp - df_sym['open'].iloc[0]
    
    screener_results[sym] = {
        "df": df_sym,
        "ltp": ltp,
        "sig": sig,
        "atr": atr_val,
        "vwap": vwap_val
    }
    
    with screener_cols[idx]:
        sig_color = "🟢" if sig == "BUY" else ("🔴" if sig == "SELL" else "⚪")
        st.metric(
            label=f"{sym} {sig_color}",
            value=f"₹{ltp:.2f}",
            delta=f"{change:.2f}"
        )

# Selected stock for deep chart view
active_sym = st.selectbox("Select Active Chart Focus", list(WATCHLIST.keys()))
active_data = screener_results[active_sym]
df_active = active_data["df"]
active_ltp = active_data["ltp"]

# -------------------------------------------------------------
# Automation Engine: Trailing SL, Exits & Auto-Entries
# -------------------------------------------------------------
square_off_time = datetime.time(15, 15)

for sym in list(WATCHLIST.keys()):
    data_pack = screener_results[sym]
    ltp = data_pack["ltp"]
    atr = data_pack["atr"] if not np.isnan(data_pack["atr"]) else ltp * 0.006
    
    # 1. Manage Active Positions
    if sym in st.session_state.positions:
        pos = st.session_state.positions[sym]
        
        # Dynamic Trailing Stop-Loss logic
        if trail_sl_enabled:
            if pos["side"] == "BUY":
                # Price moved 1x ATR into profit -> move SL up
                if ltp - pos["entry"] >= atr:
                    new_sl = max(pos["sl"], ltp - (atr * 1.5))
                    if new_sl > pos["sl"]:
                        pos["sl"] = new_sl
            elif pos["side"] == "SELL":
                if pos["entry"] - ltp >= atr:
                    new_sl = min(pos["sl"], ltp + (atr * 1.5))
                    if new_sl < pos["sl"]:
                        pos["sl"] = new_sl

        # Check Exits
        sl_hit = (pos["side"] == "BUY" and ltp <= pos["sl"]) or (pos["side"] == "SELL" and ltp >= pos["sl"])
        tp_hit = (pos["side"] == "BUY" and ltp >= pos["tp"]) or (pos["side"] == "SELL" and ltp <= pos["tp"])
        time_exit = current_clock >= square_off_time
        
        if sl_hit or tp_hit or time_exit:
            reason = "STOP LOSS HIT" if sl_hit else ("TARGET HIT" if tp_hit else "3:15 PM AUTO SQUARE-OFF")
            pnl = (ltp - pos["entry"]) * pos["qty"] if pos["side"] == "BUY" else (pos["entry"] - ltp) * pos["qty"]
            st.session_state.capital += pnl
            st.session_state.trade_log.append({
                "Time": datetime.datetime.now().strftime("%H:%M:%S"),
                "Symbol": sym,
                "Side": pos["side"],
                "Qty": pos["qty"],
                "Entry": round(pos["entry"], 2),
                "Exit": round(ltp, 2),
                "Net PnL": round(pnl, 2),
                "Exit Reason": reason
            })
            del st.session_state.positions[sym]
            st.rerun()

    # 2. Automated Signal Entry (if Auto-Execute is ON)
    elif auto_execute and sym not in st.session_state.positions:
        sig = data_pack["sig"]
        if sig in ["BUY", "SELL"] and current_clock < square_off_time:
            sl_buffer = max(atr * 1.5, ltp * 0.005)
            risk_rupees = st.session_state.capital * risk_pct
            qty = max(1, int(risk_rupees / sl_buffer))
            
            if sig == "BUY":
                st.session_state.positions[sym] = {
                    "side": "BUY",
                    "entry": ltp,
                    "qty": qty,
                    "sl": ltp - sl_buffer,
                    "tp": ltp + (sl_buffer * rr_ratio)
                }
            elif sig == "SELL":
                st.session_state.positions[sym] = {
                    "side": "SELL",
                    "entry": ltp,
                    "qty": qty,
                    "sl": ltp + sl_buffer,
                    "tp": ltp - (sl_buffer * rr_ratio)
                }
            st.rerun()

# -------------------------------------------------------------
# Chart Display & Manual Execution Desk
# -------------------------------------------------------------
col_chart, col_desk = st.columns([3, 1])

with col_chart:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df_active["time"],
        open=df_active["open"],
        high=df_active["high"],
        low=df_active["low"],
        close=df_active["close"],
        name="Price"
    ))
    fig.add_trace(go.Scatter(x=df_active["time"], y=df_active["ema9"], line=dict(color="cyan", width=1.5), name="EMA 9"))
    fig.add_trace(go.Scatter(x=df_active["time"], y=df_active["ema21"], line=dict(color="orange", width=1.5), name="EMA 21"))
    fig.add_trace(go.Scatter(x=df_active["time"], y=df_active["vwap"], line=dict(color="magenta", width=1.5, dash="dot"), name="VWAP"))
    
    # Overlay lines if active position exists for focused symbol
    if active_sym in st.session_state.positions:
        pos_focus = st.session_state.positions[active_sym]
        fig.add_hline(y=pos_focus["sl"], line_dash="dash", line_color="red", annotation_text=f"Trailing SL: ₹{pos_focus['sl']:.2f}")
        fig.add_hline(y=pos_focus["tp"], line_dash="dash", line_color="green", annotation_text=f"Target: ₹{pos_focus['tp']:.2f}")
        fig.add_hline(y=pos_focus["entry"], line_dash="dot", line_color="yellow", annotation_text=f"Entry: ₹{pos_focus['entry']:.2f}")

    fig.update_layout(
        height=520,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False,
        template="plotly_dark"
    )
    st.plotly_chart(fig, use_container_width=True)

with col_desk:
    st.subheader(f"Execution Desk: {active_sym}")
    
    if active_sym in st.session_state.positions:
        pos = st.session_state.positions[active_sym]
        floating_pnl = (active_ltp - pos["entry"]) * pos["qty"] if pos["side"] == "BUY" else (pos["entry"] - active_ltp) * pos["qty"]
        color = "green" if floating_pnl >= 0 else "red"
        
        st.info(f"""
        **Side:** {pos['side']} ({pos['qty']} Qty)  
        **Entry:** ₹{pos['entry']:.2f}  
        **Current SL:** ₹{pos['sl']:.2f}  
        **Target:** ₹{pos['tp']:.2f}  
        """)
        st.markdown(f"### Live P&L: <span style='color:{color}'>₹{floating_pnl:.2f}</span>", unsafe_allow_html=True)
        
        if st.button("Close Position (Market)", use_container_width=True):
            st.session_state.capital += floating_pnl
            st.session_state.trade_log.append({
                "Time": datetime.datetime.now().strftime("%H:%M:%S"),
                "Symbol": active_sym,
                "Side": pos["side"],
                "Qty": pos["qty"],
                "Entry": round(pos["entry"], 2),
                "Exit": round(active_ltp, 2),
                "Net PnL": round(floating_pnl, 2),
                "Exit Reason": "MANUAL DESK EXIT"
            })
            del st.session_state.positions[active_sym]
            st.rerun()
    else:
        atr_f = active_data["atr"] if not np.isnan(active_data["atr"]) else active_ltp * 0.005
        sl_calc = max(atr_f * 1.5, active_ltp * 0.005)
        calc_qty = max(1, int((st.session_state.capital * risk_pct) / sl_calc))
        
        st.write(f"**Recommended Sizing:** {calc_qty} Qty")
        st.write(f"**Stop Buffer:** ₹{sl_calc:.2f}")
        
        b1, b2 = st.columns(2)
        if b1.button("🟢 BUY", use_container_width=True):
            st.session_state.positions[active_sym] = {
                "side": "BUY",
                "entry": active_ltp,
                "qty": calc_qty,
                "sl": active_ltp - sl_calc,
                "tp": active_ltp + (sl_calc * rr_ratio)
            }
            st.rerun()
        if b2.button("🔴 SELL", use_container_width=True):
            st.session_state.positions[active_sym] = {
                "side": "SELL",
                "entry": active_ltp,
                "qty": calc_qty,
                "sl": active_ltp + sl_calc,
                "tp": active_ltp - (sl_calc * rr_ratio)
            }
            st.rerun()

    st.markdown("---")
    if st.button("Simulate Next Tick Wave"):
        for sym, df_bar in st.session_state.market_data.items():
            last = df_bar["close"].iloc[-1]
            shift = np.random.normal(0, last * 0.002)
            c_new = last + shift
            new_row = pd.DataFrame([{
                "time": df_bar["time"].iloc[-1] + datetime.timedelta(minutes=5),
                "open": last,
                "high": max(last, c_new) + (last * 0.001),
                "low": min(last, c_new) - (last * 0.001),
                "close": c_new,
                "volume": np.random.randint(4000, 20000)
            }])
            st.session_state.market_data[sym] = pd.concat([df_bar, new_row], ignore_index=True)
        st.rerun()

# -------------------------------------------------------------
# Bottom Table: Trade Journal
# -------------------------------------------------------------
st.subheader("Session Trade Journal & Performance")
if st.session_state.trade_log:
    log_df = pd.DataFrame(st.session_state.trade_log)
    st.dataframe(log_df, use_container_width=True)
else:
    st.write("Abhi tak koi trade square-off nahi hua hai.")

if auto_refresh:
    time.sleep(3)
    st.rerun()
