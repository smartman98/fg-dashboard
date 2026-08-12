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
    # 8개 지표 모델을 쓴다. 이 8개 지표 모델(상관계수 0.834)과 5개 지표 모델(0.729,
    # 사용자가 정한 기준 0.75 미달)은 스케일 자체가 달라서, 조회가 실패할 때마다
    # 5개 지표 모델로 조용히 대체하면 같은 가격에도 값이 몇 점씩 튀어 보인다
    # (2026-08-11 실측: 같은 순간 8개 모델 50.25 vs 5개 모델 53.86 — 대시보드에
    # "50대↔55대"로 튀는 것으로 관측됨). 그래서 실패하면 이번 실행은 값을 저장하지
    # 않고 건너뛴다 — 대시보드에는 마지막으로 성공한 8개 지표 모델 값이 그대로 남는다.
    extra = fetch_components().set_index("date").sort_index()
    extra = extra.reindex(series_map["QQQ"].index).ffill()
    put_call, strength, breadth = extra["put_call"], extra["strength"], extra["breadth"]

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


def get_previous_daily_snapshot() -> float | None:
    """오늘 이전의 가장 최근 daily_snapshot 점수를 반환한다(없으면 None)."""
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]
    start_iso, _ = _kst_today_range_utc()
    response = requests.get(
        f"{supabase_url}/rest/v1/live_scores",
        headers=_supabase_headers(supabase_key),
        params={
            "source": "eq.daily_snapshot",
            "computed_at": f"lt.{start_iso}",
            "select": "score",
            "order": "computed_at.desc",
            "limit": "1",
        },
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json()
    return float(rows[0]["score"]) if rows else None


def save_signal_note(fg_score: float, rating: str, signal: str, note: str) -> None:
    """대시보드 "기록" 목록(signal_notes 표)에 자동 메모를 남긴다."""
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]
    response = requests.post(
        f"{supabase_url}/rest/v1/signal_notes",
        headers=_supabase_headers(supabase_key),
        json={"fg_score": fg_score, "rating": rating, "signal": signal, "note": note},
        timeout=20,
    )
    response.raise_for_status()


def diagnose_anomaly() -> str:
    """이상 감지 시, 어떤 티커가 얼마나 움직였는지·캐시가 오래됐는지를 사람이 읽을 문장으로 만든다."""
    history = _load_cached_history()
    live_quotes = {ticker: fetch_live_quote(ticker) for ticker in TICKERS}

    moves = {}
    for ticker in TICKERS:
        prev_close = float(history[ticker].iloc[-1])
        now_price = float(live_quotes[ticker]["price"])
        moves[ticker] = (now_price - prev_close) / prev_close * 100

    top_ticker = max(moves, key=lambda t: abs(moves[t]))
    cache_age = (pd.Timestamp.now().normalize() - history.index.max()).days
    move_str = ", ".join(f"{t} {v:+.2f}%" for t, v in moves.items())

    return (
        f"티커별 변동(캐시 마지막 종가 대비 현재가): {move_str}. "
        f"가장 크게 움직인 건 {top_ticker}({moves[top_ticker]:+.2f}%). "
        f"price_cache.csv는 {cache_age}일 전 데이터."
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


# 2026-07-27 수정: "일별 계산값"은 그날의 종가 개념이어야 의미가 있다(사용자: "종가가
# 있어야 쌓을 수 있잖아... 저녁 12시를 기준으로 하는 게 어때"). 하루 중 아무 때나(예:
# 자정 막 넘긴 직후) 처음 도는 실행에서 잡아버리면 사실상 "어제 마지막 값"이나 다름없어
# 종가라고 부르기 애매하다. 그래서 한국시간 23:55~23:59, 하루가 끝나기 직전 5분 창에서만
# 기록하도록 창을 좁혔다(1분 주기 크론이므로 이 창 안에서 최소 한 번은 반드시 걸린다).
_SNAPSHOT_WINDOW_KST_HOUR = 23
_SNAPSHOT_WINDOW_KST_MINUTE_MIN = 55

# 2026-08-11 추가: 종가 기록값이 튀면(계산 버그, 캐시 문제 등) 투자판단에 바로 영향을
# 준다. fg_index.csv 4338개 실제 거래일 기준으로 정상 범위를 재보고 문턱을 잡았다:
# - 일간 변화 절대값 95th/99th percentile: 약 10 / 16 → 여유를 두고 18점 초과면 이상.
# - price_based vs CNN real 격차 절대값 95th percentile: 약 27 → 여유를 두고 30점
#   초과면 이상. (평상시 격차 평균은 10.4로, 어느 정도 벌어지는 건 정상이다.)
JUMP_THRESHOLD = 18
CNN_GAP_THRESHOLD = 30

# 2026-08-12 추가: "종가"뿐 아니라 1분마다 도는 실시간 값도 튈 수 있다(오늘 실측된
# 5개/8개 모델 전환, 20일 묵은 가격캐시 등). 정상 구간(가격캐시 갱신 후) 39개 표본을
# 실측한 결과 분당 변화는 평균 0.03, 최대 0.08에 불과했다 — 3점 초과는 35배 이상
# 여유를 둔 확실한 이상치 기준이다.
MINUTE_JUMP_THRESHOLD = 3.0


def get_previous_price_based_score() -> float | None:
    """가장 최근에 저장된 price_based 점수를 반환한다(분당 이상치 비교용)."""
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]
    response = requests.get(
        f"{supabase_url}/rest/v1/live_scores",
        headers=_supabase_headers(supabase_key),
        params={
            "source": "eq.price_based",
            "select": "score",
            "order": "computed_at.desc",
            "limit": "1",
        },
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json()
    return float(rows[0]["score"]) if rows else None


def is_in_daily_snapshot_window() -> bool:
    now_kst = pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=9)
    return now_kst.hour == _SNAPSHOT_WINDOW_KST_HOUR and now_kst.minute >= _SNAPSHOT_WINDOW_KST_MINUTE_MIN


if __name__ == "__main__":
    rows = []

    # KIS가 가끔 500/rate-limit을 던지는데, 그것 때문에 CNN 실제값까지 못 남기면 안 된다.
    price_based = None
    try:
        price_based = compute_live_score()
        prev_minute_score = get_previous_price_based_score()
        minute_jump = (price_based["score"] - prev_minute_score) if prev_minute_score is not None else None

        if minute_jump is not None and abs(minute_jump) > MINUTE_JUMP_THRESHOLD:
            print(f"실시간 값 이상 감지(직전 저장값 대비 {minute_jump:+.2f}) — 한 번 더 계산해서 재확인합니다.")
            retry = compute_live_score()
            retry_jump = retry["score"] - prev_minute_score
            if abs(retry_jump) > MINUTE_JUMP_THRESHOLD:
                detail = diagnose_anomaly()
                note = (
                    f"실시간 계산값 {price_based['score']}가 직전 저장값({prev_minute_score}) 대비 "
                    f"{minute_jump:+.1f}점 튀어 이상치로 판단해 이번 실행은 저장을 건너뛰었습니다. {detail}"
                )
                print(f"[자동감지] {note}")
                try:
                    save_signal_note(price_based["score"], "자동점검", "이상감지", note)
                except Exception as note_exc:  # noqa: BLE001
                    print(f"이상감지 메모 저장 실패: {note_exc}")
                price_based = None  # 저장을 건너뛰어 대시보드엔 직전 값이 그대로 유지된다.
            else:
                price_based = retry
                print(f"재계산 결과 정상 범위 — {price_based['score']}로 기록합니다.")

        if price_based:
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
    # 남긴다(2026-07-26 요청: "일별 계산치는 꼭 저장해야된다"). 그날의 "종가" 개념이
    # 되도록 한국시간 23:55~23:59에만 기록한다(2026-07-27 수정 — 사용자: "종가가 있어야
    # 쌓을 수 있잖아... 저녁 12시를 기준으로"). 그 창 안에서 오늘 날짜로 아직 없으면
    # 딱 한 번만 남긴다.
    try:
        if is_in_daily_snapshot_window() and not has_daily_snapshot_today():
            daily_score = price_based["score"] if price_based else cnn_score
            daily_source_note = "price_based" if price_based else "cnn_real"
            anomaly_note = None

            if price_based:
                prev_score = get_previous_daily_snapshot()
                jump = (daily_score - prev_score) if prev_score is not None else None
                gap = daily_score - cnn_score
                is_anomalous = (jump is not None and abs(jump) > JUMP_THRESHOLD) or abs(gap) > CNN_GAP_THRESHOLD

                if is_anomalous:
                    print(f"이상 감지(전일 대비 {jump}, CNN 대비 {gap:+.2f}) — 한 번 더 계산해서 재확인합니다.")
                    try:
                        retry = compute_live_score()
                        retry_jump = (retry["score"] - prev_score) if prev_score is not None else None
                        retry_gap = retry["score"] - cnn_score
                        is_anomalous = (
                            (retry_jump is not None and abs(retry_jump) > JUMP_THRESHOLD)
                            or abs(retry_gap) > CNN_GAP_THRESHOLD
                        )
                        if not is_anomalous:
                            daily_score = retry["score"]
                    except Exception:  # noqa: BLE001
                        is_anomalous = True

                    if is_anomalous:
                        detail = diagnose_anomaly()
                        anomaly_note = (
                            f"계산값 {daily_score}"
                            + (f" (전일 대비 {jump:+.1f}점)" if jump is not None else "")
                            + f", CNN 실제값과 격차 {gap:+.1f}점이라 이상치로 판단해 CNN 실제값"
                            f"({cnn_score})으로 대체했습니다. {detail}"
                        )
                        daily_score = cnn_score
                        daily_source_note = "cnn_real(이상감지로 대체)"
                    else:
                        print(f"재계산 결과 정상 범위 — {daily_score}로 기록합니다.")

            rows.append({
                "as_of": pd.Timestamp.now(tz="UTC").isoformat(),
                "score": daily_score,
                "source": "daily_snapshot",
            })
            print(f"오늘의 종가성 일별 계산값 기록: {daily_score} (기준: {daily_source_note})")

            if anomaly_note:
                print(f"[자동감지] {anomaly_note}")
                try:
                    save_signal_note(daily_score, "자동점검", "이상감지", anomaly_note)
                except Exception as note_exc:  # noqa: BLE001
                    print(f"이상감지 메모 저장 실패: {note_exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"일별 계산값 저장 확인 실패(다음 실행에 재시도): {exc}")

    save_to_supabase(rows)
    print(f"Supabase 저장 완료 ({len(rows)}개)")
