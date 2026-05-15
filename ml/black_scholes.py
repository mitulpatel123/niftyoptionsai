import math

import numpy as np
from scipy.stats import norm


def d1(S, K, T, r, sigma, q=0.0):
    return (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))


def d2(S, K, T, r, sigma, q=0.0):
    return d1(S, K, T, r, sigma, q) - sigma * np.sqrt(T)


def bs_call_price(S, K, T, r, sigma, q=0.0):
    if T <= 0:
        return max(0.0, S - K)
    _d1 = d1(S, K, T, r, sigma, q)
    _d2 = d2(S, K, T, r, sigma, q)
    return S * np.exp(-q * T) * norm.cdf(_d1) - K * np.exp(-r * T) * norm.cdf(_d2)


def bs_put_price(S, K, T, r, sigma, q=0.0):
    if T <= 0:
        return max(0.0, K - S)
    _d1 = d1(S, K, T, r, sigma, q)
    _d2 = d2(S, K, T, r, sigma, q)
    return K * np.exp(-r * T) * norm.cdf(-_d2) - S * np.exp(-q * T) * norm.cdf(-_d1)


def bs_vega(S, K, T, r, sigma, q=0.0):
    if T <= 0:
        return 0.0
    _d1 = d1(S, K, T, r, sigma, q)
    return S * np.exp(-q * T) * norm.pdf(_d1) * np.sqrt(T)


def implied_volatility(price, S, K, T, r, option_type="CE", q=0.0, max_iter=100, precision=1e-5):
    if T <= 0 or price <= 0:
        return np.nan

    # Check for intrinsic value violations
    intrinsic = max(0.0, S - K) if option_type == "CE" else max(0.0, K - S)
    if price < intrinsic:
        return np.nan

    sigma = 0.5  # Initial guess
    for _ in range(max_iter):
        if option_type == "CE":
            price_est = bs_call_price(S, K, T, r, sigma, q)
        else:
            price_est = bs_put_price(S, K, T, r, sigma, q)

        vega = bs_vega(S, K, T, r, sigma, q)

        diff = price - price_est
        if abs(diff) < precision:
            return sigma

        if vega == 0.0:
            break

        sigma += diff / vega

        # Keep sigma within bounds
        if sigma <= 0.0:
            sigma = 0.01

    # If Newton-Raphson fails to converge perfectly, return the closest approximation if it's reasonable
    if sigma > 0 and sigma < 5.0:
        return sigma
    return np.nan


def calculate_greeks(S, K, T, r, sigma, option_type="CE", q=0.0):
    if T <= 0 or np.isnan(sigma) or sigma <= 0:
        return {"delta": np.nan, "gamma": np.nan, "theta": np.nan, "vega": np.nan, "iv": np.nan}

    _d1 = d1(S, K, T, r, sigma, q)
    _d2 = d2(S, K, T, r, sigma, q)

    gamma = (norm.pdf(_d1) * np.exp(-q * T)) / (S * sigma * np.sqrt(T))
    vega = S * np.exp(-q * T) * norm.pdf(_d1) * np.sqrt(T) / 100.0  # Usually expressed per 1%

    if option_type == "CE":
        delta = np.exp(-q * T) * norm.cdf(_d1)
        theta = (- (S * sigma * np.exp(-q * T) * norm.pdf(_d1)) / (2 * np.sqrt(T))
                 - r * K * np.exp(-r * T) * norm.cdf(_d2)
                 + q * S * np.exp(-q * T) * norm.cdf(_d1)) / 365.0  # Daily theta
    else:
        delta = np.exp(-q * T) * (norm.cdf(_d1) - 1)
        theta = (- (S * sigma * np.exp(-q * T) * norm.pdf(_d1)) / (2 * np.sqrt(T))
                 + r * K * np.exp(-r * T) * norm.cdf(-_d2)
                 - q * S * np.exp(-q * T) * norm.cdf(-_d1)) / 365.0  # Daily theta

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "theta": float(theta),
        "vega": float(vega),
        "iv": float(sigma)
    }
