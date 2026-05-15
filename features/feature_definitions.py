from datetime import time

import numpy as np
import pandas as pd

from ml.black_scholes import calculate_greeks, implied_volatility


MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def safe_float(value):
    if value is None or pd.isna(value):
        return None
    return float(value)


def safe_div(numerator, denominator):
    if denominator is None or pd.isna(denominator) or denominator == 0:
        return None
    if numerator is None or pd.isna(numerator):
        return None
    return float(numerator) / float(denominator)


def latest_before(df, timestamp, time_col="time"):
    if df.empty:
        return None
    frame = df[df[time_col] <= timestamp]
    if frame.empty:
        return None
    return frame.sort_values(time_col).iloc[-1]


def rows_until(df, timestamp, minutes=None, time_col="time"):
    if df.empty:
        return df
    frame = df[df[time_col] <= timestamp]
    if minutes is not None:
        start = timestamp - pd.Timedelta(minutes=minutes)
        frame = frame[frame[time_col] >= start]
    return frame.sort_values(time_col)


def price_return(series, periods):
    if len(series) <= periods:
        return None
    previous = series.iloc[-periods - 1]
    current = series.iloc[-1]
    return safe_div(current - previous, previous)


def rsi(series, period=14):
    if len(series) <= period:
        return None
    delta = series.diff()
    gains = delta.clip(lower=0).rolling(period).mean()
    losses = -delta.clip(upper=0).rolling(period).mean()
    rs = gains.iloc[-1] / losses.iloc[-1] if losses.iloc[-1] else np.nan
    if pd.isna(rs):
        return None
    return float(100 - (100 / (1 + rs)))


def linear_slope(x, y):
    clean = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(clean) < 2:
        return None
    return float(np.polyfit(clean["x"], clean["y"], 1)[0])


def index_features(index_df, timestamp):
    frame = rows_until(index_df, timestamp, minutes=60)
    if frame.empty:
        return {}

    close = frame["close"].astype(float)
    returns = close.pct_change().dropna()
    latest = frame.iloc[-1]
    minutes_since_open = (
        latest["time"].hour * 60 + latest["time"].minute - (9 * 60 + 15)
    )

    return {
        "index_close": safe_float(latest.get("close")),
        "index_return_1m": price_return(close, 1),
        "index_return_5m": price_return(close, 5),
        "index_return_15m": price_return(close, 15),
        "index_volatility_15m": safe_float(returns.tail(15).std()),
        "index_trend_ma_9": safe_float(close.iloc[-1] - close.tail(9).mean()) if len(close) >= 9 else None,
        "index_trend_ma_21": safe_float(close.iloc[-1] - close.tail(21).mean()) if len(close) >= 21 else None,
        "index_trend_ma_50": safe_float(close.iloc[-1] - close.tail(50).mean()) if len(close) >= 50 else None,
        "index_rsi_14": rsi(close, 14),
        "time_of_day": int(minutes_since_open),
        "is_open_session": int(minutes_since_open < 60),
        "is_mid_session": int(60 <= minutes_since_open < 300),
        "is_close_session": int(minutes_since_open >= 300),
    }


def choose_atm_strike(chain_slice, index_close=None):
    if chain_slice.empty:
        return None
    if index_close is None or pd.isna(index_close):
        liquid = chain_slice.copy()
        liquid["total_oi"] = liquid[["ce_oi", "pe_oi"]].fillna(0).sum(axis=1)
        return int(liquid.sort_values("total_oi", ascending=False).iloc[0]["strike"])
    distances = (chain_slice["strike"].astype(float) - float(index_close)).abs()
    return int(chain_slice.loc[distances.idxmin(), "strike"])


def option_chain_features(chain_df, timestamp, index_close=None):
    latest_time_row = latest_before(chain_df[["time"]].drop_duplicates(), timestamp)
    if latest_time_row is None:
        return {}, None, None

    snapshot_time = latest_time_row["time"]
    chain_slice = chain_df[chain_df["time"] == snapshot_time].copy()
    if chain_slice.empty:
        return {}, None, None

    atm_strike = choose_atm_strike(chain_slice, index_close)
    atm = chain_slice[chain_slice["strike"] == atm_strike]
    if atm.empty:
        return {}, None, None
    atm_row = atm.iloc[0]
    expiry = atm_row.get("expiry")

    total_ce_oi = chain_slice["ce_oi"].fillna(0).sum()
    total_pe_oi = chain_slice["pe_oi"].fillna(0).sum()
    top_ce_oi = chain_slice["ce_oi"].fillna(0).nlargest(5).sum()
    top_pe_oi = chain_slice["pe_oi"].fillna(0).nlargest(5).sum()

    otm_ce = chain_slice[chain_slice["strike"] > atm_strike]
    otm_pe = chain_slice[chain_slice["strike"] < atm_strike]
    near_atm = chain_slice[(chain_slice["strike"] - atm_strike).abs() <= 200]

    atm_iv = np.nanmean([atm_row.get("ce_iv"), atm_row.get("pe_iv")])
    otm_iv = np.nanmean(
        pd.concat([otm_ce["ce_iv"], otm_pe["pe_iv"]], ignore_index=True).dropna()
    )

    # --- Black-Scholes Mathematical Greeks ---
    bs_ce_iv, bs_pe_iv = np.nan, np.nan
    bs_ce_greeks, bs_pe_greeks = {}, {}
    
    if index_close is not None and pd.notna(index_close):
        # Calculate time to expiry in years
        expiry_date = pd.Timestamp(expiry).date()
        current_date = pd.Timestamp(timestamp).date()
        days_to_expiry = (expiry_date - current_date).days
        
        # Add intraday fractional time
        time_remaining_minutes = max(0, (15 * 60 + 30) - (timestamp.hour * 60 + timestamp.minute))
        T_years = (days_to_expiry + time_remaining_minutes / (24 * 60)) / 365.0
        r = 0.065  # 6.5% risk-free rate approximation for India
        
        S = float(index_close)
        K = float(atm_strike)
        ce_ltp = safe_float(atm_row.get("ce_ltp"))
        pe_ltp = safe_float(atm_row.get("pe_ltp"))
        
        if ce_ltp is not None:
            bs_ce_iv = implied_volatility(ce_ltp, S, K, T_years, r, "CE")
            if not np.isnan(bs_ce_iv):
                bs_ce_greeks = calculate_greeks(S, K, T_years, r, bs_ce_iv, "CE")
                
        if pe_ltp is not None:
            bs_pe_iv = implied_volatility(pe_ltp, S, K, T_years, r, "PE")
            if not np.isnan(bs_pe_iv):
                bs_pe_greeks = calculate_greeks(S, K, T_years, r, bs_pe_iv, "PE")

    features = {
        "atm_strike": int(atm_strike),
        "atm_ce_ltp": safe_float(atm_row.get("ce_ltp")),
        "atm_pe_ltp": safe_float(atm_row.get("pe_ltp")),
        "atm_ce_iv": safe_float(atm_row.get("ce_iv")),
        "atm_pe_iv": safe_float(atm_row.get("pe_iv")),
        "atm_ce_oi": safe_float(atm_row.get("ce_oi")),
        "atm_pe_oi": safe_float(atm_row.get("pe_oi")),
        "atm_ce_oi_change": safe_float(atm_row.get("ce_oi") - atm_row.get("ceprevoi")) if pd.notna(atm_row.get("ceprevoi")) else None,
        "atm_pe_oi_change": safe_float(atm_row.get("pe_oi") - atm_row.get("peprevoi")) if pd.notna(atm_row.get("peprevoi")) else None,
        "pcr_oi": safe_div(total_pe_oi, total_ce_oi),
        "pcr_volume": None,
        "iv_skew_otm": safe_float(otm_iv - atm_iv) if not pd.isna(otm_iv) and not pd.isna(atm_iv) else None,
        "ce_iv_slope_across_strikes": linear_slope(chain_slice["strike"], chain_slice["ce_iv"]),
        "pe_iv_slope_across_strikes": linear_slope(chain_slice["strike"], chain_slice["pe_iv"]),
        "ce_oi_concentration": safe_div(top_ce_oi, total_ce_oi),
        "pe_oi_concentration": safe_div(top_pe_oi, total_pe_oi),
        "atm_ce_delta": safe_float(atm_row.get("ce_delta")),
        "atm_pe_delta": safe_float(atm_row.get("pe_delta")),
        "atm_ce_gamma": safe_float(atm_row.get("ce_gamma")),
        "atm_pe_gamma": safe_float(atm_row.get("pe_gamma")),
        "atm_ce_theta": safe_float(atm_row.get("ce_theta")),
        "atm_pe_theta": safe_float(atm_row.get("pe_theta")),
        "atm_ce_vega": safe_float(atm_row.get("ce_vega")),
        "atm_pe_vega": safe_float(atm_row.get("pe_vega")),
        "delta_skew": safe_float(otm_ce["ce_delta"].mean() - atm_row.get("ce_delta")) if not otm_ce.empty else None,
        "gamma_exposure": safe_float(
            (chain_slice["ce_gamma"].fillna(0) * chain_slice["ce_oi"].fillna(0)).sum()
            + (chain_slice["pe_gamma"].fillna(0) * chain_slice["pe_oi"].fillna(0)).sum()
        ),
        "theta_pressure": safe_float(
            near_atm["ce_theta"].abs().fillna(0).sum()
            + near_atm["pe_theta"].abs().fillna(0).sum()
        ),
        "bs_ce_iv": safe_float(bs_ce_iv),
        "bs_pe_iv": safe_float(bs_pe_iv),
        "bs_ce_delta": safe_float(bs_ce_greeks.get("delta", np.nan)),
        "bs_pe_delta": safe_float(bs_pe_greeks.get("delta", np.nan)),
        "bs_ce_gamma": safe_float(bs_ce_greeks.get("gamma", np.nan)),
        "bs_pe_gamma": safe_float(bs_pe_greeks.get("gamma", np.nan)),
        "bs_ce_theta": safe_float(bs_ce_greeks.get("theta", np.nan)),
        "bs_pe_theta": safe_float(bs_pe_greeks.get("theta", np.nan)),
        "bs_ce_vega": safe_float(bs_ce_greeks.get("vega", np.nan)),
        "bs_pe_vega": safe_float(bs_pe_greeks.get("vega", np.nan)),
    }
    return features, atm_strike, expiry


def option_price_features(option_df, timestamp, strike, option_type):
    frame = option_df[
        (option_df["strike"] == strike) & (option_df["option_type"] == option_type)
    ]
    frame = rows_until(frame, timestamp, minutes=30)
    if frame.empty:
        return {}

    close = frame["close"].astype(float)
    recent_15 = frame.tail(15)
    latest = frame.iloc[-1]
    prior_high = frame["high"].iloc[:-1].tail(20).max() if len(frame) > 1 else np.nan
    prior_low = frame["low"].iloc[:-1].tail(20).min() if len(frame) > 1 else np.nan

    return {
        "atm_option_close": safe_float(latest.get("close")),
        "atm_option_return_1m": price_return(close, 1),
        "atm_option_return_5m": price_return(close, 5),
        "atm_option_range_15m": safe_float(recent_15["high"].max() - recent_15["low"].min()),
        "atm_option_volatility_15m": safe_float(close.pct_change().dropna().tail(15).std()),
        "recent_high_breakout_flag": int(pd.notna(prior_high) and latest["close"] > prior_high),
        "recent_low_breakdown_flag": int(pd.notna(prior_low) and latest["close"] < prior_low),
    }


def microstructure_features(depth_df, timestamp, security_id=None):
    frame = depth_df.copy()
    if security_id is not None and "security_id" in frame.columns:
        frame = frame[frame["security_id"] == security_id]
    frame = rows_until(frame, timestamp, minutes=5)
    if frame.empty:
        return {}

    latest = frame.iloc[-1]
    bid = latest.get("bidprice1")
    ask = latest.get("askprice1")
    bid_qty = latest.get("bidqty1")
    ask_qty = latest.get("askqty1")
    mid = np.nanmean([bid, ask])
    spread = ask - bid if pd.notna(ask) and pd.notna(bid) else None
    mids = frame[["bidprice1", "askprice1"]].mean(axis=1)

    return {
        "bid_ask_spread": safe_float(spread),
        "spread_pct": safe_div(spread, mid),
        "orderbook_imbalance": safe_div(bid_qty - ask_qty, bid_qty + ask_qty),
        "liquidity_score": safe_float((bid_qty or 0) + (ask_qty or 0)),
        "tick_volatility": safe_float(mids.pct_change().dropna().std()),
    }


def expiry_features(timestamp, expiry):
    if expiry is None or pd.isna(expiry):
        return {}
    expiry_date = pd.Timestamp(expiry).date()
    current_date = pd.Timestamp(timestamp).date()
    days = (expiry_date - current_date).days
    return {
        "days_to_expiry": int(days),
        "is_expiry_day": int(days == 0),
        "is_weekly_expiry": 1,
        "is_monthly_expiry": int(expiry_date.day >= 24),
    }
