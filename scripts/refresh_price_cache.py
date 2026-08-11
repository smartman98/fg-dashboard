"""5개 티커(QQQ/VIXY/IEF/HYG/LQD)의 과거 시세를 받아 price_cache.csv를 갱신한다.

2026-08-11 추가: 이 캐시가 커밋된 채로 20일 넘게 방치돼(마지막 갱신 2026-07-22),
GitHub Actions가 매 실행마다 낡은 과거 데이터로 F&G를 계산하고 있었다 —
같은 순간에 로컬(신선한 캐시)과 배포본(낡은 캐시)이 5점 넘게 벌어지는 원인이었다.
KIS 인증 없이 돌 수 있도록 price_fetcher.py(Yahoo Finance 직접 호출)를 쓴다 —
GitHub Actions Secrets에 KIS 키를 새로 추가할 필요가 없다.
매일 자동으로 갱신+커밋하도록 refresh-price-cache.yml 워크플로에서 이 스크립트를 돈다.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from price_fetcher import fetch_price_history

TICKERS = ["QQQ", "VIXY", "IEF", "HYG", "LQD"]
HISTORY_DAYS = 420
CACHE_PATH = Path(__file__).resolve().parent / "price_cache.csv"


def refresh() -> pd.DataFrame:
    start = datetime.now() - timedelta(days=HISTORY_DAYS)

    series_by_ticker = {}
    for ticker in TICKERS:
        print(f"{ticker} 과거 시세 받는 중...")
        series_by_ticker[ticker] = fetch_price_history(ticker, start)

    df = pd.DataFrame(series_by_ticker).sort_index()
    df.index.name = "date"
    df.to_csv(CACHE_PATH, encoding="utf-8-sig")
    return df


if __name__ == "__main__":
    df = refresh()
    print(f"\n저장 완료: {CACHE_PATH} ({df.index.min().date()} ~ {df.index.max().date()}, {len(df)}행)")
    print(df.tail())
