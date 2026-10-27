"""
Market Bias Platform — GEX (Gamma Exposure) Simulator Engine
Generates realistic Options Gamma Exposure (GEX) data for UI and AI analysis.
"""

import math
import random
import yfinance as yf

def get_live_spot_price(asset: str) -> float:
    """Fetches the real-time spot price directly from Yahoo Finance."""
    ticker_map = {
        "SPX": "^GSPC",
        "NASDAQ": "^IXIC",
        "GOLD": "GC=F"
    }
    ticker = ticker_map.get(asset)
    if not ticker:
        return 0.0
    
    try:
        t = yf.Ticker(ticker)
        # Try to get the live market price first
        price = t.info.get('regularMarketPrice')
        if not price:
            # Fallback to the last close from history if info is missing
            hist = t.history(period="1d")
            if not hist.empty:
                price = hist['Close'].iloc[-1]
        return price or 0.0
    except Exception:
        return 0.0

def simulate_gex_data(asset: str, current_price: float = 0.0) -> dict:
    """
    Generates a realistic Options Chain GEX profile based on the current spot price.
    Returns a dict with Call Walls, Put Walls, and Order Flow bias.
    """
    # If no price is passed, or if we want to force real-time:
    live_price = get_live_spot_price(asset)
    if live_price > 0.0:
        current_price = live_price

    if current_price <= 0:
        return {}

    # Define strike steps based on asset
    if asset == "SPX":
        step = 50
    elif asset == "NASDAQ" or asset == "NDX":
        step = 100
    elif asset == "GOLD":
        step = 20 # spot gold step
    else:
        step = round(current_price * 0.01)
        if step == 0:
            step = 1

    # Find the nearest ATM (At-The-Money) strike
    atm_strike = round(current_price / step) * step

    strikes = []
    
    # Generate 4 strikes below and 4 strikes above
    for i in range(-4, 5):
        strike_price = atm_strike + (i * step)
        
        # Base GEX magnitude (simulate log-normal distribution centered slightly above ATM)
        distance = abs(i - 0.5)
        base_gex = 300.0 * math.exp(-(distance ** 2) / 4)
        
        # Add noise
        noise = random.uniform(0.7, 1.3)
        gex_value = base_gex * noise
        
        # Calls (positive GEX usually above spot), Puts (negative GEX usually below spot)
        if i >= 0:
            # Positive GEX (Call territory)
            gex = round(gex_value, 1)
            if i == 2:
                role = "Call Wall chính (Bức tường kháng cự mạnh nhất)"
                gex = round(gex * 1.5, 1) # Make the wall stand out
            elif i == 4:
                role = "Call Wall phụ (Kháng cự mục tiêu tiếp theo)"
            elif i == 0:
                role = "Vùng giao dịch lân cận giá hiện tại (ATM)"
            else:
                role = "Vùng đệm hỗ trợ trung gian / Kháng cự mỏng"
        else:
            # Puts (Negative GEX territory, or sometimes positive if put sellers dominate)
            # Let's simulate a standard skew where downside puts act as support (Negative GEX)
            gex = round(-gex_value * 0.8, 1) 
            if i == -2:
                role = "Put Wall chính (Vùng hỗ trợ/đệm thanh khoản mạnh)"
                gex = round(gex * 1.5, 1)
            elif i == -4:
                role = "Vùng hỗ trợ xa (Tail Risk Support)"
            else:
                role = "Vùng chuyển tiếp xu hướng"
                
        strikes.append({
            "strike": strike_price,
            "gex": gex,
            "role": role
        })

    # Determine Delta Volume & Gamma Regime based on the skew
    net_gex = sum(s["gex"] for s in strikes)
    
    if net_gex > 0:
        regime = "Positive Gamma (Đỡ giá, dao động có kiểm soát)"
        delta_vol = "Dòng lệnh mua chủ động (Aggressive Buying) áp đảo."
    else:
        regime = "Negative Gamma (Biến động mạnh, nguy cơ sập sốc)"
        delta_vol = "Dòng lệnh bán chủ động (Aggressive Selling) gia tăng."

    return {
        "asset": asset,
        "spot_price": current_price,
        "regime": regime,
        "delta_volume": delta_vol,
        "strikes": strikes,
        "net_gex": round(net_gex, 1)
    }
