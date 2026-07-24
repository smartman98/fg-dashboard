"""키움증권(Kiwoom) REST API 클라이언트. kis_price_client.py의 KIS 버전과 같은 역할이지만,
헤더 이름·인증 방식·엔드포인트 구조가 KIS와 달라서 별도 모듈로 새로 만든다.

키움 vs KIS 주요 차이점(2026-07-24 공식 API 스펙 JSON 기준으로 확인):
- TR 식별 헤더가 tr_id가 아니라 api-id.
- 모든 API가 GET이 아니라 POST + JSON body (조회성 API도 마찬가지).
- 토큰 발급 필드명이 appkey/secretkey (KIS는 appkey/appsecret), 응답 필드도 access_token이
  아니라 그냥 token.
- 국내(dostk)와 해외(us)가 완전히 다른 URL 프리픽스(/api/dostk/*, /api/us/*)와 파라미터
  이름 체계(dmst_stex_tp vs stex_tp, KRX/NXT/SOR vs NA/ND/NY)를 씀.
- 키 발급 자체가 KIS와 다르게 실전/모의(국내)/모의(해외) 3세트로 완전히 분리되어 있음
  (계좌번호도 다 다름) — 그래서 자격증명 선택 로직이 KIS보다 한 단계 더 필요하다.

인증 환경변수 (2026-07-24 발급, Windows 사용자 환경변수로 저장됨):
- KIWOOM_APP_KEY / KIWOOM_APP_SECRET             — 실전투자 (계좌 6107-9193)
- KIWOOM_PAPER_APP_KEY / KIWOOM_PAPER_APP_SECRET — 모의투자(국내, 계좌 81312864)
- KIWOOM_PAPER_OVERSEAS_APP_KEY / KIWOOM_PAPER_OVERSEAS_APP_SECRET — 해외모의투자(계좌 61110872)
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

REAL_BASE_URL = "https://api.kiwoom.com"
DEMO_BASE_URL = "https://mockapi.kiwoom.com"

MIN_CALL_INTERVAL_SECONDS = 1.0  # 실측(2026-07-24): 0.3초 간격으로 5~6번째 호출에서 곧장 429 발생 — KIS 수준으로 늘림

TOKEN_CACHE_DIR = Path(__file__).resolve().parent
_last_call_at = 0.0
_token_cache: dict = {}  # cache_key -> {"token":..., "expires_dt":...}


def _throttle() -> None:
    global _last_call_at
    elapsed = time.monotonic() - _last_call_at
    if elapsed < MIN_CALL_INTERVAL_SECONDS:
        time.sleep(MIN_CALL_INTERVAL_SECONDS - elapsed)
    _last_call_at = time.monotonic()


def _credentials(mode: str, market: str) -> tuple[str, str]:
    """mode: "real" | "demo", market: "domestic" | "overseas".

    실전은 국내/해외 구분 없이 키 하나(KIWOOM_APP_KEY)를 쓰고, 모의투자는 국내용과
    해외용 키가 서로 다르다(키움이 실제로 그렇게 발급함 — KIS는 모의 키 하나로 둘 다 커버했었음).
    """
    if mode == "real":
        key, secret = os.environ.get("KIWOOM_APP_KEY"), os.environ.get("KIWOOM_APP_SECRET")
    elif mode == "demo" and market == "domestic":
        key, secret = os.environ.get("KIWOOM_PAPER_APP_KEY"), os.environ.get("KIWOOM_PAPER_APP_SECRET")
    elif mode == "demo" and market == "overseas":
        key, secret = os.environ.get("KIWOOM_PAPER_OVERSEAS_APP_KEY"), os.environ.get("KIWOOM_PAPER_OVERSEAS_APP_SECRET")
    else:
        raise ValueError(f"알 수 없는 mode/market 조합: {mode}/{market}")
    if not key or not secret:
        raise RuntimeError(f"Kiwoom 자격증명 환경변수가 비어있음 (mode={mode}, market={market})")
    return key, secret


def _base_url(mode: str) -> str:
    return REAL_BASE_URL if mode == "real" else DEMO_BASE_URL


def _token_cache_path(mode: str, market: str) -> Path:
    return TOKEN_CACHE_DIR / f".kiwoom_token_cache_{mode}_{market}.json"


def _is_still_valid(cached: dict) -> bool:
    # expires_dt 포맷: YYYYMMDDHHMMSS (KIS의 access_token_token_expired와 같은 자릿수 관례를 따름 — 실제
    # 응답 받아보고 포맷이 다르면 여기만 고치면 됨)
    try:
        expires_at = datetime.strptime(cached["expires_dt"], "%Y%m%d%H%M%S")
    except (KeyError, ValueError):
        return False
    return expires_at - datetime.now() > timedelta(minutes=5)


def _issue_token(mode: str, market: str) -> str:
    cache_key = f"{mode}:{market}"
    if cache_key in _token_cache:
        return _token_cache[cache_key]["token"]

    cache_path = _token_cache_path(mode, market)
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if _is_still_valid(cached):
            _token_cache[cache_key] = cached
            return cached["token"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    app_key, app_secret = _credentials(mode, market)
    _throttle()
    response = requests.post(
        f"{_base_url(mode)}/oauth2/token",
        headers={"content-type": "application/json;charset=UTF-8"},
        data=json.dumps({
            "grant_type": "client_credentials",
            "appkey": app_key,
            "secretkey": app_secret,
        }),
        timeout=20,
    )
    response.raise_for_status()
    body = response.json()
    if "token" not in body:
        raise RuntimeError(f"Kiwoom 토큰 발급 실패 (mode={mode}, market={market}): {body}")

    cache_path.write_text(json.dumps(body), encoding="utf-8")
    _token_cache[cache_key] = body
    return body["token"]


def _headers(mode: str, market: str, api_id: str) -> dict:
    return {
        "content-type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {_issue_token(mode, market)}",
        "api-id": api_id,
        "cont-yn": "N",
        "next-key": "",
    }


def _post(mode: str, market: str, api_id: str, path: str, body: dict, retries: int = 2) -> dict:
    """모든 키움 API가 조회든 주문이든 POST + JSON body라는 게 KIS와의 가장 큰 차이.

    429(rate limit)는 실측으로 초당 1회 스로틀로도 연속 호출 시 발생함 — KIS처럼 짧게
    재시도한다(kis_price_client._get_with_retry와 동일한 완화책)."""
    response = None
    for attempt in range(retries + 1):
        _throttle()
        response = requests.post(
            f"{_base_url(mode)}{path}",
            headers=_headers(mode, market, api_id),
            data=json.dumps(body),
            timeout=20,
        )
        if response.status_code != 429:
            break
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    response.raise_for_status()
    data = response.json()
    if data.get("return_code") not in (0, "0", None):
        raise RuntimeError(f"Kiwoom API 실패 {api_id} ({mode}/{market}): {data}")
    return data


def abs_price(signed_value) -> float:
    """cur_prc/open_pric/high_pric 등 시세 필드는 "부호가 포함된 숫자"로 내려온다 —
    부호는 전일대비 등락 방향(양수=상승, 음수=하락)이지 가격이 실제로 음수라는 뜻이 아니다.
    실제 가격이 필요하면 이 함수로 부호를 떼고 절대값만 취할 것(실측 확인: 2026-07-24,
    472150이 -20815, TQQQ가 -65.7400으로 내려옴 — 둘 다 그날 하락 중이었을 뿐 가격은 양수)."""
    return abs(float(signed_value))


# ── 국내주식 ────────────────────────────────────────────────────────────────

def get_domestic_quote(stk_cd: str, mode: str = "demo") -> dict:
    """주식기본정보요청(ka10001) — 현재가 등 기본 정보. cur_prc가 현재가(원) — 부호 포함이니
    실제 가격이 필요하면 abs_price(quote["cur_prc"])로 쓸 것."""
    return _post(mode, "domestic", "ka10001", "/api/dostk/stkinfo", {"stk_cd": stk_cd})


def get_domestic_orderbook(stk_cd: str, mode: str = "demo") -> dict:
    """주식호가요청(ka10004) — 10단 호가."""
    return _post(mode, "domestic", "ka10004", "/api/dostk/mrkcond", {"stk_cd": stk_cd})


def place_domestic_order(
    stk_cd: str, side: str, qty: int, price: int | None = None,
    trde_tp: str = "0", dmst_stex_tp: str = "KRX", mode: str = "demo",
) -> dict:
    """side: "buy" | "sell". trde_tp 기본값 "0"=보통(지정가). price=None이면 시장가로 간주하고
    ord_uv를 빈 문자열로 보낸다(trde_tp도 "3"으로 바꿔줘야 함 — 호출부에서 지정)."""
    api_id = "kt10000" if side == "buy" else "kt10001"
    body = {
        "dmst_stex_tp": dmst_stex_tp,
        "stk_cd": stk_cd,
        "ord_qty": str(qty),
        "ord_uv": str(price) if price is not None else "",
        "trde_tp": trde_tp,
        "cond_uv": "",
    }
    return _post(mode, "domestic", api_id, "/api/dostk/ordr", body)


def amend_domestic_order(
    orig_ord_no: str, stk_cd: str, qty: int, price: int,
    dmst_stex_tp: str = "KRX", mode: str = "demo",
) -> dict:
    """정정주문(kt10002). qty=0이면 잔량 전부 정정. 정정 시 새 주문번호가 반환됨(KIS와 동일한 특성)."""
    body = {
        "dmst_stex_tp": dmst_stex_tp,
        "orig_ord_no": orig_ord_no,
        "stk_cd": stk_cd,
        "mdfy_qty": str(qty),
        "mdfy_uv": str(price),
        "mdfy_cond_uv": "",
    }
    return _post(mode, "domestic", "kt10002", "/api/dostk/ordr", body)


def cancel_domestic_order(
    orig_ord_no: str, stk_cd: str, qty: int = 0,
    dmst_stex_tp: str = "KRX", mode: str = "demo",
) -> dict:
    """취소주문(kt10003). qty=0이면 잔량 전부 취소."""
    body = {
        "dmst_stex_tp": dmst_stex_tp,
        "orig_ord_no": orig_ord_no,
        "stk_cd": stk_cd,
        "cncl_qty": str(qty),
    }
    return _post(mode, "domestic", "kt10003", "/api/dostk/ordr", body)


def get_domestic_unfilled_orders(stk_cd: str = "", mode: str = "demo") -> dict:
    """미체결요청(ka10075)."""
    body = {
        "all_stk_tp": "1" if stk_cd else "0",
        "trde_tp": "0",
        "stk_cd": stk_cd,
        "stex_tp": "0",
    }
    return _post(mode, "domestic", "ka10075", "/api/dostk/acnt", body)


def get_domestic_filled_orders(stk_cd: str = "", ord_no: str = "", mode: str = "demo") -> dict:
    """체결요청(ka10076)."""
    body = {
        "stk_cd": stk_cd,
        "qry_tp": "1" if stk_cd else "0",
        "sell_tp": "0",
        "ord_no": ord_no,
        "stex_tp": "0",
    }
    return _post(mode, "domestic", "ka10076", "/api/dostk/acnt", body)


def get_domestic_cash_balance(mode: str = "demo") -> dict:
    """예수금상세현황요청(kt00001)."""
    return _post(mode, "domestic", "kt00001", "/api/dostk/acnt", {"qry_tp": "2"})


def get_domestic_holdings(mode: str = "demo") -> dict:
    """계좌평가잔고내역요청(kt00018)."""
    return _post(mode, "domestic", "kt00018", "/api/dostk/acnt", {"qry_tp": "1", "dmst_stex_tp": "KRX"})


# ── 해외주식 ────────────────────────────────────────────────────────────────

EXCHANGE_BY_TICKER = {
    "TQQQ": "ND",
    "QQQ": "ND",
    "SPY": "NY",
    "VIXY": "NA",
    "IEF": "ND",
    "HYG": "NY",  # 실측(2026-07-24): NA(AMEX)로는 "종목 정보가 없습니다" 실패, NY(NYSE Arca 취급)라야 됨
    "LQD": "NY",  # 위와 동일한 이유
}


def get_overseas_quote(stk_cd: str, exchange: str | None = None, mode: str = "demo") -> dict:
    """미국주식 현재가 종목정보(usa20100). cur_prc가 현재가(USD, 부호 포함 — abs_price() 참고).
    exchange 생략 시 티커로 추정."""
    stex_tp = exchange or EXCHANGE_BY_TICKER[stk_cd]
    return _post(mode, "overseas", "usa20100", "/api/us/mrkcond", {"stex_tp": stex_tp, "stk_cd": stk_cd})


def get_overseas_orderbook(stk_cd: str, exchange: str | None = None, mode: str = "demo") -> dict:
    """미국주식 현재가 10호가(usa20101)."""
    stex_tp = exchange or EXCHANGE_BY_TICKER[stk_cd]
    return _post(mode, "overseas", "usa20101", "/api/us/mrkcond", {"stex_tp": stex_tp, "stk_cd": stk_cd})


def place_overseas_order(
    stk_cd: str, side: str, qty: int, price: float | None = None,
    exchange: str | None = None, trde_tp: str = "00", mode: str = "demo",
) -> dict:
    """side: "buy" | "sell". trde_tp 기본값 "00"=지정가. price=None+trde_tp="03"이면 시장가."""
    api_id = "ust20000" if side == "buy" else "ust20001"
    stex_tp = exchange or EXCHANGE_BY_TICKER[stk_cd]
    body = {
        "stex_tp": stex_tp,
        "stk_cd": stk_cd,
        "ord_qty": str(qty),
        "ord_uv": str(price) if price is not None else "",
        "trde_tp": trde_tp,
    }
    if side == "sell":
        body["stop_pric"] = ""
    return _post(mode, "overseas", api_id, "/api/us/ordr", body)


def amend_overseas_order(
    orig_ord_no: str, stk_cd: str, price: float,
    exchange: str | None = None, mode: str = "demo",
) -> dict:
    """정정주문(ust20002). 국내와 달리 수량 정정 필드가 없음 — 가격만 정정 가능."""
    stex_tp = exchange or EXCHANGE_BY_TICKER[stk_cd]
    body = {
        "orig_ord_no": orig_ord_no,
        "stex_tp": stex_tp,
        "stk_cd": stk_cd,
        "mdfy_uv": str(price),
        "stop_pric": "",
    }
    return _post(mode, "overseas", "ust20002", "/api/us/ordr", body)


def cancel_overseas_order(
    orig_ord_no: str, stk_cd: str, exchange: str | None = None, mode: str = "demo",
) -> dict:
    """취소주문(ust20003)."""
    stex_tp = exchange or EXCHANGE_BY_TICKER[stk_cd]
    body = {"orig_ord_no": orig_ord_no, "stex_tp": stex_tp, "stk_cd": stk_cd}
    return _post(mode, "overseas", "ust20003", "/api/us/ordr", body)


def get_overseas_unfilled_orders(stk_cd: str = "", mode: str = "demo") -> dict:
    """미국주식 원장 미체결(ust21050)."""
    body = {"ord_dt": "", "slby_tp": "0", "stex_tp": "", "stk_cd": stk_cd}
    return _post(mode, "overseas", "ust21050", "/api/us/acnt", body)


def get_overseas_balance(stk_cd: str = "", mode: str = "demo") -> dict:
    """미국주식 원장잔고확인(ust21070)."""
    body = {"stex_tp": "", "stk_cd": stk_cd}
    return _post(mode, "overseas", "ust21070", "/api/us/acnt", body)


def get_overseas_cash_balance(mode: str = "demo") -> dict:
    """미국주식 예수금 상세(ust21160)."""
    return _post(mode, "overseas", "ust21160", "/api/us/acnt", {})


def fetch_live_quote(ticker: str, mode: str = "demo") -> dict:
    """kis_price_client.fetch_live_quote()와 같은 반환 형식({"price":, "as_of":}) —
    live_fg.py/update_live_score.py가 import만 바꿔서 그대로 쓸 수 있게 맞췄다.

    as_of는 실제 체결시각이 아니라 이 함수를 호출한 시점의 wall-clock 시각이다
    (kis_price_client.py와 동일한 한계 — 이전 세션에서 "as_of가 계속 갱신되니 최신"이라고
    잘못 판단했던 실수를 반복하지 말 것). 진짜 체결시각이 필요하면 fetch_live_quote_with_time()을 쓸 것.
    """
    quote = get_overseas_quote(ticker, mode=mode)
    return {"price": abs_price(quote["cur_prc"]), "as_of": pd.Timestamp.now(tz="UTC")}


def fetch_live_quote_with_time(ticker: str, mode: str = "demo") -> dict:
    """usa20101(10호가)의 bid_tm(HH:mm)/dt(YYYYMMDD)을 같이 반환 — 프리마켓 시간대에
    이 시각이 실제로 갱신되는지 보고 "진짜 실시간 데이터인지" 검증하는 용도."""
    quote = get_overseas_orderbook(ticker, mode=mode)
    return {
        "price": abs_price(quote["cur_prc"]),
        "quote_date": quote.get("dt"),
        "quote_time": quote.get("bid_tm"),
        "as_of": pd.Timestamp.now(tz="UTC"),
    }


if __name__ == "__main__":
    print("국내(472150) 현재가:", abs_price(get_domestic_quote("472150")["cur_prc"]))
    print("해외(TQQQ) 현재가:", abs_price(get_overseas_quote("TQQQ")["cur_prc"]))
