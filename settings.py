"""설정 창 (판별 목록 오른쪽 위 ⚙ 설정). stocknews_filter 의 설정 창을 옮겨 이쪽 설정에 맞췄다.

줄마다 이름·한 줄 설명·ⓘ(자세히)·오른쪽 스위치나 고르기 칸, 바꾸면 바로 적용된다 (저장 단추 없음).
값은 news_alert_config.json 에 쓰고, 돌고 있는 판별기에도 곧바로 반영한다.
"""
import html
import json
import re
from pathlib import Path

VOICES = [("ko-KR-InJoonNeural", "인준 (남)"), ("ko-KR-SunHiNeural", "선희 (여)"),
          ("ko-KR-HyunsuMultilingualNeural", "현수 (남, 다국어)")]
RATES = [("-30%", "느리게"), ("-15%", "조금 느리게"), ("+0%", "보통"), ("+15%", "조금 빠르게"), ("+30%", "빠르게")]
MEDIA = Path(r"C:\Windows\Media")
BACKENDS = [("auto", "Ollama 먼저, 안 되면 Claude"), ("ollama", "Ollama 만"), ("claude", "Claude 만")]


def chimes() -> list:
    files = sorted(MEDIA.glob("*.wav")) if MEDIA.exists() else []
    return [("", "소리 없음")] + [(str(p), p.stem) for p in files]


# 키 → (종류, 선택지). 선택지 None 인 select 는 말머리 소리 (폴더에서 읽는다)
FIELDS = {
    "toast": ("bool", None),
    "threshold": ("select", [(str(i), f"{i}점 이상") for i in range(5, 11)]),
    "max_age_min": ("select", [(str(m), f"{m}분") for m in (30, 60, 120, 180, 360)]),
    "tts": ("bool", None),
    "tts_voice": ("select", VOICES),
    "tts_rate": ("select", RATES),
    "tts_chime": ("select", None),
    "quiet_on": ("bool", None),
    "tts_quiet": ("quiet", None),
    "briefing_on": ("bool", None),
    "briefing_at": ("time", None),
    "briefing_hours": ("select", [(str(h), f"지난 {h}시간") for h in (6, 12, 24)]),
    "briefing_max": ("select", [(str(n), f"{n}건") for n in (3, 5, 8, 10)]),
    "summary_max": ("select", [(str(n), f"{n}건") for n in (3, 5, 8, 10)]),
    "wake_gap_min": ("select", [(str(m), f"{m}분 넘게") for m in (5, 10, 20, 30, 60)]),
    "suggest_days": ("select", [("0", "단추로만")] + [(str(d), f"{d}일마다") for d in (3, 7, 14, 30)]),
    "suggest_backend": ("select", BACKENDS),
    "catchup_hours": ("select", [(str(h), f"{h}시간") for h in (3, 6, 12, 24)]),
    "backend": ("select", BACKENDS),
    "claude_model": ("select", [("sonnet", "sonnet"), ("opus", "opus")]),
    "model": ("text", None),
    "hide_max_score": ("select", [("-1", "숨기지 않음")] + [(str(i), f"{i}점 이하") for i in range(0, 6)]),
}
INT_KEYS = {"threshold", "max_age_min", "briefing_hours", "briefing_max", "summary_max", "wake_gap_min",
            "suggest_days", "catchup_hours", "hide_max_score"}
LABELS = {"toast": "윈도우 알림", "threshold": "기준 점수", "max_age_min": "알림 시한", "tts": "음성으로 읽기",
          "tts_voice": "목소리", "tts_rate": "빠르기", "tts_chime": "말머리 소리", "quiet_on": "조용한 시각",
          "tts_quiet": "조용한 시각", "briefing_on": "장 전 브리핑", "briefing_at": "브리핑 시각",
          "briefing_hours": "브리핑 기간", "briefing_max": "브리핑 사건 수", "summary_max": "깨어난 뒤 요약",
          "wake_gap_min": "잠든 것으로 보는 시간", "suggest_days": "관심사 제안", "suggest_backend": "제안 LLM",
          "catchup_hours": "밀린 뉴스", "backend": "판별 LLM", "claude_model": "Claude 모델", "model": "Ollama 모델",
          "hide_max_score": "목록에서 숨기기"}


def apply(cfg: dict, key: str, value) -> tuple:
    """값 하나를 검사해 cfg 에 넣는다. (전, 후) 를 돌려준다."""
    if key not in FIELDS:
        raise ValueError(f"바꿀 수 없는 설정: {key}")
    kind, opts = FIELDS[key]
    if kind == "bool":
        value = bool(value)
    elif kind == "select":
        allowed = [o[0] for o in (opts if opts is not None else chimes())]
        value = str(value)
        if value not in allowed:
            raise ValueError("고를 수 없는 값")
        if key in INT_KEYS:
            value = int(value)
    elif kind == "quiet":
        value = str(value).strip()
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("23:00-07:00 처럼 넣어 주세요")
    elif kind == "time":
        value = str(value).strip()
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("21:00 처럼 넣어 주세요")
    else:
        value = str(value).strip()
        if not value:
            raise ValueError("비울 수 없습니다")
    before = cfg.get(key)
    cfg[key] = value
    return before, value


def save(cfg: dict, path: Path):
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# 화면
# ─────────────────────────────────────────────────────────────

e = html.escape


def _label(name: str, small: str = "", tip: str = "") -> str:
    info = (f" <button type=button class=info aria-expanded=false title=\"{e(tip)}\" aria-label=자세히>ⓘ</button>"
            if tip else "")
    return (f"<span class=mlabel><span>{e(name)}{info}</span>"
            + (f"<small>{e(small)}</small>" if small else "") + "</span>")


def _switch(cfg: dict, key: str) -> str:
    on = "true" if cfg.get(key) else "false"
    return f"<button class=switch data-key={key} role=switch aria-checked={on} aria-label=\"{e(LABELS[key])}\"></button>"


def _select(cfg: dict, key: str) -> str:
    opts = FIELDS[key][1]
    items = opts if opts is not None else chimes()
    cur = str(cfg.get(key, ""))
    if cur not in [o[0] for o in items]:   # 설정 파일에 목록 밖의 값이 있으면 그대로 보여 준다
        items = items + [(cur, cur)]
    return (f"<select data-key={key} aria-label=\"{e(LABELS[key])}\">"
            + "".join(f"<option value=\"{e(o)}\"{' selected' if o == cur else ''}>{e(t)}</option>" for o, t in items)
            + "</select>")


def row(cfg: dict, key: str, small: str = "", tip: str = "", control: str = "") -> str:
    """설정 한 줄. control 을 안 주면 종류에 맞춰 스위치나 고르기 칸을 넣는다."""
    control = control or (_switch(cfg, key) if FIELDS[key][0] == "bool" else _select(cfg, key))
    more = f"<p class=more hidden>{e(tip)}</p>" if tip else ""
    return f"<div class=mrow>{_label(LABELS[key], small, tip)}{control}</div>{more}"


def menu(cfg: dict) -> str:
    q = cfg.get("tts_quiet") or ""
    qfrom, qto = q.split("-") if re.fullmatch(r"\d\d:\d\d-\d\d:\d\d", q) else ("23:00", "07:00")
    at = cfg.get("briefing_at") if re.fullmatch(r"\d\d:\d\d", cfg.get("briefing_at") or "") else "21:00"
    return f"""<div class=menu id=setmenu hidden>
  <div class=mhead style="border-top:0;margin-top:0">알림</div>
  {row(cfg, "toast", "관심 뉴스를 토스트로 띄운다", "기준 점수 이상이고 알림 시한 안의 뉴스만 띄운다. 끄면 목록에만 쌓인다. 브리핑·요약·수집 멈춤 알림도 함께 꺼진다. 음성은 따로 끈다.")}
  {row(cfg, "threshold", "LLM 이 매긴 0~10점. [SAVE PICK] 은 늘 9점")}
  {row(cfg, "max_age_min", "나온 지 이보다 오래되면 알리지 않는다", "PC 가 잠들었다 깨면 밀린 뉴스가 한꺼번에 들어온다. 시한이 지난 뉴스도 판별해서 목록에는 올린다.")}

  <div class=mhead>소리 <small>꺼 둔 때도 알림 목록에는 쌓인다</small></div>
  {row(cfg, "tts", "말머리 소리 뒤에 제목을 줄인 말을 읽는다", "제목을 12자 안팎으로 줄인 말을 Edge 음성으로 읽는다 (예: 이란 휴전안 거부). 인터넷이 안 되면 윈도우 기본 음성으로 읽는다. 켜 두면 토스트 소리는 끈다.")}
  {row(cfg, "tts_voice", "종목 뉴스 필터는 선희 (여)")}
  {row(cfg, "tts_rate")}
  {row(cfg, "tts_chime", "종목 뉴스 필터는 Windows Notify Email")}
  {row(cfg, "quiet_on", "이 PC 시각. 23:00~07:00 처럼 자정을 넘어도 된다", "이 시간에는 말하지 않는다. 토스트는 그대로 뜬다.")}
  <div class="mrow qtimes"><input type=time id=qfrom value="{qfrom}" aria-label="조용한 시각 시작"> ~ <input type=time id=qto value="{qto}" aria-label="조용한 시각 끝"></div>
  <div class=mrow><input id=saytext value="이란 휴전안 거부" aria-label="읽어 볼 말"><button type=button class=hbtn id=soundtest title="고른 목소리로 한 번 읽는다">TTS 테스트</button></div>

  <div class=mhead>브리핑 · 요약</div>
  {row(cfg, "briefing_on", "평일 정한 시각에 주요 사건을 모아 읽는다", "미국 장이 열리기 전에 그동안의 기준 점수 이상 뉴스를 사건별로 묶어 읽고 토스트를 띄운다. PC 가 그 시각에 잠들어 있었으면 깬 뒤 2시간 안에는 한다.",
       f"<span class=mbtns><input type=time id=brat value=\"{at}\" aria-label=\"브리핑 시각\">" + _switch(cfg, "briefing_on") + "</span>")}
  {row(cfg, "briefing_hours", "브리핑에 담을 기간")}
  {row(cfg, "briefing_max", "브리핑에서 읽어 줄 사건 수")}
  {row(cfg, "summary_max", "PC 가 깨어난 뒤 밀린 뉴스 요약에서 읽을 수")}
  {row(cfg, "wake_gap_min", "감시가 이만큼 끊기면 잠들었다 깬 것으로 본다")}
  {row(cfg, "catchup_hours", "깨어나면 이만큼 거슬러 판별해 목록에 올린다")}

  <div class=mhead>판별</div>
  {row(cfg, "backend", "", "Ollama 는 이 PC 에서 돈다. 꺼져 있거나 엉뚱한 답을 내면 Claude CLI 로 넘긴다. Claude 는 구독 사용량을 쓴다.")}
  {row(cfg, "claude_model")}
  <div class=mrow>{_label(LABELS["model"])}<input data-key=model value="{e(str(cfg.get('model', '')))}" aria-label="Ollama 모델" size=14 spellcheck=false></div>
  {row(cfg, "suggest_days", "👍👎 기록으로 interests.md 고칠 곳을 제안한다", "제안은 점수 성적표 페이지에 뜬다. 고치는 것은 직접 한다.")}
  {row(cfg, "suggest_backend")}
  {row(cfg, "hide_max_score", "👍·🔔10 준 것은 점수와 상관없이 보인다")}
  <div class=mrow><small class=sub id=setmsg>바꾸면 바로 적용된다</small></div>
</div>"""


BUTTON = "<button type=button class='hbtn setbtn' id=setbtn aria-expanded=false>⚙ 설정</button>"

# 판별 목록의 글자 크기 단추(FS_BAR, 오른쪽 위에 고정) 왼쪽에 ⚙ 설정 단추를 둔다
CSS = """
:root{--bg:#16181c;--panel:#1c1f24;--line:#2e333b;--text:#e6e6e6;--muted:#8a9099;--pos:#3cc47c;--neg:#f0605a;--down:#5b8ff0;--sel:#23272e;--input:#16181c}
h2{padding-right:200px}
.hbtn{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:99px;padding:2px 9px;cursor:pointer;white-space:nowrap}
.hbtn:hover{background:var(--sel)} .hbtn:disabled{opacity:.4;cursor:default}
.setbtn{position:fixed;top:10px;right:104px;z-index:5;font-size:14px}
.menu{position:fixed;z-index:10;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 4px;box-shadow:0 4px 16px rgba(0,0,0,.4);display:grid;width:min(max(480px,calc(var(--fs) * 34)),calc(100vw - 16px));max-height:calc(100vh - 70px);overflow-y:auto;overflow-x:hidden}
.menu[hidden],.menu [hidden]{display:none!important}
.menu .sub{color:var(--muted);font-size:.9em}
.menu .mrow{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:4px 8px}
.menu .mlabel{display:grid;gap:1px} .menu .mlabel small{color:var(--muted);font-size:.85em}
.menu .mbtns{display:inline-flex;gap:8px;align-items:center}
.menu .info{font:inherit;border:0;background:none;color:var(--muted);cursor:pointer;padding:0 2px}
.menu .info:hover,.menu .info[aria-expanded="true"]{color:var(--down)}
.menu .more{margin:0 8px 4px;padding:6px 8px;border-radius:6px;background:var(--bg);color:var(--muted);font-size:.9em;line-height:1.5}
.menu .mhead{padding:8px 8px 2px;border-top:1px solid var(--line);margin-top:4px;font-weight:600}
.menu .mhead small{font-weight:400;color:var(--muted)}
.menu input,.menu select{font:inherit;color:var(--text);background:var(--input);border:1px solid var(--line);border-radius:5px;padding:2px 5px}
.menu input:disabled,.menu select:disabled{opacity:.5}
.menu .qtimes{justify-content:flex-end;gap:6px;color:var(--muted)}
.menu #saytext{flex:1;min-width:0}
.switch{position:relative;flex:none;width:calc(var(--fs)*3.2);height:calc(var(--fs)*1.8);padding:0;border:0;border-radius:99px;background:var(--line);cursor:pointer;transition:background .15s}
.switch::after{content:"";position:absolute;top:2px;left:2px;width:calc(var(--fs)*1.8 - 4px);height:calc(var(--fs)*1.8 - 4px);border-radius:50%;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.3);transition:transform .15s}
.switch[aria-checked="true"]{background:var(--pos)}
.switch[aria-checked="true"]::after{transform:translateX(calc(var(--fs)*1.4))}
.switch:focus-visible{outline:2px solid var(--down);outline-offset:2px}
.err{color:var(--neg)!important} .okmsg{color:var(--pos)!important}
"""

JS = r"""
(function () {
  const $ = s => document.querySelector(s);
  const btn = $("#setbtn"), menu = $("#setmenu");
  async function post(path, body) {
    try {
      const r = await fetch(path, {method: "POST", headers: {"X-Settings": "yes", "Content-Type": "application/json"},
                                   body: JSON.stringify(body || {})});
      return r.ok ? await r.json() : {ok: false, msg: "요청 실패 (" + r.status + ")"};
    } catch (err) { return {ok: false, msg: "판별기에 연결할 수 없습니다"}; }
  }
  function say(d, okText) {
    const el = $("#setmsg");
    el.classList.toggle("err", !d.ok);
    el.classList.toggle("okmsg", !!d.ok);
    el.textContent = d.ok ? okText : d.msg;
  }

  // ⚙ 설정: 단추 밑에 펼친다. 바깥을 누르면 닫는다
  const show = open => {
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open);
    if (!open) return;
    const b = btn.getBoundingClientRect();
    menu.style.top = `${b.bottom + 4}px`;
    menu.style.left = `${Math.max(8, Math.min(b.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 8))}px`;
  };
  btn.onclick = ev => { ev.stopPropagation(); show(menu.hidden); };
  document.addEventListener("click", ev => {
    if (!menu.contains(ev.target) && ev.target.isConnected) show(false);
  });

  // ⓘ: 마우스를 올리면 title 이 뜨고, 누르면 아래에 펼친다
  menu.addEventListener("click", ev => {
    const b = ev.target.closest(".info");
    if (!b) return;
    const more = b.closest(".mrow").nextElementSibling;
    if (!more || !more.classList.contains("more")) return;
    more.hidden = !more.hidden;
    b.setAttribute("aria-expanded", !more.hidden);
  });

  // 설정 하나 바꾸기: 바로 적용
  async function setKey(key, value) {
    const d = await post("/settings", {key, value});
    say(d, d.ok ? "적용했다 · " + d.label : "");
    return d.ok;
  }
  const isOn = key => menu.querySelector(`.switch[data-key="${key}"]`).getAttribute("aria-checked") === "true";
  function dim() {   // 꺼 둔 기능의 딸린 칸은 흐리게
    $("#qfrom").disabled = $("#qto").disabled = !isOn("quiet_on");
    ["tts_voice", "tts_rate", "tts_chime"].forEach(k => menu.querySelector(`[data-key="${k}"]`).disabled = !isOn("tts"));
    $("#brat").disabled = !isOn("briefing_on");
    ["briefing_hours", "briefing_max"].forEach(k => menu.querySelector(`[data-key="${k}"]`).disabled = !isOn("briefing_on"));
  }
  menu.querySelectorAll(".switch[data-key]").forEach(sw => sw.onclick = async () => {
    const on = sw.getAttribute("aria-checked") !== "true";
    if (await setKey(sw.dataset.key, on)) sw.setAttribute("aria-checked", on);
    dim();
  });
  menu.querySelectorAll("select[data-key], input[data-key]").forEach(el =>
    el.onchange = () => setKey(el.dataset.key, el.value));
  $("#qfrom").onchange = $("#qto").onchange = () => setKey("tts_quiet", $("#qfrom").value + "-" + $("#qto").value);
  $("#brat").onchange = () => setKey("briefing_at", $("#brat").value);
  dim();

  $("#soundtest").onclick = async () => {
    const d = await post("/say", {text: $("#saytext").value});
    say(d, "읽는 중 · " + (d.by || ""));
  };
})();
"""
