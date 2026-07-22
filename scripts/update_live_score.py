"""실시간 F&G 점수를 계산해서 Supabase의 live_scores 표에 저장합니다.

GitHub Actions가 (이상적으로는) 5분마다 이 스크립트를 실행합니다.
SUPABASE_URL, SUPABASE_KEY / KIS_PAPER_APP_KEY, KIS_PAPER_APP_SECRET은
환경변수(GitHub Actions Secrets)로 받습니다.

과거 시세는 Yahoo Finance 대신 KIS API를 쓰되(2026-07-22 교체), 매 실행마다 420일치를
다시 받으면 KIS 호출 제한에 자주 걸리므로 price_cache.csv(fg-index/refresh_price_cache.py로
하루 1번 갱신 후 커밋)를 읽고, "오늘" 값만 실시간으로 KIS에서 받아 덮어쓴다.

VIX 현물지수는 KIS가 안 줘서 VIX 선물 ETF인 VIXY로 대체했다 (kis_price_client.py 참고).
"""

import os
from pathlib import Path

import pandas as pd
import requests

from fetch_components import fetch_components
from fetch_real_data import fetch_latest_score
from kis_price_client import EXCHANGE_BY_TICKER, fetch_live_quote
from price_proxy import (
    INTERCEPT_8_VIXY,
    INTERCEPT_VIXY,
    WEIGHTS_8_VIXY,
    WEIGHTS_VIXY,
    compute_price_based_fg,
)

TICKERS = list(EXCHANGE_BY_TICKER)  # QQQ, VIXY, IEF, HYG, LQD
CACHE_PATH = Path(__file__).resolve().parent / "price_cache.csv"
STALE_WARNING_DAYS = 3


def _load_cached_history() -> pd.DataFrame:
    df = pd.read_csv(CACHE_PATH, index_col="date", parse_dates=True)
    age_days = (pd.Timestamp.now().normalize() - df.index.max()).days
    if age_days > STALE_WARNING_DAYS:
        print(f"경고: price_cache.csv가 {age_days}일 전 데이터임. refresh_price_cache.py 재실행 필요.")
    return df


def compute_live_score() -> dict:
    history = _load_cached_history()

    live_quotes = {ticker: fetch_live_quote(ticker) for ticker in TICKERS}

    today = pd.Timestamp.now().normalize()

    series_map = {}
    for ticker in TICKERS:
        series = history[ticker].copy()
        series.loc[today] = live_quotes[ticker]["price"]
        series_map[ticker] = series.sort_index()

    # 2020-09-18 이후는 CNN이 공개하는 나머지 3개 지표(풋/콜·강도·폭)를 받아서
    # 8개 지표 모델을 쓴다. 실패하면(네트워크 문제 등) 5개 지표 모델로 자동 대체.
    try:
        extra = fetch_components().set_index("date").sort_index()
        extra = extra.reindex(series_map["QQQ"].index).ffill()
        put_call, strength, breadth = extra["put_call"], extra["strength"], extra["breadth"]
    except Exception as exc:  # noqa: BLE001
        print(f"3개 추가 지표 조회 실패, 5개 지표 모델로 대체합니다: {exc}")
        put_call = strength = breadth = None

    fg_series = compute_price_based_fg(
        qqq=series_map["QQQ"],
        vix=series_map["VIXY"],
        ief=series_map["IEF"],
        hyg=series_map["HYG"],
        lqd=series_map["LQD"],
        put_call=put_call,
        strength=strength,
        breadth=breadth,
        weights=WEIGHTS_VIXY,
        intercept=INTERCEPT_VIXY,
        weights_8=WEIGHTS_8_VIXY,
        intercept_8=INTERCEPT_8_VIXY,
    )

    return {
        "as_of": live_quotes["QQQ"]["as_of"].isoformat(),
        "score": round(float(fg_series.iloc[-1]), 2),
    }


def save_to_supabase(rows: list[dict]) -> None:
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]

    response = requests.post(
        f"{supabase_url}/rest/v1/live_scores",
        headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
        },
        json=rows,
        timeout=20,
    )
    response.raise_for_status()


if __name__ == "__main__":
    rows = []

    # KIS가 가끔 500/rate-limit을 던지는데, 그것 때문에 CNN 실제값까지 못 남기면 안 된다.
    try:
        price_based = compute_live_score()
        print(f"가격 기반 계산: {price_based}")
        rows.append({**price_based, "source": "price_based"})
    except Exception as exc:  # noqa: BLE001
        print(f"가격 기반 계산 실패(KIS 오류 등), 이번 실행은 CNN 실제값만 저장합니다: {exc}")

    cnn_real = fetch_latest_score()
    cnn_row = {
        "as_of": cnn_real["date"].isoformat(),
        "score": round(float(cnn_real["score"]), 2),
        "source": "cnn_real",
    }
    print(f"CNN 실제값: {cnn_row}")
    rows.append(cnn_row)

    save_to_supabase(rows)
    print(f"Supabase 저장 완료 ({len(rows)}개)")
