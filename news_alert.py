"""
세이브티커 관심 뉴스 알림

  확장 프로그램이 C:\\_c\\saveticker\\data 에 쓰는 날짜별 CSV 를 지켜보다가,
  새 뉴스가 들어오면 LLM(ollama, 안 되면 claude CLI)이 interests.md 와 과거 👍/👎 반응을 읽고
  0~10점으로 판별한다. 기준 점수 이상이면 윈도우 토스트로 알린다.

  토스트의 [👍 관심] [👎 별로] 버튼은 http://127.0.0.1:18765 로 반응을 기록하고,
  기록은 다음 판별의 예시로 들어간다. 같은 주소에서 최근 판별 목록도 볼 수 있다.

실행:
  python news_alert.py            # 감시 시작
  python news_alert.py --test 15  # 최근 15건만 판별해 점수를 출력 (알림 없음)
  python news_alert.py --say "이란 휴전안 거부"   # 음성 알림 시험

필요:
  pip install requests winotify edge-tts pywin32
  claude CLI 로그인 (터미널에서 claude 실행 후 /login 한 번)
  news_alert_config.json 의 backend: "auto" 는 ollama 가 켜져 있으면 먼저 쓰고,
  꺼져 있거나 오류·엉뚱한 답이면 claude 로 넘긴다
"""
import argparse
import csv
import difflib
import hashlib
import html
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
CONFIG = BASE / "news_alert_config.json"
INTERESTS = BASE / "interests.md"
JUDGED = BASE / "news_judged.jsonl"      # 판별 기록 (재시작해도 다시 묻지 않게)
FEEDBACK = BASE / "news_feedback.jsonl"  # 👍/👎 기록
MOVES = BASE / "news_moves.jsonl"        # 뉴스 뒤 종목 시세 움직임
SUGGEST = BASE / "interests_suggest.json"   # 관심사 고침 제안 (마지막 것)

KST = timezone(timedelta(hours=9))

DEFAULTS = {
    "backend": "auto",             # "auto" (ollama 먼저, 안 되면 claude), "claude", "ollama"
    "claude_model": "sonnet",
    "ollama_url": "http://localhost:11434/api/generate",
    "model": "qwen3.8:27b",        # rsi_vision 이 이미 올려 둔 모델을 같이 쓴다
    "keep_alive": -1,
    "timeout_sec": 180,
    "ollama_timeout_sec": 90,      # auto 에서 ollama 를 이만큼 기다려 보고 안 되면 claude 로
    "threshold": 7,                # 이 점수 이상이면 알린다
    "max_age_min": 60,             # 이보다 오래된 뉴스는 알리지 않는다 (판별은 한다)
    "catchup_hours": 12,           # 절전·재시작으로 밀린 뉴스는 이만큼까지 거슬러 판별해 목록에만 올린다
    "batch": 10,                   # 한 번에 묻는 뉴스 수
    "poll_sec": 10,
    "max_wait_sec": 90,            # 뉴스를 모아서 한 번에 묻는다. batch 가 차거나 가장 오래 기다린 뉴스가 이만큼 되면 묻는다
    "port": 18765,
    "examples": 15,                # 프롬프트에 넣을 👍, 👎 각각의 최대 개수
    "dup_ratio": 0.6,              # 최근 알린 제목과 이만큼 비슷하면 알리지 않는다
    "hide_max_score": 3,           # 판별 목록에서 이 점수 이하는 기본으로 숨긴다 (👍·🔔10 준 것은 보인다)
    "tts": True,                   # 알림을 말로도 읽는다: 말머리 소리 → 제목을 줄인 말 ("이란 휴전안 거부")
    "tts_voice": "ko-KR-SunHiNeural",   # Edge 읽어주기 음성. 안 되면 윈도우 기본 음성(SAPI)
    "tts_rate": "+0%",
    "tts_chime": r"C:\Windows\Media\Windows Notify Messaging.wav",   # RSI 알림(Speech On)과 다른 소리
    "tts_quiet": "",               # 말하지 않을 시간대, 예: "23-07". 비우면 늘 말한다 (토스트는 그대로)
    "wake_gap_min": 10,            # 감시 주기가 이만큼 끊겼으면 PC 가 잠들었다 깬 것으로 보고, 밀린 판별이 끝나면 요약을 알린다
    "summary_max": 5,              # 요약에서 읽어 줄 뉴스 수
    "moves": True,                 # 기준 점수 이상 뉴스의 종목 시세가 5분·30분 뒤 얼마나 움직였는지 적는다 (yfinance, 공개 시세)
    "suggest_days": 7,             # 관심사 고침 제안을 이 날짜마다 한 번 만든다. 0 이면 버튼으로만
    "suggest_backend": "claude",   # 관심사 제안을 누구에게 묻나. "claude" / "auto" (ollama 먼저) / "ollama"
}

PROMPT = """너는 한 개인 투자자의 뉴스 비서다.
아래 [관심사]와 [과거 반응]을 보고, [새 뉴스] 각각이 이 사람에게 지금 알려줄 가치가 얼마나 되는지 0~10점으로 매겨라.

점수 기준:
- 9~10: 보유·관찰 종목이나 시장 전체를 당장 움직일 만한 소식
- 7~8: 관심 분야와 직접 관련 있고 알면 도움이 되는 소식
- 4~6: 간접적으로만 관련
- 0~3: 관련 없음, 이미 나온 내용의 반복, 사소한 소식
[과거 반응]에서 👍 받은 뉴스와 비슷하면 점수를 올리고, 👎 받은 뉴스와 비슷하면 내려라.
[과거 반응]의 🔔 는 "이런 뉴스는 반드시 알려라", 🔕 는 "이런 뉴스는 절대 알리지 마라"는 강한 표시다.
🔔 와 같은 종류의 뉴스는 9~10점, 🔕 와 같은 종류는 0~1점을 줘라. 이것이 👍/👎 와 관심사보다 우선한다.

[관심사]
{interests}

[과거 반응]
{examples}

같은 사건 묶기:
- 뉴스마다 그 뉴스가 다루는 사건의 이름(topic)을 10자 안팎 한국어로 붙여라. 예: "미중 정상회담", "H&M 3분기 실적", "미 5년물 국채 입찰".
- 이름은 "누가 무엇을" 이 드러나게 짓는다. 나라·인물 이름만으로 짓지 마라. 예: "이란" (X), "트럼프 이란 제안 거부" (O).
- 한 사건에서 나온 여러 발언, 후속 보도([2보] 등), 다른 매체의 같은 보도는 모두 같은 이름을 쓴다.
- [최근 사건]에 같은 사건이 있으면 그 이름을 글자 그대로 다시 써라. 이름 뒤에 그 사건의 기사 제목을 붙여 두었다.
- 같은 사건이란 그 기사 제목과 같은 일을 다루는 것이다. 같은 나라·인물이 나와도 다른 일이면 새 이름을 지어라.
  예: 최근 사건이 "이란 항공편 금지 — 이란 항공사 운항 금지 …" 일 때, "트럼프, 이란의 제안 거부" 는 다른 일이다.
- 이름만 쓰고, 이름 뒤의 " — 기사 제목" 은 topic 에 넣지 마라.

[최근 사건] (이름 — 그 사건의 최근 기사 제목)
{topics}

[새 뉴스]
{news}

JSON 만 출력하라. 다른 말은 쓰지 마라.
{{"results": [{{"i": 번호, "score": 0~10 정수, "reason": "왜 관심 있을지 15자 이내 한국어", "topic": "사건 이름", "say": "제목을 소리내 읽기 좋게 12자 안팎으로 줄인 말. 예: 이란 휴전안 거부"}}]}}
"""


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG.exists():
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    else:
        CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg


LOG = BASE / "news_alert.log"


def log(msg: str):
    line = f"{datetime.now():%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


_lock = threading.Lock()


def append_jsonl(path: Path, rec: dict):
    with _lock, path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────
# 뉴스 읽기
# ─────────────────────────────────────────────────────────────

def parse_ts(s: str):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def read_news(days: int = 2) -> list:
    """최근 며칠치 CSV 의 행. 확장이 파일을 덮어쓰는 중이면 그 파일은 다음 차례에 읽는다."""
    rows = []
    for d in range(days):
        day = (datetime.now(KST) - timedelta(days=d)).strftime("%Y-%m-%d")
        path = DATA / f"saveticker_news_{day}.csv"
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8-sig", newline="") as f:
                rows.extend(csv.DictReader(f))
        except (OSError, csv.Error, UnicodeDecodeError):
            continue
    for r in rows:
        r["ts"] = parse_ts(r.get("created_at", ""))
    return [r for r in rows if r.get("id") and r["ts"]]


# ─────────────────────────────────────────────────────────────
# 판별
# ─────────────────────────────────────────────────────────────

def news_line(r: dict) -> str:
    t = r["title"]
    if r.get("title_en") and r["title_en"] != t:
        t += f" / {r['title_en']}"
    extra = " ".join(x for x in (r.get("tickers"), r.get("labels")) if x)
    return f"{t}" + (f" ({extra})" if extra else "")


# 반응 버튼: v 값 → (like, strong). 10점·0점은 👍/👎 보다 강한 반응이다.
FB_VALUES = {"10": (True, True), "1": (True, False), "0": (False, False), "00": (False, True)}


def fb_key(rec) -> str:
    """반응 기록 → "10" / "1" / "0" / "00", 반응이 없거나 취소했으면 None."""
    if not rec or rec.get("like") is None:
        return None
    return {(True, True): "10", (True, False): "1", (False, False): "0", (False, True): "00"}[
        (rec["like"], bool(rec.get("strong")))]


def latest_feedback() -> dict:
    fb = {}
    for rec in read_jsonl(FEEDBACK):   # 같은 뉴스에 여러 번 누르면 마지막 것
        fb[rec["id"]] = rec
    return fb


def examples_text(n: int) -> str:
    recs = sorted(latest_feedback().values(), key=lambda x: x.get("at", ""), reverse=True)
    groups = {k: [r["title"] for r in recs if fb_key(r) == k] for k in FB_VALUES}
    # 10점·0점은 드물고 중요하니 더 많이 남긴다
    lines = ([f"🔔 {t}" for t in groups["10"][:n * 2]] + [f"👍 {t}" for t in groups["1"][:n]]
             + [f"👎 {t}" for t in groups["0"][:n]] + [f"🔕 {t}" for t in groups["00"][:n * 2]])
    return "\n".join(lines) or "(아직 없음)"


def ask_claude(cfg: dict, prompt: str) -> str:
    # 프롬프트는 stdin 으로 넘긴다. 뉴스 제목이 많으면 명령줄 길이 제한에 걸린다.
    # 도구·MCP·설정·메모리를 모두 빼고 시스템 프롬프트를 한 줄로 바꾼다.
    # 그냥 부르면 Claude Code 전체가 딸려 와서 입력이 10배 넘게 는다 (10건에 4만 → 3천 토큰).
    p = subprocess.run(
        ["claude", "-p", "--model", cfg["claude_model"], "--output-format", "json",
         "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
         "--setting-sources", "", "--no-session-persistence",
         "--system-prompt", "너는 뉴스 판별기다. 요청한 JSON 만 출력한다."],
        input=prompt, capture_output=True, text=True, encoding="utf-8",
        timeout=cfg["timeout_sec"], cwd=str(DATA), shell=(sys.platform == "win32"),
    )
    try:
        out = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError(f"claude 응답을 읽지 못함: {(p.stdout or p.stderr)[:200]}")
    if out.get("is_error"):
        raise RuntimeError(f"claude: {out.get('result', '')[:200]}")
    return out.get("result", "")


def ask_ollama(cfg: dict, prompt: str, timeout: float) -> str:
    r = requests.post(
        cfg["ollama_url"],
        json={
            "model": cfg["model"],
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": "json",
            "keep_alive": cfg["keep_alive"],
            "options": {"temperature": 0.0},
        },
        timeout=timeout,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    return r.json()["response"]


def parse_results(text: str, batch: list) -> dict:
    """{id: (score, reason, topic, say)}. 모델이 빠뜨린 뉴스는 결과에 없다."""
    try:
        items = json.loads(text).get("results", [])
    except (ValueError, AttributeError):
        m = re.search(r"\{.*\}", text, re.S)
        try:
            items = json.loads(m.group(0)).get("results", []) if m else []
        except (ValueError, AttributeError):
            items = []
    out = {}
    for it in items if isinstance(items, list) else []:
        try:
            i, score = int(it["i"]), int(round(float(it["score"])))
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= i <= len(batch):
            out[batch[i - 1]["id"]] = (max(0, min(10, score)), str(it.get("reason", "")).strip(),
                                       str(it.get("topic", "")).split(" — ")[0].strip(), str(it.get("say", "")).strip())
    return out


def judge(cfg: dict, batch: list, topics: list = ()) -> tuple:
    """({id: (score, reason, topic, say)}, 판별한 쪽 이름). topics 는 최근에 붙인 사건 이름."""
    prompt = PROMPT.format(
        interests=INTERESTS.read_text(encoding="utf-8") if INTERESTS.exists() else "(없음)",
        examples=examples_text(cfg["examples"]),
        topics="\n".join(topics) or "(없음)",
        news="\n".join(f"{i}. {news_line(r)}" for i, r in enumerate(batch, 1)),
    )
    def check(text):
        out = parse_results(text, batch)
        # 절반도 못 매겼으면 형식을 어긴 답으로 보고 claude 에게 다시 묻는다
        if len(out) * 2 < len(batch):
            raise RuntimeError(f"결과 {len(out)}/{len(batch)}건만 읽힘")
        return out
    return ask_llm(cfg, prompt, check)


def ask_llm(cfg: dict, prompt: str, check=lambda text: text) -> tuple:
    """(check(답), 답한 쪽 이름). backend 가 auto 면 ollama 에 먼저 묻고, 안 되거나 check 가
    거절하면 claude 에게 묻는다. 둘 다 JSON 으로 답하게 부른다."""
    backend = cfg["backend"]
    if backend in ("auto", "ollama"):
        timeout = cfg["ollama_timeout_sec"] if backend == "auto" else cfg["timeout_sec"]
        try:
            return check(ask_ollama(cfg, prompt, timeout)), "ollama"
        except Exception as e:
            if backend == "ollama":
                raise
            log(f"ollama 실패 → claude: {str(e)[:120]}")
    return check(ask_claude(cfg, prompt)), "claude"


def parse_json(text: str) -> dict:
    """LLM 답에서 JSON 객체를 꺼낸다. 앞뒤에 딴말이 붙어 있어도 읽는다."""
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


# ─────────────────────────────────────────────────────────────
# 알림
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# 음성
# ─────────────────────────────────────────────────────────────

def _mci(cmd: str):
    import ctypes
    err = ctypes.windll.winmm.mciSendStringW(cmd, None, 0, None)
    if err:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.winmm.mciGetErrorStringW(err, buf, 256)
        raise OSError(f"MCI {err}: {buf.value}")


def play_file(path: str):
    """소리 파일을 끝까지 틀고 돌아온다."""
    kind = "waveaudio" if path.lower().endswith(".wav") else "mpegvideo"
    _mci(f'open "{path}" type {kind} alias newsalert')
    try:
        _mci("play newsalert wait")
    finally:
        _mci("close newsalert")


def _speak_edge(cfg: dict, text: str):
    import asyncio
    import edge_tts
    fd, tmp = tempfile.mkstemp(prefix="news_tts_", suffix=".mp3")
    os.close(fd)
    try:
        asyncio.run(asyncio.wait_for(
            edge_tts.Communicate(text, cfg["tts_voice"], rate=cfg["tts_rate"]).save(tmp), 15))
        play_file(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _speak_sapi(text: str):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        win32com.client.Dispatch("SAPI.SpVoice").Speak(text)
    finally:
        pythoncom.CoUninitialize()


def speak(cfg: dict, text: str) -> str:
    """말머리 소리를 내고 text 를 읽는다. 실제로 읽은 길('edge'·'sapi'·'')을 돌려준다."""
    chime = cfg.get("tts_chime")
    if chime and os.path.exists(chime):
        try:
            play_file(chime)
        except OSError:
            pass
    try:
        _speak_edge(cfg, text)
        return "edge"
    except Exception as e:
        log(f"edge 음성 실패 → SAPI: {type(e).__name__}: {str(e)[:100]}")
    try:
        _speak_sapi(text)
        return "sapi"
    except Exception as e:
        log(f"SAPI 도 실패: {type(e).__name__}: {e}")
        return ""


def quiet_now(cfg: dict) -> bool:
    """tts_quiet("23-07") 시간대 안인가."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", cfg.get("tts_quiet") or "")
    if not m:
        return False
    a, b, h = int(m[1]), int(m[2]), datetime.now().hour
    return a <= h < b if a <= b else h >= a or h < b


_speech = queue.Queue()


def _speech_worker(cfg: dict):
    # 한 판별 묶음에서 알림이 여럿 나와도 겹치지 않게 차례로 읽는다. 판별은 기다리지 않는다.
    while True:
        text = _speech.get()
        try:
            speak(cfg, text)
        except Exception as e:
            log(f"음성 오류: {type(e).__name__}: {e}")


def say_alert(cfg: dict, text: str):
    if not cfg["tts"] or quiet_now(cfg) or not text:
        return
    _speech.put(text)


def toast(cfg: dict, r: dict, score: int, reason: str):
    try:
        from winotify import Notification, audio
    except ImportError:
        log("winotify 가 없어 토스트를 띄우지 못했다. pip install winotify")
        return
    fb = f"http://127.0.0.1:{cfg['port']}/fb?id={r['id']}"
    n = Notification(app_id="SaveTicker 뉴스", title=f"[{score}점] {reason}",
                     msg=r["title"][:200], launch=r["url"])
    # 말로 읽을 때는 토스트 소리를 끈다. 말머리 소리와 겹치면 뉴스 알림인지 헷갈린다
    speaking = cfg["tts"] and not quiet_now(cfg)
    n.set_audio(audio.Silent if speaking else audio.Default, loop=False)
    n.add_actions(label="👍 관심", launch=fb + "&v=1")
    n.add_actions(label="👎 별로", launch=fb + "&v=0")
    n.show()


# ─────────────────────────────────────────────────────────────
# 뉴스 뒤 시세 움직임 (공개 시세만. 계좌는 보지 않는다)
# ─────────────────────────────────────────────────────────────

def price_moves(symbol: str, t0: datetime) -> dict:
    """t0 직전 값에서 5분·30분 뒤 몇 % 움직였나. 장이 닫혀 있었으면 빈 dict.
    프리·애프터 장도 본다. 1분봉은 최근 7일만 받을 수 있다."""
    import yfinance as yf
    h = yf.Ticker(symbol.replace(".", "-")).history(
        start=t0 - timedelta(hours=1), end=t0 + timedelta(minutes=40), interval="1m", prepost=True)
    if h.empty:
        return {}
    closes = h["Close"]

    def at(t):
        s = closes[closes.index <= t]
        return (s.index[-1], float(s.iloc[-1])) if len(s) else (None, None)

    i0, p0 = at(t0)
    if i0 is None or t0 - i0 > timedelta(minutes=10):   # 뉴스 때 거래가 없었다 = 장이 닫혀 있었다
        return {}
    out = {"p0": round(p0, 4)}
    for k, m in (("m5", 5), ("m30", 30)):
        _, p = at(t0 + timedelta(minutes=m))
        out[k] = round((p / p0 - 1) * 100, 2) if p else None
    return out


def moves_worker(watcher: "Watcher"):
    """기준 점수 이상이거나 👍 받은 뉴스 가운데 종목이 붙은 것을, 나온 지 35분 뒤 시세를 받아 적는다."""
    cfg = watcher.cfg
    while True:
        time.sleep(60)
        try:
            fb = {k: fb_key(v) for k, v in latest_feedback().items()}
            now = datetime.now(timezone.utc)
            # 종목은 CSV 에서 읽는다. 판별 기록에 종목을 적기 전에 판별한 뉴스도 있다
            tickers = {n["id"]: n.get("tickers", "") for n in read_news(days=6)}
            for r in list(watcher.judged.values()):
                t0 = parse_ts(r.get("created_at", ""))
                syms = (r.get("tickers") or tickers.get(r["id"], "")).split()
                if (r["id"] in watcher.moves or not syms or not t0
                        or not (r["score"] >= cfg["threshold"] or fb.get(r["id"]) in ("1", "10"))
                        or not timedelta(minutes=35) < now - t0 < timedelta(days=6)):
                    continue
                got = {}
                for sym in syms[:4]:
                    try:
                        m = price_moves(sym, t0)
                    except Exception as e:
                        log(f"시세 실패 {sym}: {type(e).__name__}: {str(e)[:80]}")
                        continue
                    if m:
                        got[sym] = m
                append_jsonl(MOVES, {"id": r["id"], "moves": got,
                                     "at": datetime.now(KST).isoformat(timespec="seconds")})
                watcher.moves[r["id"]] = got
                shown = " ".join(f"{s} {move_text(m)}" for s, m in got.items())
                if shown:
                    log(f"📈 {shown}  {r['title'][:50]}")
        except Exception as e:
            log(f"시세 기록 오류: {type(e).__name__}: {e}")


def move_text(m: dict) -> str:
    """"+0.4% → +1.2%" (5분 → 30분)"""
    f = lambda v: "?" if v is None else f"{v:+.1f}%"
    return f"{f(m.get('m5'))} → {f(m.get('m30'))}"


# ─────────────────────────────────────────────────────────────
# 관심사 고침 제안 · 사건 흐름 요약
# ─────────────────────────────────────────────────────────────

SUGGEST_PROMPT = """너는 한 개인 투자자의 뉴스 비서다.
[관심사]는 뉴스에 0~10점을 매길 때 기준으로 쓰는 문서다. {threshold}점 이상이면 알림을 보낸다.
최근 {days}일 동안 이 사람이 뉴스에 보인 반응을 아래 세 묶음으로 나눠 두었다.
이것을 보고 [관심사]에 더하면 좋을 줄과, 좁히거나 고치면 좋을 줄을 제안하라.

규칙:
- [놓친 뉴스]는 이 사람이 좋아했는데 점수가 낮았던 것이다. 여기서 되풀이되는 주제가 관심사에 빠져 있으면 "add" 에 넣어라.
- [헛알림]은 이 사람이 싫어했는데 점수가 높아 알림이 간 것이다. 여기서 되풀이되는 주제를 좁히는 고침을 "remove" 에 넣어라.
- [잘 맞은 뉴스]는 이 사람이 좋아했고 점수도 높았던 것이다. 이 주제들은 지금 관심사가 잘 잡고 있다. 절대 빼거나 좁히지 마라.
- 한 주제가 [헛알림]과 [잘 맞은 뉴스]에 모두 있으면, 주제 전체를 빼지 말고 싫어한 쪽만 가려내는 조건을 제안하라.
- 같은 주제가 세 건 이상 되풀이될 때만 제안하라. 근거가 약하면 빈 목록으로 둬라.
- 계좌·보유 수량 같은 것은 묻지도 넣지도 마라.

[관심사]
{interests}

[놓친 뉴스] 좋아함 · 점수 {threshold}점 미만 · {n_missed}건 (점수 제목)
{missed}

[헛알림] 싫어함 · 점수 {threshold}점 이상 · {n_false}건 (점수 제목)
{false}

[잘 맞은 뉴스] 좋아함 · 점수 {threshold}점 이상 · {n_hit}건 (점수 제목)
{hit}

JSON 만 출력하라.
{{"add": ["관심사에 더할 줄", ...], "remove": ["관심사 원문 그대로 → 어떻게 좁히거나 고칠지", ...], "why": "근거가 된 반응을 들어 한두 문장"}}
"""

TOPIC_PROMPT = """아래는 "{topic}" 사건에 관한 뉴스 제목을 오래된 것부터 늘어놓은 것이다.
사건이 어떻게 흘러왔는지 한국어 한두 문장(100자 안팎)으로 요약하라. 제목에 없는 내용은 지어내지 마라.

{rows}

JSON 만 출력하라. {{"summary": "요약"}}
"""


def make_suggestion(watcher: "Watcher") -> dict:
    """최근 반응으로 관심사 고침 제안을 만들어 SUGGEST 에 적는다. 반응이 적으면 만들지 않는다.

    반응을 한 줄로 섞어 주면 👎 가 훨씬 많아 모델이 좋아한 주제까지 빼라고 한다 (09-26, 이란 뉴스
    👍12·👎6 인데 "이란 정세를 빼라"). 그래서 고칠 근거가 되는 두 묶음(놓친 뉴스·헛알림)과
    건드리지 말아야 할 묶음(잘 맞은 뉴스)으로 나눠 준다. 좋아했고 점수도 낮은 뉴스는 그대로 두면 된다.
    """
    cfg = watcher.cfg
    days, th = cfg["suggest_days"] or 7, cfg["threshold"]
    cutoff = (datetime.now(KST) - timedelta(days=days)).isoformat(timespec="seconds")
    missed, false, hit = [], [], []
    for rec in sorted(latest_feedback().values(), key=lambda x: x.get("at", ""), reverse=True):
        k, j = fb_key(rec), watcher.judged.get(rec["id"])
        if not k or not j or rec.get("at", "") < cutoff:
            continue
        line = f"{j['score']:>2} {j['title']}"
        liked = k in ("1", "10")
        if liked and j["score"] < th:
            missed.append(line)
        elif liked:
            hit.append(line)
        elif j["score"] >= th:
            false.append(line)
    if len(missed) + len(false) < 3:
        raise RuntimeError(f"최근 {days}일 놓친 뉴스 {len(missed)}건·헛알림 {len(false)}건뿐이라 제안하지 않는다")
    prompt = SUGGEST_PROMPT.format(
        days=days, threshold=th,
        interests=INTERESTS.read_text(encoding="utf-8") if INTERESTS.exists() else "(없음)",
        n_missed=len(missed), missed="\n".join(missed[:40]) or "(없음)",
        n_false=len(false), false="\n".join(false[:40]) or "(없음)",
        n_hit=len(hit), hit="\n".join(hit[:40]) or "(없음)")

    def check(text):
        d = parse_json(text)
        if not isinstance(d.get("add"), list) or not isinstance(d.get("remove"), list):
            raise RuntimeError("add/remove 가 없다")
        return d
    # 한 주에 한 번이고 판단이 까다로워 Claude 에게 먼저 묻는다 (suggest_backend)
    d, by = ask_llm({**cfg, "backend": cfg["suggest_backend"]}, prompt, check)
    out = {"at": datetime.now(KST).isoformat(timespec="seconds"), "days": days, "by": by,
           "n": len(missed) + len(false) + len(hit), "missed": len(missed), "false": len(false), "hit": len(hit),
           "add": [str(x) for x in d["add"]], "remove": [str(x) for x in d["remove"]],
           "why": str(d.get("why", ""))}
    SUGGEST.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"💡 관심사 고침 제안: 더할 것 {len(out['add'])} · 고칠 것 {len(out['remove'])} ({by})")
    return out


def read_suggestion() -> dict:
    try:
        return json.loads(SUGGEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def suggest_worker(watcher: "Watcher"):
    """suggest_days 마다 한 번 제안을 만들고 토스트로 알린다."""
    days = watcher.cfg["suggest_days"]
    if not days:
        return
    while True:
        last = read_suggestion().get("at", "")
        if last < (datetime.now(KST) - timedelta(days=days)).isoformat(timespec="seconds"):
            try:
                s = make_suggestion(watcher)
                if s["add"] or s["remove"]:
                    plain_toast(watcher.cfg, "관심사 고침 제안이 있습니다",
                                f"더할 것 {len(s['add'])} · 고칠 것 {len(s['remove'])}", "/stats")
            except Exception as e:
                log(f"관심사 제안 건너뜀: {e}")
                # 반응이 모자라면 하루 뒤에 다시 본다
                time.sleep(86400)
                continue
        time.sleep(3600)


def topic_summary(watcher: "Watcher", topic: str) -> str:
    recs = topic_records(watcher, topic)
    if len(recs) < 2:
        return "뉴스가 한 건뿐이라 요약할 흐름이 없습니다."
    key = (topic, len(recs))
    if key not in watcher.summaries:
        rows = "\n".join(f"{parse_ts(r['created_at']).astimezone(KST):%m-%d %H:%M} {r['title']}"
                         for r in recs[-40:])

        def check(text):
            s = str(parse_json(text).get("summary", "")).strip()
            if not s:
                raise RuntimeError("summary 가 비었다")
            return s
        watcher.summaries[key], _ = ask_llm(watcher.cfg, TOPIC_PROMPT.format(topic=topic, rows=rows), check)
    return watcher.summaries[key]


def topic_records(watcher: "Watcher", topic: str) -> list:
    """이 사건 이름을 단 뉴스, 오래된 것부터 (최근 3일)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    recs = [r for r in watcher.judged.values()
            if r.get("topic") == topic and (parse_ts(r.get("created_at", "")) or cutoff) >= cutoff]
    return sorted(recs, key=lambda r: r.get("created_at", ""))


def plain_toast(cfg: dict, title: str, msg: str, path: str = "/"):
    try:
        from winotify import Notification
    except ImportError:
        return
    Notification(app_id="SaveTicker 뉴스", title=title, msg=msg,
                 launch=f"http://127.0.0.1:{cfg['port']}{path}").show()


# ─────────────────────────────────────────────────────────────
# 수집이 멈췄는지 살피기
# ─────────────────────────────────────────────────────────────

def collect_problem(watcher: "Watcher") -> str:
    """확장이 보내는 소식으로 수집에 탈이 있는지 본다. 없으면 빈 문자열."""
    now = time.time()
    # 켠 직후나 PC 가 깬 직후는 확장이 아직 소식을 못 보냈을 수 있다
    if now - max(watcher.started, watcher.last_wake) < 300:
        return watcher.problem
    e = watcher.ext
    if not e or now - e["at"] > 300:
        return "Edge 확장에서 5분 넘게 소식이 없습니다 (Edge 가 꺼졌거나 확장이 멈췄거나 옛 버전)"
    if not e["tabs"]:
        return "Edge 에 saveticker 뉴스 탭이 열려 있지 않습니다"
    if not e["watch"]:
        return "확장의 실시간 감시가 꺼져 있습니다"
    if now - e["tick"] > 600:
        # 감시견이 3분마다 탭을 새로고침해 보는데도 10분째 못 받았다 (로그아웃·차단 따위)
        return f"실시간 감시가 {(now - e['tick']) / 60:.0f}분째 뉴스를 받지 못했습니다"
    return ""


def health_worker(watcher: "Watcher"):
    """1분마다 수집 상태를 보고, 탈이 생기거나 풀리면 한 번씩 알린다."""
    while True:
        time.sleep(60)
        try:
            now = collect_problem(watcher)
            if now == watcher.problem:
                continue
            if now and not watcher.problem:
                log(f"⚠ 뉴스 수집이 멈췄다: {now}")
                plain_toast(watcher.cfg, "뉴스 수집이 멈췄습니다", now)
            elif now:
                log(f"⚠ 수집 탈이 바뀌었다: {now}")
            else:
                log("✅ 뉴스 수집이 다시 된다")
                plain_toast(watcher.cfg, "뉴스 수집이 다시 됩니다", "새 뉴스가 다시 들어옵니다")
            watcher.problem = now
        except Exception as e:
            log(f"수집 상태 확인 오류: {type(e).__name__}: {e}")


def summary_toast(cfg: dict, n: int, top: list):
    try:
        from winotify import Notification, audio
    except ImportError:
        return
    lines = "\n".join(f"{r['score']}  {r.get('say') or r['title'][:30]}" for r in top)
    note = Notification(app_id="SaveTicker 뉴스", title=f"잠든 사이 중요 뉴스 {n}건",
                        msg=lines, launch=f"http://127.0.0.1:{cfg['port']}/")
    speaking = cfg["tts"] and not quiet_now(cfg)
    note.set_audio(audio.Silent if speaking else audio.Default, loop=False)
    note.show()


class Watcher:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.judged = {rec["id"]: rec for rec in read_jsonl(JUDGED)}
        self.recent_alerts = []   # (시각, 제목) — 비슷한 후속 보도를 거르려고
        self.first_seen = {}      # id → 처음 본 시각
        self.wake_at = None       # PC 가 잠들었다 깬 시각. 밀린 판별이 끝나면 요약을 알리고 비운다
        self.moves = {m["id"]: m["moves"] for m in read_jsonl(MOVES)}   # id → {종목: {p0, m5, m30}}
        self.summaries = {}       # (사건 이름, 건수) → 흐름 요약. 뉴스가 늘면 다시 만든다
        self.started = self.last_wake = time.time()
        self.ext = None           # 확장이 1분마다 보내는 소식: {at, watch, tick, tabs}
        self.problem = ""         # 지금 수집에 무슨 탈이 있나 (없으면 빈 문자열)

    def is_dup(self, title: str) -> bool:
        cutoff = time.time() - 3600
        self.recent_alerts = [(t, s) for t, s in self.recent_alerts if t > cutoff]
        return any(difflib.SequenceMatcher(None, title, s).ratio() >= self.cfg["dup_ratio"]
                   for _, s in self.recent_alerts)

    def recent(self, hours: float) -> list:
        """최근 hours 시간 안에 판별한 기록, 새것부터."""
        cutoff = (datetime.now(KST) - timedelta(hours=hours)).isoformat(timespec="seconds")
        recs = [r for r in self.judged.values() if r.get("at", "") >= cutoff]
        return sorted(recs, key=lambda r: r.get("at", ""), reverse=True)

    def recent_topics(self) -> list:
        """프롬프트에 넣을 최근 사건. 같은 사건에 같은 이름을 다시 쓰게 한다.
        이름만 주면 나라 이름만 겹쳐도 옛 이름을 가져다 붙인다 (09-26 "트럼프 이란 제안 거부" 가
        "이란 항공편 금지" 로 묶임). 그래서 그 사건의 최근 기사 제목을 함께 준다."""
        seen, out = set(), []
        for r in self.recent(3):
            t = r.get("topic")
            if t and t not in seen:
                seen.add(t)
                out.append(f"{t} — {r['title'][:60]}")
        return out[:40]

    def topic_alerted(self, topic: str) -> bool:
        """한 시간 안에 이 사건으로 알림을 보냈는가."""
        return bool(topic) and any(r.get("alerted") and r.get("topic") == topic for r in self.recent(1))

    def pending(self) -> list:
        """아직 판별하지 않은 뉴스. 알릴 만큼 새것을 먼저, 밀린 것은 그 뒤에."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.cfg["catchup_hours"])
        seen, out = set(), []
        for r in read_news():
            done = self.judged.get(r["id"])
            if done:   # 목록 표시용으로만 최신 값을 반영한다
                done["title"] = r["title"]   # 원문 제목이 나중에 한글로 바뀐 경우
                done.setdefault("source", r.get("source", ""))
            if done or r["id"] in seen or r["ts"] < cutoff:
                continue
            seen.add(r["id"])
            out.append(r)
        return sorted(out, key=lambda r: (self.is_late(r), r["ts"]))

    def is_late(self, r: dict) -> bool:
        """알리기엔 늦은 뉴스인가. PC 가 잠든 사이 나온 뉴스를 깨어나서 한꺼번에 울리지 않게."""
        return r["ts"] < datetime.now(timezone.utc) - timedelta(minutes=self.cfg["max_age_min"])

    def step(self):
        todo = self.pending()
        if not todo:
            return
        # 한 건씩 바로 물으면 호출마다 관심사·예시를 다시 보내야 한다. 조금 모았다가 묻는다.
        waited = time.time() - self.first_seen.setdefault(todo[0]["id"], time.time())
        if len(todo) < self.cfg["batch"] and waited < self.cfg["max_wait_sec"]:
            return
        for k in range(0, len(todo), self.cfg["batch"]):
            batch = todo[k:k + self.cfg["batch"]]
            # 밀린 뉴스는 한 차례에 한 묶음만. 그사이 새로 들어온 뉴스가 뒤로 밀리지 않게.
            if k and self.is_late(batch[0]):
                return
            t0 = time.time()
            try:
                result, by = judge(self.cfg, batch, self.recent_topics())
            except Exception as e:   # 모델이 바쁘거나 꺼져 있으면 다음 차례에 다시
                log(f"판별 실패: {e}")
                return
            log(f"{len(batch)}건 판별 {time.time() - t0:.1f}초 ({by})")
            for r in batch:
                if r["id"] not in result:
                    continue
                score, reason, topic, say = result[r["id"]]
                # 같은 사건(시진핑 발언 문장마다 뜨는 속보 등)은 한 시간에 한 번만 알린다
                late = self.is_late(r)
                alert = (score >= self.cfg["threshold"] and not late and not self.topic_alerted(topic)
                         and not self.is_dup(r["title"]))
                rec = {"id": r["id"], "title": r["title"], "url": r["url"], "source": r.get("source", ""),
                       "created_at": r["created_at"], "score": score, "reason": reason, "topic": topic,
                       "say": say, "tickers": r.get("tickers", ""), "alerted": alert, "late": late, "by": by,
                       "at": datetime.now(KST).isoformat(timespec="seconds")}
                self.judged[r["id"]] = rec
                append_jsonl(JUDGED, rec)
                mark = "🔔" if alert else "⏰" if late and score >= self.cfg["threshold"] else "  "
                log(f"{mark} {score:>2} [{topic}] {r['title'][:70]}  — {reason}")
                if alert:
                    self.recent_alerts.append((time.time(), r["title"]))
                    toast(self.cfg, r, score, reason)
                    say_alert(self.cfg, say or topic or reason)

    def woke(self) -> None:
        """PC 가 잠들었다 깼다. 밀린 뉴스를 다 판별하면 요약을 알린다."""
        self.wake_at = self.last_wake = time.time()

    def maybe_summarize(self):
        """깬 뒤 밀린 판별이 끝났으면 잠든 사이 중요 뉴스를 한 번에 알린다.
        확장이 빈 시간을 거슬러 받아올 틈을 3분 주고, 30분이 넘으면 끝나지 않았어도 알린다."""
        if not self.wake_at:
            return
        since = time.time() - self.wake_at
        if since < 180:
            return
        if since < 1800 and any(self.is_late(r) for r in self.pending()):
            return
        woke = datetime.fromtimestamp(self.wake_at, KST).isoformat(timespec="seconds")
        self.wake_at = None
        # 잠들기 전에 이미 알린 사건은 뺀다
        told = {r.get("topic") for r in self.recent(self.cfg["catchup_hours"])
                if r.get("alerted") and r.get("topic")}
        picks, topics = [], set()
        for r in sorted(self.judged.values(), key=lambda r: (-r["score"], r.get("created_at", ""))):
            tp = r.get("topic")
            if (not r.get("late") or r.get("at", "") < woke or r["score"] < self.cfg["threshold"]
                    or (tp and (tp in told or tp in topics))):
                continue
            picks.append(r)
            if tp:
                topics.add(tp)
        if not picks:
            log("잠든 사이 중요 뉴스 없음")
            return
        n, top = len(picks), picks[:self.cfg["summary_max"]]
        says = [r.get("say") or r.get("topic") or r["title"][:20] for r in top]
        text = f"잠든 사이 중요 뉴스 {n}건. " + ", ".join(says) + (f", 외 {n - len(top)}건" if n > len(top) else "")
        log(f"🌙 {text}")
        summary_toast(self.cfg, n, top)
        say_alert(self.cfg, text)

    def run(self):
        log(f"감시 시작: {DATA}  (모델 {self.cfg['model']}, 기준 {self.cfg['threshold']}점)")
        # 켜자마자 밀린 뉴스가 있으면(밤새 꺼져 있다가 부팅) 깬 것과 같이 본다
        if any(self.is_late(r) for r in self.pending()):
            self.woke()
        while True:
            try:
                self.step()
                self.maybe_summarize()
            except Exception as e:   # 한 번의 오류로 감시가 멈추지 않게
                log(f"오류: {type(e).__name__}: {e}")
            # 잠깐 쉬는 사이 벽시계가 크게 건너뛰었으면 PC 가 잠들었다 깬 것이다
            t = time.time()
            time.sleep(self.cfg["poll_sec"])
            if time.time() - t > self.cfg["wake_gap_min"] * 60:
                log(f"감시가 {(time.time() - t) / 60:.0f}분 끊겼다 (PC 절전으로 봄). 밀린 뉴스를 판별하고 요약한다")
                self.woke()


# ─────────────────────────────────────────────────────────────
# 반응 기록용 로컬 페이지
# ─────────────────────────────────────────────────────────────

def make_handler(watcher: Watcher):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send_page(self, body: str, code: int = 200):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/fb" and q.get("id") in watcher.judged:
                rec = watcher.judged[q["id"]]
                # v=10 10점, v=1 👍, v=0 👎, v=00 0점, v=x 누른 것을 다시 눌러 취소
                like, strong = FB_VALUES.get(q.get("v"), (None, False))
                append_jsonl(FEEDBACK, {"id": rec["id"], "title": rec["title"], "like": like,
                                        "strong": strong,
                                        "at": datetime.now(KST).isoformat(timespec="seconds")})
                log(f"{FB_LABELS.get(q.get('v'), '취소')} {rec['title'][:70]}")
                if q.get("ajax"):     # 페이지 스크립트가 부른 것: 이동 없이 기록만
                    self.send_response(204)
                    self.end_headers()
                    return
                self.send_response(303)
                self.send_header("Location", f"/?done={rec['id']}" + ("&all=1" if q.get("all") else ""))
                self.end_headers()
            elif u.path == "/ping":
                # 확장의 감시견이 1분마다 보낸다. 판별기는 이것이 끊기면 수집이 멈춘 줄 안다
                try:
                    watcher.ext = {"at": time.time(), "watch": q.get("watch") == "1",
                                   "tick": int(q.get("tick") or 0) / 1000, "tabs": int(q.get("tabs") or 0)}
                except ValueError:
                    pass
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
            elif u.path == "/judged.json":
                # 확장 팝업이 판별한 뉴스를 흐리게 표시할 때 쓴다: {id: 점수}
                data = json.dumps({k: v["score"] for k, v in watcher.judged.items()}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/":
                try:
                    n = max(PAGE_LINES, min(2000, int(q.get("n", PAGE_LINES))))
                except ValueError:
                    n = PAGE_LINES
                self.send_page(page(watcher, q.get("done"), bool(q.get("all")), n))
            elif u.path == "/stats":
                self.send_page(stats_page(watcher))
            elif u.path == "/topic" and q.get("name"):
                self.send_page(topic_page(watcher, q["name"]))
            elif u.path == "/topic_summary" and q.get("name"):
                # LLM 을 부르니 사용자 정의 헤더가 있을 때만 (다른 사이트가 몰래 부르지 못하게)
                if self.headers.get("X-Page") != "yes":
                    return self.send_page("bad request", 400)
                try:
                    self.send_json({"summary": topic_summary(watcher, q["name"])})
                except Exception as e:
                    self.send_json({"error": f"{type(e).__name__}: {str(e)[:150]}"})
            else:
                self.send_page("not found", 404)

        def send_json(self, obj):
            data = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            # 처음부터 다시·관심사 제안: 페이지의 버튼으로만 온다.
            # 다른 사이트가 몰래 보내지 못하게 사용자 정의 헤더를 요구한다 (브라우저가 막는다).
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/suggest" and self.headers.get("X-Page") == "yes":
                try:
                    self.send_json(make_suggestion(watcher))
                except Exception as e:
                    self.send_json({"error": str(e)[:200]})
                return
            if u.path != "/reset" or self.headers.get("X-Reset") != "yes" or q.get("what") not in ("feedback", "all"):
                self.send_page("bad request", 400)
                return
            self.send_json({"moved": reset_records(watcher, q["what"])})
    return H


def reset_records(watcher: Watcher, what: str) -> list:
    """반응 기록(과 판별 기록)을 지운다. 실제로는 이름을 바꿔 백업으로 남긴다."""
    stamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    files = [FEEDBACK] + ([JUDGED] if what == "all" else [])
    moved = []
    with _lock:
        for path in files:
            if path.exists():
                backup = path.with_name(f"{path.stem}.{stamp}.bak{path.suffix}")
                path.rename(backup)
                moved.append(backup.name)
        if what == "all":
            watcher.judged.clear()
            watcher.first_seen.clear()
    log(f"처음부터 다시 ({what}): {', '.join(moved) or '지울 기록 없음'}")
    return moved


SOURCE_NAMES = {"reuters": "Reuters", "로이터": "Reuters", "financial-juice": "FinancialJuice"}


FB_LABELS = {"10": "🔔10점", "1": "👍", "0": "👎", "00": "🔕0점"}


PAGE_LINES = 50   # 판별 목록에 한 번에 싣는 뉴스 수 (묶음 안의 뉴스도 센다). "더 보기" 로 이만큼씩 늘린다


def page(watcher: Watcher, done: str = None, show_all: bool = False, n: int = PAGE_LINES) -> str:
    fb = {k: fb_key(v) for k, v in latest_feedback().items()}
    recs = sorted(watcher.judged.values(), key=lambda r: r.get("created_at", ""), reverse=True)
    # 👎·0점 준 뉴스와 점수가 낮은 뉴스는 기본으로 숨긴다.
    # 방금 누른 것은 기록됐다는 표시를 위해, 👍·10점 준 것은 점수와 상관없이 남긴다.
    low = watcher.cfg["hide_max_score"]

    def hide(r):
        if r["id"] == done or fb.get(r["id"]) in ("1", "10"):
            return False
        return fb.get(r["id"]) in ("0", "00") or r["score"] <= low

    hidden = 0 if show_all else sum(1 for r in recs if hide(r))
    if not show_all:
        recs = [r for r in recs if not hide(r)]
    # 뉴스가 쌓이면 화면이 끝없이 길어진다. 최근 n 건만 그리고 맨 아래 "더 보기" 를 둔다.
    left = len(recs) - n
    recs = recs[:n]
    qs = "&all=1" if show_all else ""
    # 같은 사건(topic)은 가장 최근 뉴스 한 줄로 접는다. 6시간 넘게 떨어지면 다른 묶음으로 본다.
    heads, members, order = {}, {}, []
    for r in recs:
        tp, t = r.get("topic"), parse_ts(r.get("created_at", ""))
        h = heads.get(tp) if tp else None
        if h and t and (parse_ts(h["created_at"]) - t) <= timedelta(hours=6):
            members[h["id"]].append(r)
        else:
            if tp:
                heads[tp] = r
            members[r["id"]] = []
            order.append(r)
    rows = []
    for head in order:
        kids = members[head["id"]]
        # 묶음 id: 사건 이름만 쓰면 6시간 넘게 떨어져 나뉜 같은 이름의 묶음이 함께 펼쳐진다.
        # 가장 오래된 뉴스를 섞는다. 새 뉴스는 위에 붙으니 자동 갱신 뒤에도 id 가 그대로다.
        gid = (hashlib.md5(f"{head.get('topic', '')}|{kids[-1]['id']}".encode()).hexdigest()[:10]
               if kids else "")
        rows.append(row_html(head, fb, done, qs, gid=gid, kids=kids, moves=watcher.moves))
        rows.extend(row_html(k, fb, done, qs, child_of=gid, moves=watcher.moves) for k in kids)
    if left > 0:
        rows.append(f"<tr><td colspan=4 class=more><a class=more href='/?n={n + PAGE_LINES}{qs}'>"
                    f"더 보기 (뉴스 {min(left, PAGE_LINES)}개 더 · 남은 {left}개)</a></td></tr>")
    note = "<p class=ok>반응을 기록했사옵니다. 다음 판별부터 반영됩니다.</p>" if done else ""
    return page_html(watcher, rows, note, show_all, low, hidden, sum(1 for v in fb.values() if v),
                     recent_alerts_html(watcher))


def recent_alerts_html(watcher: Watcher) -> str:
    """맨 위 "최근 알림" 줄. 목록은 기사 시각 순이라 늦게 들어온 알림이 아래에 묻힌다. 알린 시각 순으로 보인다.
    수집이 멈췄으면 그 경고를 맨 앞에 붙인다."""
    warn = f"<div class=stall>⚠ 뉴스 수집이 멈췄습니다: {html.escape(watcher.problem)}</div>" if watcher.problem else ""
    return warn + _recent_alerts(watcher)


def _recent_alerts(watcher: Watcher) -> str:
    cutoff = (datetime.now(KST) - timedelta(hours=12)).isoformat(timespec="seconds")
    recs = sorted((r for r in watcher.judged.values() if r.get("alerted") and r.get("at", "") >= cutoff),
                  key=lambda r: r["at"], reverse=True)[:6]
    if not recs:
        return "<span class=why>최근 12시간 알림 없음</span>"
    items = [f"<a href='{html.escape(r['url'])}' target=_blank title='{html.escape(r['title'])}'>"
             f"<span class=why>{r['at'][11:16]}</span> <b>{r['score']}</b> "
             f"{html.escape(r.get('say') or r['title'][:30])}</a>" for r in recs]
    return "<span class=why>최근 알림</span> " + " <span class=why>·</span> ".join(items)


def moves_html(moves: dict) -> str:
    """종목별 5분 → 30분 움직임 칩. 30분 뒤가 ±1% 넘으면 색을 입힌다."""
    out = []
    for sym, m in moves.items():
        v = m.get("m30")
        cls = "mv up" if v is not None and v >= 1 else "mv dn" if v is not None and v <= -1 else "mv"
        out.append(f"<span class='{cls}' title='뉴스 시각 {m.get('p0')} 에서 5분 뒤 → 30분 뒤'>"
                   f"{html.escape(sym)} {move_text(m)}</span>")
    return "".join(out)


def row_html(r: dict, fb: dict, done: str, qs: str, gid: str = "", kids=(), child_of: str = "",
             moves: dict = None) -> str:
    t = parse_ts(r.get("created_at", ""))
    when = t.astimezone(KST).strftime("%m-%d %H:%M") if t else ""
    state = fb.get(r["id"])   # "10" / "1" / "0" / "00" / None
    classes = ["hit"] if r.get("alerted") else []
    if r["id"] == done:
        classes = ["done"]
    if child_of:
        classes += ["child", f"g-{child_of}"]
    cls = f' class="{" ".join(classes)}"' if classes else ""
    group = ""
    if kids:
        top = max(k["score"] for k in kids)
        group = (f" <a class=grp data-g='{gid}'>같은 사건 +{len(kids)}건 (최고 {top}점) ▾</a>")
    # 누가 판별했는지: 🦙 Ollama, ✴ Claude
    by = {"ollama": "<div class=by title='Ollama 가 판별'>🦙</div>",
          "claude": "<div class='by cl' title='Claude 가 판별'>✴</div>"}.get(r.get("by"), "")
    # 사건 이름을 누르면 그 사건의 타임라인
    topic = (f"<a class=tp href='/topic?name={quote(r['topic'])}' target=_blank title='사건 타임라인'>"
             f"{html.escape(r['topic'])}</a>" if r.get("topic") else "")
    mv = moves_html((moves or {}).get(r["id"]) or {})
    source = SOURCE_NAMES.get(r.get("source", ""), r.get("source", ""))
    src = f"<span class=src>{html.escape(source)}</span>" if source else ""
    # 누른 버튼은 불이 켜지고, 다시 누르면 취소된다.
    btns = "".join(
        f"<a class='fb{' num' if v in ('10', '00') else ''}{' on' if state == v else ''}' title='{tip}' "
        f"href='/fb?id={r['id']}&v={'x' if state == v else v}{qs}'>{label}</a>"
        for v, label, tip in (("10", "🔔10", "반드시 알려라 (10점)"), ("1", "👍", "관심"),
                              ("0", "👎", "별로"), ("00", "🔕0", "절대 알리지 마라 (0점)")))
    return (
        f"<tr{cls}><td class=b>{btns}</td>"
        f"<td class=t>{when}</td><td class=s>{r['score']}{by}</td>"
        f"<td><a{' class=rated' if state else ''} href='{html.escape(r['url'])}' target=_blank>{html.escape(r['title'])}</a>"
        f"<div class=why>{src}{topic}{html.escape(r.get('reason', ''))}{mv}{group}</div></td></tr>")


def page_html(watcher: Watcher, rows: list, note: str, show_all: bool, low: int, hidden: int, n_fb: int,
              recent: str = "") -> str:
    note += "<p class=why>🔔10 👍 👎 🔕0 가운데 누른 것에 불이 켜집니다. 🔔10 은 '반드시 알려라', 🔕0 은 '절대 알리지 마라'로 👍/👎 보다 강하게 반영됩니다. 같은 버튼을 다시 누르면 취소됩니다. "
    note += ("<a href='/' style='text-decoration:underline'>숨기기</a></p>" if show_all else
             f"👎·🔕0 준 뉴스와 {low}점 이하 뉴스 {hidden}건은 숨겼습니다. <a href='/?all=1' style='text-decoration:underline'>모두 보기</a></p>")
    return f"""<!doctype html><meta charset=utf-8><title>saveticker 필터링</title>
<style>
body{{font:14px system-ui,sans-serif;background:#16181c;color:#e6e6e6;margin:16px}}
table{{border-collapse:collapse;width:100%}} td{{padding:6px 8px;border-bottom:1px solid #2a2d33;vertical-align:top}}
a{{color:#e6e6e6;text-decoration:none}} .s{{text-align:right;font-weight:600}} .why{{color:#8a9099;font-size:12px}}
.b,.t,.s{{width:1%;white-space:nowrap}} a.fb{{display:inline-block;margin-right:4px;padding:2px 5px;border-radius:6px;font-size:16px;opacity:.3;filter:grayscale(1)}} a.fb:hover{{opacity:.8}} a.fb.num{{font-weight:700;font-size:13px;white-space:nowrap;text-align:center;color:#fff;background:#2a2d33}} a.fb.on{{opacity:1;filter:none;background:#3a4a6b;outline:1px solid #6d8fd6}} tr.hit{{background:#1d2a45}} tr.done{{background:#2a3d23}} a.rated{{color:#8a9099}} a[href^='https://saveticker.com/news/']:not(.rated):visited{{color:#b4b9c0}} .ok{{color:#8fd18f}} .warn{{color:#e0a44a;font-size:13px}} .warn a{{color:#e0a44a;text-decoration:underline}} .src{{display:inline-block;margin-right:6px;padding:0 5px;border-radius:4px;background:#2a2d33;color:#b8bec6;font-size:11px}} .tp{{display:inline-block;margin-right:6px;padding:0 5px;border-radius:4px;background:#2d2640;color:#c9b8ef;font-size:11px}} .by{{font-size:12px;font-weight:400;opacity:.75;margin-top:2px}} .by.cl{{color:#d97757}} .reset{{margin-top:24px}} .reset a{{color:#e0a44a;text-decoration:underline;cursor:pointer}} a.grp{{margin-left:8px;color:#8ab4f8;cursor:pointer;text-decoration:underline}} tr.child{{display:none}} tr.child.show{{display:table-row}} tr.child td{{background:#1b1e23}} tr.child td:nth-child(4){{padding-left:56px}}
.stall{{margin:-2px 0 6px;padding:6px 10px;border-radius:6px;background:#4a1f1f;color:#ffb4a8;font-weight:600}} td.more{{text-align:center;padding:14px}} a.more{{color:#8ab4f8;text-decoration:underline;cursor:pointer}} a.tp{{color:#c9b8ef}} a.tp:hover{{text-decoration:underline}} .mv{{display:inline-block;margin-left:8px;padding:0 5px;border-radius:4px;background:#23262c;color:#b8bec6;font-size:11px}} .mv.up{{background:#1f3a26;color:#8fd18f}} .mv.dn{{background:#3d2323;color:#f08c8c}}
#recent{{margin:8px 0 12px;padding:8px 10px;border-radius:8px;background:#1d2a45;line-height:1.8}} #recent a{{margin-right:2px}} #recent a:hover{{text-decoration:underline}} .nav a{{color:#8ab4f8;text-decoration:underline;margin-left:10px;font-size:13px}}
</style>
<h2>saveticker 필터링 <small style="color:#8a9099">기준 {watcher.cfg['threshold']}점 · 파란 줄은 알림을 보낸 뉴스 · 점수 밑 🦙 Ollama / <span style="color:#d97757">✴</span> Claude 가 판별</small><span class=nav><a href='/stats' target=_blank>점수 성적표 · 관심사 제안</a></span></h2>
<p class=warn>※ 이 PC 의 Edge 에 <a href="https://saveticker.com/news" target=_blank>saveticker.com/news</a> 탭이 떠 있고 확장의 실시간 감시가 켜져 있어야 새 뉴스가 들어옵니다.</p>
<div id=recent>{recent}</div>
{note}<p class=why id=upd></p><table id=list>{''.join(rows)}</table>
<p class="why reset">처음부터 다시 ·
  <a id=reset-feedback data-n="{n_fb}">반응 기록 지우기 ({n_fb}건)</a> ·
  <a id=reset-all data-n="{n_fb}" data-j="{len(watcher.judged)}">반응과 판별 기록 모두 지우기 ({n_fb}건 · {len(watcher.judged)}건)</a>
  — 지운 기록은 같은 폴더에 .bak 파일로 남는다</p>
<script>
// 처음부터 다시: 지우기 전에 반드시 한 번 더 묻는다
async function resetRecords(what, msg) {{
  if (!confirm(msg + "\\n\\n정말 지우시겠습니까? (기록은 .bak 파일로 옮겨져 되살릴 수 있습니다)")) return;
  const r = await fetch("/reset?what=" + what, {{method: "POST", headers: {{"X-Reset": "yes"}}}});
  const d = r.ok ? await r.json() : null;
  alert(d ? "지웠습니다. 백업: " + (d.moved.join(", ") || "(지울 기록 없음)") : "지우지 못했습니다 (" + r.status + ")");
  location.href = "/";
}}
document.getElementById("reset-feedback").onclick = (e) => resetRecords("feedback",
  "🔔10·👍·👎·🔕0 반응 기록 " + e.target.dataset.n + "건을 지웁니다.\\n판별기는 관심사(interests.md)만 보고 처음부터 다시 배웁니다.");
document.getElementById("reset-all").onclick = (e) => resetRecords("all",
  "반응 기록 " + e.target.dataset.n + "건과 판별 기록 " + e.target.dataset.j + "건을 모두 지웁니다.\\n목록이 비고, 최근 12시간 안의 뉴스는 다시 판별합니다 (알림은 60분 안의 것만).");

// 15초마다 목록만 바꿔 끼운다. 스크롤 위치는 그대로 남는다.
// 방금 누른 뉴스는 10초 동안 목록에 남긴다 (👎 해도 바로 사라지지 않게, 잘못 누르면 되돌릴 수 있게)
let keep = null, keepAt = 0;
async function refresh() {{
  if (keep && Date.now() - keepAt > 10000) keep = null;
  const params = new URLSearchParams({{{"all: 1" if show_all else ""}}});
  if (keep) params.set("done", keep);
  const n = new URLSearchParams(location.search).get("n");   // "더 보기" 로 늘린 줄 수는 갱신 뒤에도 그대로
  if (n) params.set("n", n);
  try {{
    const r = await fetch("/?" + params, {{cache: "no-store"}});
    const doc = new DOMParser().parseFromString(await r.text(), "text/html");
    document.getElementById("list").innerHTML = doc.getElementById("list").innerHTML;
    document.getElementById("recent").innerHTML = doc.getElementById("recent").innerHTML;
    applyOpen();
    document.getElementById("upd").textContent = "자동 갱신 " + new Date().toLocaleTimeString("ko-KR", {{hour12: false}});
  }} catch (e) {{
    document.getElementById("upd").textContent = "판별기에 연결할 수 없습니다 (" + new Date().toLocaleTimeString("ko-KR", {{hour12: false}}) + ")";
  }}
}}
setInterval(refresh, 15000);

// 같은 사건 묶음: 펼친 것은 자동 갱신 뒤에도 펼친 채로 둔다
const opened = new Set();
function applyOpen() {{
  document.querySelectorAll("tr.child").forEach((tr) => {{
    const g = [...tr.classList].find((c) => c.startsWith("g-"));
    tr.classList.toggle("show", opened.has(g.slice(2)));
  }});
  document.querySelectorAll("a.grp").forEach((a) => {{
    a.textContent = a.textContent.replace(/[▾▴]$/, opened.has(a.dataset.g) ? "▴" : "▾");
  }});
}}

// 👍/👎 는 페이지를 옮기지 않고 기록한다. 그래서 스크롤 위치가 그대로 남는다.
document.getElementById("list").addEventListener("click", async (e) => {{
  const g = e.target.closest("a.grp");
  if (g) {{
    opened.has(g.dataset.g) ? opened.delete(g.dataset.g) : opened.add(g.dataset.g);
    applyOpen();
    return;
  }}
  const m = e.target.closest("a.more");
  if (m) {{
    // 페이지를 옮기면 맨 위로 튄다. 주소만 바꾸고 목록만 다시 받는다
    e.preventDefault();
    history.replaceState(null, "", m.href);
    await refresh();
    return;
  }}
  const a = e.target.closest("a.fb");
  if (!a) return;
  e.preventDefault();
  const url = new URL(a.href);
  try {{
    const r = await fetch(url.pathname + url.search + "&ajax=1", {{cache: "no-store"}});
    if (!r.ok) throw new Error(r.status);
    keep = url.searchParams.get("id");
    keepAt = Date.now();
    await refresh();
  }} catch (err) {{
    location.href = a.href;   // 스크립트로 안 되면 예전처럼 페이지 이동
  }}
}});
</script>"""


SUB_CSS = """<style>
body{font:14px system-ui,sans-serif;background:#16181c;color:#e6e6e6;margin:16px;max-width:1100px}
table{border-collapse:collapse;margin:8px 0 20px} td,th{padding:5px 10px;border-bottom:1px solid #2a2d33;text-align:left;vertical-align:top}
th{color:#8a9099;font-weight:500} td.n{text-align:right} tr.cur{background:#1d2a45}
a{color:#e6e6e6;text-decoration:none} a:hover{text-decoration:underline} .why{color:#8a9099;font-size:12px}
h3{margin:24px 0 4px} .box{padding:10px 12px;border-radius:8px;background:#1d2127;line-height:1.7}
button{background:#2a3d5c;color:#e6e6e6;border:1px solid #6d8fd6;border-radius:6px;padding:4px 12px;cursor:pointer}
button:disabled{opacity:.5;cursor:wait} .add{color:#8fd18f} .rm{color:#f0a36c}
.mv{display:inline-block;margin-left:8px;padding:0 5px;border-radius:4px;background:#23262c;color:#b8bec6;font-size:11px}
.mv.up{background:#1f3a26;color:#8fd18f} .mv.dn{background:#3d2323;color:#f08c8c}
</style>"""


def _pct(a: int, b: int) -> str:
    return f"{a * 100 // b}%" if b else "-"


def stats_page(watcher: Watcher) -> str:
    """점수 성적표: 점수와 반응(👍👎)·시세 움직임을 맞대어 기준 점수가 맞는지 본다."""
    th = watcher.cfg["threshold"]
    fb = {k: fb_key(v) for k, v in latest_feedback().items()}
    recs = list(watcher.judged.values())
    good = lambda r: fb.get(r["id"]) in ("1", "10")
    bad = lambda r: fb.get(r["id"]) in ("0", "00")

    def big(r):   # 30분 뒤 가장 크게 움직인 종목의 |%|
        ms = [abs(m["m30"]) for m in (watcher.moves.get(r["id"]) or {}).values() if m.get("m30") is not None]
        return max(ms) if ms else None

    ats = sorted(r.get("at", "") for r in recs if r.get("at"))
    span = 1.0
    if len(ats) > 1:
        span = max(1.0, (datetime.fromisoformat(ats[-1]) - datetime.fromisoformat(ats[0])).total_seconds() / 86400)

    t1 = []
    for name, lo, hi in (("0~3", 0, 3), ("4~6", 4, 6), ("7~8", 7, 8), ("9~10", 9, 10)):
        rs = [r for r in recs if lo <= r["score"] <= hi]
        rated = [r for r in rs if fb.get(r["id"])]
        g = sum(1 for r in rated if good(r))
        mv = [x for x in map(big, rs) if x is not None]
        t1.append(f"<tr><td>{name}점</td><td class=n>{len(rs)}</td><td class=n>{sum(1 for r in rs if r.get('alerted'))}</td>"
                  f"<td class=n>{len(rated)}</td><td class=n>{g}</td><td class=n>{len(rated) - g}</td>"
                  f"<td class=n>{_pct(g, len(rated))}</td>"
                  f"<td class=n>{f'{sum(mv) / len(mv):.1f}% ({len(mv)}건)' if mv else '-'}</td></tr>")

    t2 = []
    for t in range(5, 10):
        would = [r for r in recs if r["score"] >= t and not r.get("late")]
        missed = sum(1 for r in recs if good(r) and r["score"] < t)
        t2.append(f"<tr{' class=cur' if t == th else ''}><td>{t}점{' (지금)' if t == th else ''}</td>"
                  f"<td class=n>{len(would) / span:.0f}</td><td class=n>{sum(1 for r in would if bad(r))}</td>"
                  f"<td class=n>{missed}</td></tr>")

    def items(rs):
        rs = sorted(rs, key=lambda r: r.get("created_at", ""), reverse=True)[:12]
        return "".join(f"<tr><td class=n>{r['score']}</td><td><a href='{html.escape(r['url'])}' target=_blank>"
                       f"{html.escape(r['title'])}</a> <span class=why>{html.escape(r.get('reason', ''))}</span></td></tr>"
                       for r in rs) or "<tr><td class=why>없음</td></tr>"

    missed = items(r for r in recs if good(r) and r["score"] < th)
    false = items(r for r in recs if r.get("alerted") and bad(r))

    s = read_suggestion()
    if s:
        counts = (f"놓친 뉴스 {s['missed']} · 헛알림 {s['false']} · 잘 맞은 뉴스 {s['hit']}" if "missed" in s
                  else f"반응 {s['n']}건")
        sug = (f"<p class=why>{s['at'][:16].replace('T', ' ')} · 최근 {s['days']}일 {counts} · {s['by']}</p>"
               + "".join(f"<div class=add>+ {html.escape(x)}</div>" for x in s["add"])
               + "".join(f"<div class=rm>− {html.escape(x)}</div>" for x in s["remove"])
               + (f"<p>{html.escape(s['why'])}</p>" if s.get("why") else "")
               + ("" if s["add"] or s["remove"] else "<p>고칠 것 없음</p>"))
    else:
        sug = "<p class=why>아직 만든 제안이 없습니다.</p>"
    every = watcher.cfg["suggest_days"]
    return f"""<!doctype html><meta charset=utf-8><title>점수 성적표</title>{SUB_CSS}
<h2>점수 성적표 <small class=why>판별 {len(recs)}건 · 반응 {sum(1 for r in recs if fb.get(r['id']))}건 · 약 {span:.1f}일치 · 기준 {th}점</small></h2>
<p class=why>👍·🔔10 은 "좋음", 👎·🔕0 은 "싫음"으로 셉니다. 시세는 종목이 붙은 뉴스의 30분 뒤 움직임(가장 크게 움직인 종목, 절댓값) 평균입니다.</p>
<h3>점수대별</h3>
<table><tr><th>점수</th><th>판별</th><th>알림</th><th>반응</th><th>좋음</th><th>싫음</th><th>좋음 비율</th><th>30분 뒤 움직임</th></tr>{''.join(t1)}</table>
<h3>기준 점수를 바꾸면</h3>
<p class=why>하루 알림 수는 늦게 잡힌 뉴스를 빼고, 같은 사건 거르기 전의 수라 실제보다 많습니다.</p>
<table><tr><th>기준</th><th>하루 알림</th><th>그중 싫음</th><th>놓치는 좋음</th></tr>{''.join(t2)}</table>
<h3>놓친 뉴스 <small class=why>좋음인데 {th}점 미만</small></h3><table>{missed}</table>
<h3>헛알림 <small class=why>알렸는데 싫음</small></h3><table>{false}</table>
<h3>관심사 고침 제안 <small class=why>{f'{every}일마다 자동' if every else '버튼으로만'} · interests.md 는 직접 고치셔야 합니다</small></h3>
<div class=box id=sug>{sug}</div><p><button id=go>지금 제안 받기</button> <span class=why id=st></span></p>
<script>
document.getElementById("go").onclick = async (e) => {{
  e.target.disabled = true;
  document.getElementById("st").textContent = "LLM 에게 묻는 중… (10초~1분)";
  try {{
    const d = await (await fetch("/suggest", {{method: "POST", headers: {{"X-Page": "yes"}}}})).json();
    if (d.error) document.getElementById("st").textContent = d.error;
    else location.reload();
  }} catch (err) {{
    document.getElementById("st").textContent = "실패: " + err;
  }}
  e.target.disabled = false;
}};
</script>"""


def topic_page(watcher: Watcher, name: str) -> str:
    """한 사건의 뉴스를 시간순으로. 흐름 요약은 버튼을 눌러야 LLM 에게 묻는다."""
    recs = topic_records(watcher, name)
    rows = []
    for r in recs:
        t = parse_ts(r.get("created_at", ""))
        mark = "🔔 " if r.get("alerted") else ""
        rows.append(f"<tr><td class=why>{t.astimezone(KST):%m-%d %H:%M}</td><td class=n>{mark}{r['score']}</td>"
                    f"<td><a href='{html.escape(r['url'])}' target=_blank>{html.escape(r['title'])}</a>"
                    f"<div class=why>{html.escape(r.get('reason', ''))}"
                    f"{moves_html(watcher.moves.get(r['id']) or {})}</div></td></tr>")
    known = watcher.summaries.get((name, len(recs)), "")
    return f"""<!doctype html><meta charset=utf-8><title>{html.escape(name)}</title>{SUB_CSS}
<h2>{html.escape(name)} <small class=why>최근 3일 {len(recs)}건 · 오래된 것부터</small></h2>
<div class=box id=sum>{html.escape(known) or '<span class=why>흐름 요약은 아래 버튼을 누르면 만듭니다.</span>'}</div>
<p><button id=go data-name="{html.escape(name)}"{' hidden' if known or len(recs) < 2 else ''}>흐름 요약</button></p>
<table>{''.join(rows) or '<tr><td class=why>이 이름의 뉴스가 없습니다</td></tr>'}</table>
<script>
document.getElementById("go").onclick = async (e) => {{
  e.target.disabled = true;
  document.getElementById("sum").textContent = "LLM 에게 묻는 중…";
  const r = await fetch("/topic_summary?name=" + encodeURIComponent(e.target.dataset.name), {{headers: {{"X-Page": "yes"}}}});
  const d = await r.json();
  document.getElementById("sum").textContent = d.summary || d.error;
  e.target.hidden = !!d.summary;
  e.target.disabled = false;
}};
</script>"""


class Server(ThreadingHTTPServer):
    # HTTPServer 는 SO_REUSEADDR 를 켠다. 윈도우에서는 그러면 두 번째 실행도 같은 포트를 잡아
    # "이미 실행 중" 검사가 통하지 않고 알림이 두 번 온다 (시작프로그램 + 손으로 켠 것).
    allow_reuse_address = False


def main():
    ap = argparse.ArgumentParser(description="세이브티커 관심 뉴스 알림")
    ap.add_argument("--test", type=int, metavar="N", help="최근 N건만 판별해 출력하고 끝낸다")
    ap.add_argument("--before", metavar="TIME", help="--test 에서 이 한국 시각까지의 뉴스만 (예: '2026-09-24 23:50')")
    ap.add_argument("--say", metavar="TEXT", help="음성 알림을 한 번 내 보고 끝낸다")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()

    if args.say:
        t0 = time.time()
        by = speak(cfg, args.say)
        print(f"{by or '못 읽음'} · {time.time() - t0:.1f}초")
        return

    if args.test:
        rows = sorted(read_news(), key=lambda r: r["ts"])
        if args.before:   # 예: "2026-09-24 23:50" (한국 시각)
            until = datetime.fromisoformat(args.before).replace(tzinfo=KST)
            rows = [r for r in rows if r["ts"] <= until]
        rows = rows[-args.test:]
        if not rows:
            sys.exit(f"{DATA} 에 오늘·어제 CSV 가 없다.")
        topics = {}   # 사건 이름 → 최근 기사 제목 (감시 때와 같은 모양으로 넘긴다)
        for k in range(0, len(rows), cfg["batch"]):
            batch = rows[k:k + cfg["batch"]]
            t0 = time.time()
            res, by = judge(cfg, batch, [f"{t} — {title[:60]}" for t, title in reversed(topics.items())])
            log(f"{len(batch)}건 판별 {time.time() - t0:.1f}초 ({by})")
            for r in batch:
                score, reason, topic, say = res.get(r["id"], (None, "(응답 없음)", "", ""))
                mark = "🔔" if score is not None and score >= cfg["threshold"] else "  "
                print(f"{mark} {score if score is not None else '-':>2} [{topic}] {r['title'][:70]}  — {reason}  🗣 {say}")
                if topic:
                    topics.pop(topic, None)
                    topics[topic] = r["title"]
        return

    watcher = Watcher(cfg)
    try:
        server = Server(("127.0.0.1", cfg["port"]), make_handler(watcher))
    except OSError as e:
        # 이미 하나 떠 있는 경우가 대부분이다. 종료 코드 3 이면 news_alert.bat 이 다시 띄우지 않는다.
        log(f"포트 {cfg['port']} 를 쓸 수 없다 ({e}). 이미 실행 중이거나, {CONFIG.name} 의 port 를 바꿔라.")
        sys.exit(3)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=_speech_worker, args=(cfg,), daemon=True).start()
    if cfg["moves"]:
        threading.Thread(target=moves_worker, args=(watcher,), daemon=True).start()
    threading.Thread(target=suggest_worker, args=(watcher,), daemon=True).start()
    threading.Thread(target=health_worker, args=(watcher,), daemon=True).start()
    log(f"판별 목록: http://127.0.0.1:{cfg['port']}/")
    try:
        watcher.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
