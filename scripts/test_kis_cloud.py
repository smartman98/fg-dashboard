"""GitHub Actions(클라우드) 환경에서 KIS API가 막히는지 확인하는 1회성 테스트.

지금까지 KIS 호출은 전부 조아라님 집 PC(한국 IP)에서만 있었다 — 키움은 이미
update-fg.yml에서 매분 클라우드에서 성공적으로 불리고 있지만(KIWOOM_PAPER_OVERSEAS),
KIS는 아직 클라우드에서 한 번도 안 불러봤다. 자동매매 로직을 클라우드로 옮기기 전에
반드시 확인해야 할 전제.

3단계로 확인한다:
  1) 시세 조회(읽기 전용) — 토큰 발급 + 기본 인증이 막히는지
  2) 국내 소액 지정가 매수 주문 (현재가보다 훨씬 낮게 걸어 체결 안 되게) — 주문 API가 막히는지
  3) 방금 낸 주문 취소 — 정정/취소 API가 막히는지, 그리고 모의계좌에 흔적을 안 남기기 위해

실패해도 실제 돈과 무관한 모의투자 계좌라 안전하다. 성공/실패와 상관없이 마지막에
주문이 남아있으면 안 되므로, 취소가 실패하면 명확히 경고를 남긴다.
"""

import json
import os
import sys

import requests

from kis_price_client import BASE_URL, _headers, _get_with_retry

CANO = os.environ["KIS_PAPER_STOCK"]
ACNT_PRDT_CD = "01"
TEST_STOCK = "472150"  # 이미 보유 중인 종목이라 소액 매수 테스트에 안전


def step1_quote():
    print("[1/3] 시세 조회 테스트 (읽기 전용)...")
    response = _get_with_retry(
        f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
        headers={**_headers("FHKST01010200"), "tr_cont": ""},
        params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": TEST_STOCK},
    )
    if response.status_code != 200:
        print(f"  실패: HTTP {response.status_code} — {response.text[:300]}")
        return None
    data = response.json()
    if data.get("rt_cd") != "0":
        print(f"  실패: {data.get('msg1')}")
        return None
    current_price = int(data["output1"]["askp1"]) or int(data["output1"]["bidp1"])
    print(f"  성공 — {TEST_STOCK} 현재 호가 근처: {current_price}원")
    return current_price


def step2_place_order(safe_price: int):
    print(f"[2/3] 소액 매수 주문 테스트 ({safe_price}원, 1주, 체결 안 되게 낮게)...")
    body = {
        "CANO": CANO, "ACNT_PRDT_CD": ACNT_PRDT_CD, "PDNO": TEST_STOCK,
        "ORD_DVSN": "00", "ORD_QTY": "1", "ORD_UNPR": str(safe_price),
        "EXCG_ID_DVSN_CD": "KRX", "SLL_TYPE": "", "CNDT_PRIC": "",
    }
    headers = {**_headers("VTTC0012U"), "tr_cont": "", "Accept": "text/plain", "charset": "UTF-8"}
    response = requests.post(
        f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash",
        headers=headers, data=json.dumps(body), timeout=20,
    )
    if response.status_code != 200:
        print(f"  실패: HTTP {response.status_code} — {response.text[:300]}")
        return None
    data = response.json()
    if data.get("rt_cd") != "0":
        print(f"  실패: {data.get('msg1')}")
        return None
    out = data["output"]
    print(f"  성공 — 주문번호 {out['ODNO']} 접수됨")
    return out


def step3_cancel_order(order: dict):
    print(f"[3/3] 방금 낸 주문 취소 테스트 (주문번호 {order['ODNO']})...")
    body = {
        "CANO": CANO, "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "KRX_FWDG_ORD_ORGNO": order["KRX_FWDG_ORD_ORGNO"], "ORGN_ODNO": order["ODNO"],
        "ORD_DVSN": "00", "RVSE_CNCL_DVSN_CD": "02",
        "ORD_QTY": "0", "ORD_UNPR": "0", "QTY_ALL_ORD_YN": "Y", "EXCG_ID_DVSN_CD": "KRX",
    }
    headers = {**_headers("VTTC0013U"), "tr_cont": "", "Accept": "text/plain", "charset": "UTF-8"}
    response = requests.post(
        f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-rvsecncl",
        headers=headers, data=json.dumps(body), timeout=20,
    )
    if response.status_code != 200:
        print(f"  실패: HTTP {response.status_code} — {response.text[:300]}")
        return False
    data = response.json()
    if data.get("rt_cd") != "0":
        print(f"  실패: {data.get('msg1')}")
        return False
    print("  성공 — 취소 완료, 모의계좌에 흔적 안 남음")
    return True


def main():
    price = step1_quote()
    if price is None:
        print("\n결론: 시세 조회부터 막힘 — KIS가 클라우드 IP를 차단하는 것으로 보임")
        sys.exit(1)

    safe_price = int(price * 0.85 // 10 * 10)  # 현재가의 85% 수준, 10원 단위로 반올림
    order = step2_place_order(safe_price)
    if order is None:
        print("\n결론: 시세 조회는 되지만 주문 접수는 막힘")
        sys.exit(1)

    cancelled = step3_cancel_order(order)
    if not cancelled:
        print(f"\n경고: 주문 취소 실패 — 계좌에 주문번호 {order['ODNO']}가 남아있을 수 있음, 확인 필요")
        sys.exit(1)

    print("\n결론: 시세 조회 · 주문 접수 · 주문 취소 전부 클라우드에서 정상 동작함")


if __name__ == "__main__":
    main()
