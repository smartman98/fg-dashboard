"""실시간 F&G 점수를 계산해서 Supabase의 live_scores 표에 저장합니다.

GitHub Actions가 (이상적으로는) 5분마다 이 스크립트를 실행합니다.
SUPABASE_URL, SUPABASE_KEY / KIWOOM_PAPER_OVERSEAS_APP_KEY, KIWOOM_PAPER_OVERSEAS_APP_SECRET은
환경변수(GitHub Actions Secrets)로 받습니다.

과거 시세는 Yahoo Finance 대신 증권사 API를 쓰되(2026-07-22 KIS로 교체 후, 2026-07-24
키움으로 재교체), 매 실행마다 420일치를 다시 받으면 호출 제한에 자주 걸리므로
price_cache.csv(fg-index/refresh_price_cache.py로 하루 1번 갱신 후 커밋)를 읽고,
"오늘" 값만 실시간으로 받아 덮어쓴다.

**2026-07-24 KIS→키움 전환 이유**: 같은 시각(장중 휴장으로 알려진 09:00~17:00 KST 구간
포함)에 두 증권사 시세를 나란히 비교해보니, KIS는 정규장 마감가에서 완전히 멈춰있는 반면
키움은 "나이트데스크"(오버나이트 ATS)를 통해 실제로 계속 움직이는 실시간 가격을 준다 —
실측 확인(compare_price_sources.py): KIS QQQ는 세 번 조회 내내 691.9600으로 고정, 키움
QQQ는 690.89→690.72→689.54로 실제 변동. 그래서 F&G 실시간 계산은 키움 쪽이 하루 종일
갱신되고, KIS는 정규장 시간에만 의미 있는 값을 준다.

VIX 현물지수는 증권사 API가 안 줘서 VIX 선물 ETF인 VIXY로 대체했다 (kiwoom_client.py 참고).
"""

import os
from pathlib import Path

import pandas as pd
import requests

from fetch_components import fetch_components
from fetch_real_data import fetch_latest_score
from kiwoom_client import fetch_live_quote
from price_proxy import (
    INTERCEPT_8_VIXY,
    INTERCEPT_VIXY,
    WEIGHTS_8_VIXY,
    WEIGHTS_VIXY,
    compute_price_based_fg,
)

TICKERS = ["QQQ", "VIXY", "IEF", "HYG", "LQD"]
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


def _supabase_headers(supabase_key: str) -> dict:
    return {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
    }


def save_to_supabase(rows: list[dict]) -> None:
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]

    response = requests.post(
        f"{supabase_url}/rest/v1/live_scores",
        headers=_supabase_headers(supabase_key),
        json=rows,
        timeout=20,
    )
    response.raise_for_status()


def _kst_today_range_utc() -> tuple[str, str]:
    """오늘(한국시간) 00:00~24:00을 UTC ISO 문자열 범위로 반환한다."""
    now_kst = pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=9)
    start_kst = now_kst.normalize()
    end_kst = start_kst + pd.Timedelta(days=1)
    return (
        (start_kst - pd.Timedelta(hours=9)).isoformat(),
        (end_kst - pd.Timedelta(hours=9)).isoformat(),
    )


def has_daily_snapshot_today() -> bool:
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]
    start_iso, end_iso = _kst_today_range_utc()
    response = requests.get(
        f"{supabase_url}/rest/v1/live_scores",
        headers=_supabase_headers(supabase_key),
        params={
            "source": "eq.daily_snapshot",
            "computed_at": [f"gte.{start_iso}", f"lt.{end_iso}"],
            "select": "id",
            "limit": "1",
        },
        timeout=20,
    )
    response.raise_for_status()
    return len(response.json()) > 0


if __name__ == "__main__":
    rows = []

    # KIS가 가끔 500/rate-limit을 던지는데, 그것 때문에 CNN 실제값까지 못 남기면 안 된다.
    price_based = None
    try:
        price_based = compute_live_score()
        print(f"가격 기반 계산: {price_based}")
        rows.append({**price_based, "source": "price_based"})
    except Exception as exc:  # noqa: BLE001
        print(f"가격 기반 계산 실패(KIS 오류 등), 이번 실행은 CNN 실제값만 저장합니다: {exc}")

    cnn_real = fetch_latest_score()
    cnn_score = round(float(cnn_real["score"]), 2)
    cnn_row = {
        "as_of": cnn_real["date"].isoformat(),
        "score": cnn_score,
        "source": "cnn_real",
    }
    print(f"CNN 실제값: {cnn_row}")
    rows.append(cnn_row)

    # "일별 계산값"을 CSV+수동 build_index.py 실행에만 의존하지 않고 DB에도 확실히
    # 남긴다(2026-07-26 요청: "일별 계산치는 꼭 저장해야된다"). 오늘 날짜로 이미 하나
    # 있으면 건드리지 않고, 없으면 이번 실행의 값으로 딱 하나만 새로 남긴다 — 그래서
    # 하루에 한 번만 실제로 기록되고(예: 자정 넘어 첫 실행), 이후 갱신 없이 그날의
    # 기록으로 고정된다.
    try:
        if not has_daily_snapshot_today():
            daily_score = price_based["score"] if price_based else cnn_score
            daily_source_note = "price_based" if price_based else "cnn_real"
            rows.append({
                "as_of": pd.Timestamp.now(tz="UTC").isoformat(),
                "score": daily_score,
                "source": "daily_snapshot",
            })
            print(f"오늘의 일별 계산값 최초 기록: {daily_score} (기준: {daily_source_note})")
    except Exception as exc:  # noqa: BLE001
        print(f"일별 계산값 저장 확인 실패(다음 실행에 재시도): {exc}")

    save_to_supabase(rows)
    print(f"Supabase 저장 완료 ({len(rows)}개)")
