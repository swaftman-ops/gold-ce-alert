import os
import numpy as np
import pandas as pd
import requests

SYMBOL, INTERVAL = "XAU/USD", "5min"
LENGTH, MULT = 22, 3.0            # same as your TradingView settings (close-price mode)
STATE_FILE = "last_alert.txt"


def fetch():
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={"symbol": SYMBOL, "interval": INTERVAL, "outputsize": 500,
                "order": "asc", "timezone": "UTC",
                "apikey": os.environ["TWELVEDATA_KEY"]},
        timeout=30,
    )
    data = r.json()
    if data.get("status") != "ok":
        raise SystemExit(f"Data error: {data}")
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    now = pd.Timestamp.now(tz="UTC")
    # keep only fully closed candles
    df = df[df["datetime"] + pd.Timedelta(minutes=5) <= now].reset_index(drop=True)
    return df


def chandelier(df):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    n = len(df)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = np.full(n, np.nan)
    atr[LENGTH - 1] = tr[:LENGTH].mean()
    for i in range(LENGTH, n):                      # Wilder's RMA, same as TradingView
        atr[i] = (atr[i - 1] * (LENGTH - 1) + tr[i]) / LENGTH

    hi = pd.Series(c).rolling(LENGTH).max().values  # close-price extremums
    lo = pd.Series(c).rolling(LENGTH).min().values
    long_raw, short_raw = hi - MULT * atr, lo + MULT * atr
    long_stop, short_stop = long_raw.copy(), short_raw.copy()
    direction = np.ones(n)
    for i in range(LENGTH, n):
        if c[i - 1] > long_stop[i - 1]:
            long_stop[i] = max(long_raw[i], long_stop[i - 1])
        if c[i - 1] < short_stop[i - 1]:
            short_stop[i] = min(short_raw[i], short_stop[i - 1])
        if c[i] > short_stop[i - 1]:
            direction[i] = 1
        elif c[i] < long_stop[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return direction, long_stop, short_stop


def tg(text):
    r = requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text},
        timeout=30,
    )
    r.raise_for_status()


def ist(t):
    return t.tz_convert("Asia/Kolkata").strftime("%d %b %H:%M IST")


def main():
    df = fetch()
    d, ls, ss = chandelier(df)
    n, times = len(df), df["datetime"]

    # manual run = send a test message so you can confirm everything works
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        trend = "BUY (up-trend)" if d[-1] == 1 else "SELL (down-trend)"
        tg(f"Test OK. {SYMBOL} 5m Chandelier Exit trend now: {trend}\n"
           f"Last closed candle {ist(times.iloc[-1])}, close {df['close'].iloc[-1]:.2f}")

    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w") as f:
            f.write(times.iloc[-1].isoformat())
        print("Initialised state")
        return
    with open(STATE_FILE) as f:
        last = pd.Timestamp(f.read().strip())

    for i in range(max(LENGTH, n - 12), n):         # look at the last 12 closed candles
        if d[i] != d[i - 1] and times.iloc[i] > last:
            side = "BUY" if d[i] == 1 else "SELL"
            stop = ls[i] if d[i] == 1 else ss[i]
            tg(f"{SYMBOL} 5m Chandelier Exit: {side}\n"
               f"Close {df['close'].iloc[i]:.2f} | Stop {stop:.2f}\n"
               f"Candle {ist(times.iloc[i])}")
            with open(STATE_FILE, "w") as f:
                f.write(times.iloc[i].isoformat())
            last = times.iloc[i]


main()
