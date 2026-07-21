"""오늘의 F&G 지수를 확인하고, FABOT 매매 규칙에 따른 신호를 판정합니다.

매매 규칙:
- TQQQ 매수: F&G<=25 -> 실탄 25% / F&G<=20 -> 50% / F&G<=15 -> 100%
- TQQQ 매도: F&G>=75 -> 보유분 50% / F&G>=80 -> 잔량 전량
- 커버드콜 추가매수: F&G 35~65(평시) -> 실탄 20%
"""

from fetch_real_data import fetch_latest_score


def judge_signal(score: float) -> str:
    if score <= 15:
        return "TQQQ 매수 100% (극단적 공포)"
    if score <= 20:
        return "TQQQ 매수 50%"
    if score <= 25:
        return "TQQQ 매수 25%"
    if score >= 80:
        return "TQQQ 매도 전량 (극단적 탐욕)"
    if score >= 75:
        return "TQQQ 매도 50%"
    if 35 <= score <= 65:
        return "커버드콜 추가매수 20% (평시)"
    return "대기 (매수/매도 조건 밖)"


if __name__ == "__main__":
    latest = fetch_latest_score()
    signal = judge_signal(latest["score"])

    print("=== 오늘의 F&G 신호 리포트 ===")
    print(f"날짜: {latest['date'].date()}")
    print(f"F&G 점수: {latest['score']:.1f} ({latest['rating']})")
    print(f"판정 신호: {signal}")
