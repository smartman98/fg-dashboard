"""가격 데이터만으로 F&G 대체 지표를 계산합니다.

실제 CNN 지수가 없는 구간(2011년 이전)을 메우거나,
계산 방식 자체를 검증하는 데 씁니다.

5가지 구성 요소 (CNN의 실제 7개 지표 중, 무료 가격 데이터로 근사 가능한 것들):
- 모멘텀: QQQ 125일 이동평균 대비 괴리율
- 낙폭: QQQ 250일 최고가 대비 하락률
- VIX 수준: VIX가 최근 1년 평균보다 높은 정도 (공포 지표)
- 안전자산 선호: QQQ 20일 수익률 - 국채(IEF) 20일 수익률
- 정크본드 수요: 정크본드(HYG) 20일 수익률 - 우량채(LQD) 20일 수익률

★ 각 지표는 "최근 1년"만 기준으로 표준화합니다(rolling z-score) — 미래를 미리 아는
   lookahead bias를 피하기 위함입니다.

★ 5개 지표를 합치는 가중치는, 2011~2026년 실제 CNN 데이터에 회귀분석(OLS)으로
   맞춘 값입니다. 이 구간에서 실제값과의 상관계수 0.77 수준을 확인했습니다.
"""

import pandas as pd

ROLLING_WINDOW = 252  # 표준화 기준 기간 (거래일 기준 약 1년)

# 2011~2026 실제 CNN 데이터에 회귀분석으로 맞춘 가중치
WEIGHTS = {
    "momentum": 0.3207,
    "drawdown": -0.1571,
    "vix_level": 0.4888,
    "safe_haven": 0.4119,
    "junk_demand": 0.1863,
}
INTERCEPT = -14.5007


def _rolling_zscore_to_0_100(series: pd.Series, invert: bool = False) -> pd.Series:
    rolling_mean = series.rolling(ROLLING_WINDOW, min_periods=60).mean()
    rolling_std = series.rolling(ROLLING_WINDOW, min_periods=60).std()
    z = (series - rolling_mean) / rolling_std
    if invert:
        z = -z
    return (50 + z * 15).clip(0, 100)


def compute_component_scores(
    qqq: pd.Series,
    vix: pd.Series,
    ief: pd.Series,
    hyg: pd.Series,
    lqd: pd.Series,
) -> pd.DataFrame:
    """가중치 적용 전, 5가지 지표 각각을 0~100으로 표준화한 값만 반환합니다.

    이 함수는 compute_price_based_fg()와 fit_weights.py(가중치를 재현하는
    회귀분석 스크립트)가 공유합니다 — 지표 계산 로직을 한 곳에서만 관리하기 위함.
    """
    prices = pd.DataFrame({"qqq": qqq, "vix": vix, "ief": ief, "hyg": hyg, "lqd": lqd})
    prices = prices.ffill()

    ma125 = prices["qqq"].rolling(125, min_periods=20).mean()
    momentum_score = _rolling_zscore_to_0_100((prices["qqq"] - ma125) / ma125)

    rolling_max = prices["qqq"].rolling(250, min_periods=20).max()
    drawdown_score = _rolling_zscore_to_0_100((prices["qqq"] - rolling_max) / rolling_max)

    vix_level_score = _rolling_zscore_to_0_100(prices["vix"], invert=True)

    safe_haven = prices["qqq"].pct_change(20) - prices["ief"].pct_change(20)
    safe_haven_score = _rolling_zscore_to_0_100(safe_haven)

    junk_demand = prices["hyg"].pct_change(20) - prices["lqd"].pct_change(20)
    junk_demand_score = _rolling_zscore_to_0_100(junk_demand)

    return pd.DataFrame(
        {
            "momentum": momentum_score,
            "drawdown": drawdown_score,
            "vix_level": vix_level_score,
            "safe_haven": safe_haven_score,
            "junk_demand": junk_demand_score,
        }
    )


def compute_price_based_fg(
    qqq: pd.Series,
    vix: pd.Series,
    ief: pd.Series,
    hyg: pd.Series,
    lqd: pd.Series,
) -> pd.Series:
    """5가지 시장 데이터를 받아 0~100 F&G 대체 점수를 반환합니다."""
    components = compute_component_scores(qqq, vix, ief, hyg, lqd)

    fg_score = (
        WEIGHTS["momentum"] * components["momentum"]
        + WEIGHTS["drawdown"] * components["drawdown"]
        + WEIGHTS["vix_level"] * components["vix_level"]
        + WEIGHTS["safe_haven"] * components["safe_haven"]
        + WEIGHTS["junk_demand"] * components["junk_demand"]
        + INTERCEPT
    )
    return fg_score.clip(0, 100).round(2)


if __name__ == "__main__":
    from datetime import datetime

    from price_fetcher import fetch_price_history

    start = datetime(2009, 1, 1)
    qqq = fetch_price_history("QQQ", start)
    vix = fetch_price_history("^VIX", start)
    ief = fetch_price_history("IEF", start)
    hyg = fetch_price_history("HYG", start)
    lqd = fetch_price_history("LQD", start)

    fg = compute_price_based_fg(qqq, vix, ief, hyg, lqd)
    print(fg.tail(10))
