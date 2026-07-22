"""Yahoo Finance 차트 API에서 직접 일별 가격 데이터를 가져옵니다.

yfinance 라이브러리가 간헐적으로 차단되는 문제가 있어,
동일한 Yahoo Finance 엔드포인트를 requests로 직접 호출합니다.
"""

from datetime import datetime, timezone

import pandas as pd
import requests

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}


def fetch_price_history(ticker: str, start: datetime, end: datetime | None = None) -> pd.Series:
    """티커의 일별 종가를 pd.Series(index=date)로 반환합니다."""
    end = end or datetime.now(timezone.utc)
    period1 = int(start.replace(tzinfo=timezone.utc).timestamp())
    period2 = int(end.replace(tzinfo=timezone.utc).timestamp())

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={period1}&period2={period2}&interval=1d"
    )
    response = requests.get(url, headers=BROWSER_HEADERS, timeout=20)
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]

    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]

    dates = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("America/New_York").normalize().tz_localize(None)
    series = pd.Series(closes, index=dates, name=ticker).dropna()
    series = series[~series.index.duplicated(keep="last")]
    return series.sort_index()


def fetch_live_quote(ticker: str) -> dict:
    """현재 가격 한 개를 가져옵니다. 프리마켓/애프터마켓(시간외) 가격도 포함합니다.

    includePrePost=true로 1분봉을 받아서, 그중 가장 최근 값을 씁니다.
    정규장이 닫혀 있어도 시간외 거래가 있으면 그 가격을 반영합니다.
    (VIX처럼 시간외 거래 자체가 없는 지수는 정규장 값만 나옵니다.)
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1m&includePrePost=true"
    response = requests.get(url, headers=BROWSER_HEADERS, timeout=20)
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]

    # 거래가 전혀 없었던 티커(예: 공휴일의 VIX)는 "timestamp" 키 자체가 없을 수 있음
    meta = result.get("meta", {})
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []

    # None(거래 없는 분)을 걸러내고 가장 최근 값을 취함
    valid = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
    if not valid:
        if "regularMarketPrice" in meta and "regularMarketTime" in meta:
            as_of = pd.to_datetime(meta["regularMarketTime"], unit="s", utc=True)
            return {"price": meta["regularMarketPrice"], "as_of": as_of}
        raise RuntimeError(f"{ticker}: Yahoo Finance 응답에 쓸 수 있는 가격이 없음 (분봉도 meta도 비어있음)")

    last_ts, last_price = valid[-1]
    return {"price": last_price, "as_of": pd.to_datetime(last_ts, unit="s", utc=True)}


if __name__ == "__main__":
    prices = fetch_price_history("QQQ", datetime(2009, 1, 1))
    print(f"{prices.index.min().date()} ~ {prices.index.max().date()}, {len(prices)}개")
    print(prices.tail())
