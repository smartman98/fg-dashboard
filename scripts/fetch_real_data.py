"""실제 CNN Fear & Greed 데이터를 두 소스에서 받아 하나로 합칩니다.

소스 1: GitHub CSV (2011-01-03 ~ 2020-09-18)
소스 2: CNN 공식 API (2020-09-17 ~ 오늘)
"""

import io

import pandas as pd
import requests

CSV_URL = "https://raw.githubusercontent.com/hackingthemarkets/sentiment-fear-and-greed/master/datasets/fear-greed.csv"
API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2020-09-18"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://edition.cnn.com/markets/fear-and-greed",
}


def fetch_csv_history() -> pd.DataFrame:
    """2011-01-03 ~ 2020-09-18 구간의 실제 CNN F&G 데이터."""
    response = requests.get(CSV_URL, timeout=20)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))
    df = df[["Date", "Fear Greed"]].rename(columns={"Fear Greed": "score"})
    df["date"] = pd.to_datetime(df["Date"])
    return df[["date", "score"]]


def fetch_api_history() -> pd.DataFrame:
    """2020-09-17 ~ 오늘 구간의 실제 CNN F&G 데이터."""
    response = requests.get(API_URL, headers=BROWSER_HEADERS, timeout=20)
    response.raise_for_status()
    payload = response.json()
    records = payload["fear_and_greed_historical"]["data"]
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["x"], unit="ms").dt.normalize()
    df = df.rename(columns={"y": "score"})
    return df[["date", "score"]]


def fetch_latest_score() -> dict:
    """오늘 시점의 실시간 F&G 점수와 등급."""
    response = requests.get(API_URL, headers=BROWSER_HEADERS, timeout=20)
    response.raise_for_status()
    payload = response.json()["fear_and_greed"]
    return {
        "date": pd.to_datetime(payload["timestamp"]).normalize(),
        "score": payload["score"],
        "rating": payload["rating"],
    }


def fetch_combined_real_history() -> pd.DataFrame:
    """두 소스를 합쳐 2011-01-03 ~ 오늘까지 실제 F&G 시계열을 만듭니다."""
    csv_df = fetch_csv_history()
    api_df = fetch_api_history()

    combined = pd.concat([csv_df, api_df]).drop_duplicates(subset="date", keep="last")
    combined = combined.sort_values("date").reset_index(drop=True)
    combined["source"] = "cnn_real"
    return combined


if __name__ == "__main__":
    history = fetch_combined_real_history()
    print(f"실제 CNN F&G 데이터: {history['date'].min().date()} ~ {history['date'].max().date()}")
    print(f"총 {len(history)}개 거래일")
    print(history.tail())
