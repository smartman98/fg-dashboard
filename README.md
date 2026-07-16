# F&G 지수 대시보드

FABOT 매매 신호 판단용 공포·탐욕(Fear & Greed) 지수 대시보드입니다.

## 기능

- 오늘의 F&G 지수 + 매매 신호 (실제 CNN 데이터 + 2011년 이전은 가격 기반 계산)
- 2009년~오늘까지 F&G 지수 추이 차트 (기간 필터: 30일/90일/1년/전체)
- **신호 메모 저장** — Supabase에 실시간 저장되어 새로고침해도 남습니다

## 데이터 새로고침

`fg_data.js`는 [fg-index 프로젝트](https://github.com/smartman98)의 `export_dashboard_data.py`로 생성됩니다.

플레이: https://smartman98.github.io/fg-dashboard/
