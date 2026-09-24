# saveticker 필터링

[세이브티커](https://saveticker.com/news) 뉴스를 모아서, LLM 이 내 관심사에 맞는 것만 골라 윈도우 알림으로 알려준다.

## 왜 만들었나

오선님의 세이브티커에 요즘 뉴스가 많이 늘었다. 그러다보니 내가 관심 없는 뉴스도 너무 많이 올라와서,
적당히 걸러 주는 페이지가 필요했다. 관심 있는 뉴스만 알림으로 받고, 👍/👎 로 반응할수록
내 취향에 맞게 걸러지도록 만들었다.

## 주의 사항

1. **PC 의 Edge 에 https://saveticker.com/news 탭이 떠 있어야 한다.**
   뉴스는 이 탭 안에서 확장 프로그램이 모은다. 탭을 닫거나 Edge 를 끄면 새 뉴스가 들어오지 않고,
   판별과 알림도 멈춘다. 확장 팝업의 **실시간 감시** 도 켜 두어야 한다.

![구동 방식](docs/architecture.png)

```
Edge 확장 (extension/)          news_alert.py
  saveticker 뉴스 탭에서         data/*.csv 를 지켜보다가
  새 뉴스 수집 ──────────▶  날짜별 CSV  ──▶  LLM 판별 (ollama → 안 되면 claude CLI)
                              data/             7점 이상이면 윈도우 토스트
                                                http://127.0.0.1:18765  판별 목록 · 🔔10 👍 👎 🔕0 반응
```

## 화면

`http://127.0.0.1:18765` 의 판별 목록. 점수·이유·제공처가 보이고, 왼쪽 🔔10 · 👍 · 👎 · 🔕0 으로 반응한다.
파란 줄은 알림을 보낸 뉴스, 어두운 제목은 이미 반응한 뉴스.

![saveticker 필터링 화면](docs/screenshot.png)

## 구성

| 파일 | 역할 |
|---|---|
| `extension/` | Edge/Chrome 확장. 페이지가 받는 `/api/news/list` 응답을 기록하고, 실시간 감시로 1·2페이지를 주기적으로 확인한다. 날짜별 CSV 를 `다운로드\saveticker\` 에 저장한다 |
| `news_alert.py` | CSV 의 새 뉴스를 판별해 알림을 띄우고, 판별 목록 페이지를 연다 |
| `interests.md` | 판별 기준이 되는 관심사. 고치면 다음 판별부터 반영된다 |
| `news_alert_config.json` | 모델, 기준 점수, 포트 등 설정 |
| `news_alert_bg.vbs` / `news_alert_stop.bat` | 창 없이 백그라운드 실행 / 종료 |

## 설치

1. `edge://extensions` → 개발자 모드 → **압축 풀린 파일 로드** → `extension` 폴더.
2. `다운로드\saveticker` 를 `data` 폴더로 잇는다 (확장은 다운로드 폴더 안에만 쓸 수 있다):
   ```
   mklink /J "%USERPROFILE%\Downloads\saveticker" "C:\_c\saveticker\data"
   ```
3. `pip install requests winotify`, 그리고 터미널에서 `claude` 실행 후 `/login` 한 번.
   ollama 가 켜져 있으면 그쪽을 먼저 쓴다 (`news_alert_config.json` 의 `model`).
4. `news_alert_bg.vbs` 실행. 로그는 `news_alert.log`.
5. saveticker 뉴스 탭을 열고 확장 팝업에서 **실시간 감시** 를 켠다.

## 판별

- 새 뉴스를 최대 10건씩 모아(또는 90초 기다렸다가) 한 번에 묻는다.
- 프롬프트에는 `interests.md` 와 최근 반응(🔔10·👍·👎·🔕0)이 예시로 들어간다. 🔔10/🔕0 은 👍/👎 보다 우선한다.
- claude CLI 는 도구·MCP·설정을 모두 빼고 부른다 (10건에 입력 약 3천 토큰).
- `python news_alert.py --test 15` 로 최근 15건을 판별만 해 볼 수 있다.
