"""CNN F&G의 원래 7개 지표 중, 가격 데이터만으로는 재현이 불가능한 3개
(풋/콜 비율, 주가 강도, 주가 폭)를 CNN 공식 API에서 직접 받아온다.

2020-09-18 이후 데이터만 제공됨 (CNN도 그 이전 구간별 데이터는 안 줌).
"""

import pandas as pd
import requests

API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2020-09-18"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://edition.cnn.com/markets/fear-and-greed",
}

# CNN 응답 필드명 -> 우리 컬럼명
COMPONENT_KEYS = {
    "put_call_options": "put_call",
    "stock_price_strength": "strength",
    "stock_price_breadth": "breadth",
}


def fetch_components() -> pd.DataFrame:
    """날짜별로 3개 지표의 원본값(raw y)을 받아온다."""
    response = requests.get(API_URL, headers=BROWSER_HEADERS, timeout=20)
    response.raise_for_status()
    payload = response.json()

    frames = []
    for cnn_key, col_name in COMPONENT_KEYS.items():
        records = payload[cnn_key]["data"]
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["x"], unit="ms").dt.normalize()
        df = df[["date", "y"]].rename(columns={"y": col_name})
        df = df.drop_duplicates(subset="date", keep="last")
        frames.append(df.set_index("date"))

    merged = pd.concat(frames, axis=1).reset_index()
    return merged


if __name__ == "__main__":
    df = fetch_components()
    print(f"구간: {df['date'].min().date()} ~ {df['date'].max().date()}, {len(df)}개 거래일")
    print(df.tail())
