"""price_proxy.py에 박혀있는 WEIGHTS/INTERCEPT를 어떻게 구했는지 재현하는 스크립트.

실제 CNN F&G 데이터(2011~현재)와 5가지 가격 기반 지표(momentum, drawdown,
vix_level, safe_haven, junk_demand)를 OLS 회귀로 맞춰서, price_proxy.py의
가중치가 어떻게 나왔는지 재현·검증합니다.

실행:
    python fit_weights.py
"""

from datetime import datetime

import numpy as np

from fetch_real_data import fetch_combined_real_history
from price_fetcher import fetch_price_history
from price_proxy import compute_component_scores

FEATURE_COLS = ["momentum", "drawdown", "vix_level", "safe_haven", "junk_demand"]


def fit():
    real = fetch_combined_real_history().set_index("date")[["score"]]

    start = datetime(2009, 1, 1)
    qqq = fetch_price_history("QQQ", start)
    vix = fetch_price_history("^VIX", start)
    ief = fetch_price_history("IEF", start)
    hyg = fetch_price_history("HYG", start)
    lqd = fetch_price_history("LQD", start)

    components = compute_component_scores(qqq, vix, ief, hyg, lqd)
    components.index.name = "date"

    merged = real.join(components, how="inner").dropna()

    X = merged[FEATURE_COLS].to_numpy()
    y = merged["score"].to_numpy()
    X_design = np.column_stack([X, np.ones(len(X))])

    coefs, *_ = np.linalg.lstsq(X_design, y, rcond=None)
    weights = dict(zip(FEATURE_COLS, coefs[:-1]))
    intercept = coefs[-1]

    predicted = X_design @ coefs
    correlation = np.corrcoef(predicted, y)[0, 1]

    print("=== 회귀 결과 (price_proxy.py의 WEIGHTS/INTERCEPT 재현) ===")
    for name, value in weights.items():
        print(f"  {name}: {value:.4f}")
    print(f"  intercept: {intercept:.4f}")
    print(f"상관계수(실제값 vs 예측값): {correlation:.4f}")
    print(f"학습 구간: {merged.index.min().date()} ~ {merged.index.max().date()} ({len(merged)}개 거래일)")


if __name__ == "__main__":
    fit()
