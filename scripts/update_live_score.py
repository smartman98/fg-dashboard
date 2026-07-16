"""실시간 F&G 점수를 계산해서 Supabase의 live_scores 표에 저장합니다.

GitHub Actions가 5분마다 이 스크립트를 실행합니다.
SUPABASE_URL, SUPABASE_KEY는 환경변수(GitHub Actions Secrets)로 받습니다.
"""

import os
from datetime import datetime, timedelta

import pandas as pd
import requests

from price_fetcher import fetch_live_quote, fetch_price_history
from price_proxy import compute_price_based_fg

TICKERS = ["QQQ", "^VIX", "IEF", "HYG", "LQD"]
HISTORY_DAYS = 420


def compute_live_score() -> dict:
    start = datetime.now() - timedelta(days=HISTORY_DAYS)

    histories = {}
    live_quotes = {}
    for ticker in TICKERS:
        histories[ticker] = fetch_price_history(ticker, start)
        live_quotes[ticker] = fetch_live_quote(ticker)

    today = pd.Timestamp.now().normalize()

    series_map = {}
    for ticker in TICKERS:
        series = histories[ticker].copy()
        series.loc[today] = live_quotes[ticker]["price"]
        series_map[ticker] = series.sort_index()

    fg_series = compute_price_based_fg(
        qqq=series_map["QQQ"],
        vix=series_map["^VIX"],
        ief=series_map["IEF"],
        hyg=series_map["HYG"],
        lqd=series_map["LQD"],
    )

    return {
        "as_of": live_quotes["QQQ"]["as_of"].isoformat(),
        "score": round(float(fg_series.iloc[-1]), 2),
    }


def save_to_supabase(result: dict) -> None:
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]

    response = requests.post(
        f"{supabase_url}/rest/v1/live_scores",
        headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
        },
        json={"as_of": result["as_of"], "score": result["score"]},
        timeout=20,
    )
    response.raise_for_status()


if __name__ == "__main__":
    result = compute_live_score()
    print(f"계산 완료: {result}")
    save_to_supabase(result)
    print("Supabase 저장 완료")
