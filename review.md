# AIFFEL Campus Code Peer Review Template
- 코더 : 변인선
- 리뷰어 : 안현정

대상 저장소: https://github.com/hera93939393-ctrl/fg-dashboard

# PRT(Peer Review Template)

**[x] 1. 주어진 문제를 해결하는 완성된 코드가 제출되었나요?**

전체적으로 돌려봤을 때 실제로 잘 작동하는 결과물이었습니다. 실제 CNN F&G 지수랑 2011년 이전 구간을 채우는 가격 기반 근사치를 하나로 합치는 부분([scripts/fetch_real_data.py:58-66](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/scripts/fetch_real_data.py#L58-L66) `fetch_combined_real_history()`)부터 시작해서, 점수에 따라 TQQQ 매수/매도 비율을 정하는 신호 판정 로직까지 ([scripts/today_signal.py:12-25](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/scripts/today_signal.py#L12-L25), 프론트에도 같은 로직이 [index.html:668-676](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/index.html#L668-L676)에 그대로 들어가 있음) 흐름이 끊기지 않고 이어집니다.

특히 인상적이었던 건 GitHub Actions로 5분마다 값을 갱신하는 부분이었습니다. [.github/workflows/update-fg.yml](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/.github/workflows/update-fg.yml)이 [scripts/update_live_score.py](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/scripts/update_live_score.py)를 돌려서 Supabase에 쌓고, 대시보드는 그걸 REST API로 실시간 조회하는 구조([index.html:537-561](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/index.html#L537-L561))라 정적 페이지인데도 계속 살아있는 느낌이 들었습니다. 메모를 남기고 저장하는 기능([index.html:611-655](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/index.html#L611-L655))도 잘 붙어 있어서, README에 적힌 기능들은 다 구현이 됐다고 봐도 될 것 같습니다.

**[x] 2. 핵심적이거나 복잡한 부분에 설명이 잘 되어있어 코드가 잘 이해되었나요?**

주석을 꽤 신경 써서 써놓으신 것 같습니다. [scripts/price_proxy.py:1-17](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/scripts/price_proxy.py#L1-L17)을 보면 왜 이 5가지 지표를 골랐는지, rolling z-score를 쓰는 이유가 lookahead bias를 피하기 위해서라는 것, 가중치를 OLS 회귀로 맞췄고 상관계수가 0.77 정도 나왔다는 것까지 다 적혀 있어서 계산 로직을 따라가는 데 크게 막히지 않았습니다.

[scripts/price_fetcher.py:1-5](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/scripts/price_fetcher.py#L1-L5)에 `yfinance` 라이브러리를 안 쓰고 직접 API를 호출하게 된 이유를 남겨두신 것도 좋았습니다. 이런 걸 안 적어두면 나중에 다시 봤을 때 "왜 굳이 이렇게 했지?" 싶어지는데, 미리 설명이 있어서 이해가 편했습니다. JS 쪽에도 50점을 기준으로 위/아래 영역을 나눠 그리는 방식([index.html:779-780](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/index.html#L779-L780))이나 CNN이 붙이는 날짜가 "지금"을 뜻하는 게 아니라는 점([index.html:703-704](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/index.html#L703-L704)) 같은, 헷갈릴 수 있는 부분에 주석이 달려 있어서 좋았습니다.

다만 하나 걸리는 게 있었는데, [scripts/today_signal.py:3](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/scripts/today_signal.py#L3)에 "매매 규칙(CLAUDE.md 기준)"이라고 써있는데 저장소 안에 CLAUDE.md 파일이 실제로는 없더라고요. 아마 로컬에만 있는 파일이거나 실수로 안 올라간 것 같은데, 리뷰어 입장에서는 그 근거를 확인할 수가 없었습니다. 사소하지만 짚어드리고 싶었습니다.

**[ ] 3. 에러가 난 부분을 디버깅하여 "문제를 해결한 기록"을 남겼나요? 또는 "새로운 시도 및 추가 실험"을 해봤나요?**

커밋 히스토리를 보다가 [b79e357](https://github.com/hera93939393-ctrl/fg-dashboard/commit/b79e357) 커밋이 눈에 들어왔습니다. GitHub 자체 스케줄 트리거가 활동이 적은 저장소에서는 몇 시간씩 늦게 돈다는 걸 발견하고, `repository_dispatch`를 추가해서 외부 크론으로 대신 트리거하게 바꾼 내용이었는데, 이런 식으로 문제를 발견하고 원인을 찾아서 고친 과정이 커밋 메시지에 남아있는 게 좋았습니다.

근데 정작 이 프로젝트에서 가장 실험적인 부분이라고 할 수 있는, 가격 데이터만으로 F&G 지수를 근사하는 회귀식([scripts/price_proxy.py:16-32](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/scripts/price_proxy.py#L16-L32))은 결과값(가중치, 상관계수 0.77)만 코드에 박혀있고, 그 값을 어떻게 뽑아냈는지 보여주는 회귀분석 코드나 노트북은 저장소에 없었습니다. 다른 지표 조합이나 기간을 시도해봤는지도 확인할 방법이 없더라고요. 이 부분에 대한 시도 기록이 남아있었으면 이 항목도 충족될 수 있었을 것 같습니다.

**[ ] 4. 회고를 잘 작성했나요?**

README나 커밋 메시지, 코드 어디에서도 배운 점이나 아쉬운 점, 느낀 점 같은 회고에 해당하는 내용은 찾지 못했습니다. 실제 지수와 계산값을 비교하는 차트([index.html:499-510](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/index.html#L499-L510))가 이미 있어서, 근사 방식이 실제값과 얼마나 차이가 나는지 스스로도 확인하고 계셨을 것 같은데, 그 결과를 보고 어떤 생각이 들었는지 글로 남겨두지 않은 게 아쉬웠습니다. 왜 이 5개 지표를 골랐는지, 근사 방식의 한계는 뭐라고 생각하는지, 다음에 개선하고 싶은 부분은 뭔지 정도만 README에 짧게라도 추가하면 충분히 채워질 것 같습니다.

**[x] 5. 코드가 간결하고 효율적인가요?**

파이썬 코드는 함수 하나하나가 하는 일이 명확하게 나뉘어 있고(`fetch_price_history`, `fetch_live_quote`, `compute_price_based_fg` 등), 타입 힌트도 꾸준히 붙어 있어서 읽기 편했습니다. `fetch_real_data`, `price_fetcher`, `price_proxy` 모듈을 `update_live_score.py`와 `today_signal.py`에서 그대로 가져다 쓰는 걸 보면([scripts/update_live_score.py:13-15](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/scripts/update_live_score.py#L13-L15)) 중복 없이 잘 모듈화하셨다는 생각이 들었습니다. PEP8 관련해서도 줄 길이나 네이밍(snake_case), import 정리까지 크게 벗어나는 부분은 없었습니다.

한 가지 아쉬웠던 건 JS 쪽인데, `renderChart`([index.html:749](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/index.html#L749))와 `renderCompareChart`([index.html:938](https://github.com/hera93939393-ctrl/fg-dashboard/blob/main/index.html#L938))가 그리드라인 그리는 부분이나 크로스헤어/툴팁 로직이 거의 똑같이 복붙되어 있더라고요. 공통 함수로 한번 빼내시면 코드가 훨씬 짧아질 것 같습니다.

# 참고 링크 및 코드 개선

```
- 커밋 b79e357: GitHub Actions 스케줄이 지연되는 문제를 repository_dispatch로 해결한 기록.
  3번 항목에서 "문제 해결 기록"의 좋은 예시로 참고하시면 좋을 것 같습니다.

- 제안 1: price_proxy.py의 WEIGHTS, INTERCEPT 값을 뽑아낸 회귀분석 코드(스크립트나 노트북)를 같이 커밋해두면
  좋겠습니다. 지금은 결과만 남아있어서 나중에 다시 검증하거나 재현하기 어려운 상태입니다.

- 제안 2: index.html에서 renderChart()와 renderCompareChart()의 중복 로직을 공통 함수로 묶어보시면
  코드가 더 간결해질 것 같습니다.

- 제안 3: today_signal.py에서 언급하는 CLAUDE.md 파일이 저장소에 없어서 근거를 확인하지 못했습니다.
  파일을 같이 올리시거나, 주석에서 해당 언급을 빼주시면 좋겠습니다.
```

전체적으로 봤을 때 완성도, 설명, 코드 효율성 세 항목은 충분히 충족했다고 생각합니다. 다만 실험 재현성 부분과 회고 부분은 조금만 더 채워주시면 훨씬 완성도 높은 프로젝트가 될 것 같습니다. 고생하셨습니다!
