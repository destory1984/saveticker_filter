"""docs/architecture.png 를 그린다: python docs/draw_architecture.py (윈도우 맑은 고딕 필요)"""
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1800, 1420
S = 2  # supersample
img = Image.new("RGB", (W * S, H * S), "#ffffff")
d = ImageDraw.Draw(img)

F = r"C:\Windows\Fonts\malgun.ttf"
FB = r"C:\Windows\Fonts\malgunbd.ttf"
def font(sz, bold=False):
    return ImageFont.truetype(FB if bold else F, sz * S)

INK = "#1f2328"
MUTED = "#57606a"
LINE = "#8c959f"

def box(x, y, w, h, title, lines, fill, edge, tsz=24):
    d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=14 * S,
                        fill=fill, outline=edge, width=3 * S)
    d.text(((x + 18) * S, (y + 14) * S), title, font=font(tsz, True), fill=INK)
    yy = y + 14 + tsz + 14
    for ln in lines:
        d.text(((x + 18) * S, yy * S), ln, font=font(17), fill=MUTED if ln.startswith("  ") else INK)
        yy += 27

def group(x, y, w, h, label, edge):
    d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=20 * S,
                        outline=edge, width=2 * S)
    tw = d.textlength(label, font=font(18, True))
    d.rectangle([(x + 20) * S, (y - 14) * S, (x + 20) * S + tw + 20 * S, (y + 14) * S], fill="#ffffff")
    d.text(((x + 30) * S, (y - 13) * S), label, font=font(18, True), fill=edge)

def arrow(pts, label=None, lpos=None, color=LINE, dashed=False):
    pts = [(px * S, py * S) for px, py in pts]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if dashed:
            n = int(max(abs(x2 - x1), abs(y2 - y1)) / (14 * S)) or 1
            for i in range(0, n, 2):
                a, b = i / n, min((i + 1) / n, 1)
                d.line([x1 + (x2 - x1) * a, y1 + (y2 - y1) * a, x1 + (x2 - x1) * b, y1 + (y2 - y1) * b],
                       fill=color, width=3 * S)
        else:
            d.line([x1, y1, x2, y2], fill=color, width=3 * S)
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    L = 16 * S
    d.polygon([(x2, y2),
               (x2 - L * math.cos(ang - 0.4), y2 - L * math.sin(ang - 0.4)),
               (x2 - L * math.cos(ang + 0.4), y2 - L * math.sin(ang + 0.4))], fill=color)
    if label:
        lx, ly = lpos
        for i, t in enumerate(label.split("\n")):
            tw = d.textlength(t, font=font(16))
            d.rectangle([lx * S - 4 * S, (ly + i * 22) * S - 2 * S, lx * S + tw + 4 * S, (ly + i * 22 + 22) * S],
                        fill="#ffffff")
            d.text((lx * S, (ly + i * 22) * S), t, font=font(16), fill=color)

# title
d.text((40 * S, 28 * S), "saveticker 필터링 — 구동 방식", font=font(34, True), fill=INK)
d.text((40 * S, 78 * S), "뉴스 수집(Edge 확장) → 날짜별 CSV → LLM 판별 → 윈도우 알림 · 음성 · 반응이 다음 판별에 되먹임",
       font=font(19), fill=MUTED)

BLUE, BLUE_BG = "#0969da", "#ddf4ff"
GREEN, GREEN_BG = "#1a7f37", "#dafbe1"
ORANGE, ORANGE_BG = "#bc4c00", "#fff1e5"
PURPLE, PURPLE_BG = "#8250df", "#fbefff"
GRAY_BG = "#f6f8fa"

# ---- column 1: web + Edge
box(40, 140, 360, 120, "saveticker.com", ["뉴스 API  /api/news/list", "  Cloudflare 보호 · 원문 → 번역 제목"], GRAY_BG, "#d0d7de")

group(30, 310, 390, 650, "Edge 브라우저 (확장 프로그램)", BLUE)
box(50, 340, 350, 240, "saveticker 뉴스 탭", [
    "hook.js  페이지가 받는 뉴스 응답 복사",
    "content.js  실시간 감시",
    "  60초마다 1·2페이지 확인",
    "  새 뉴스 · 번역된 제목 저장",
    "  PC 가 잠들었다 깨면 빈 시간을",
    "  최대 30페이지까지 거슬러 받음",
], BLUE_BG, BLUE)
box(50, 610, 350, 170, "background.js", [
    "새 뉴스가 오면 5초 뒤 자동 저장",
    "  그날 CSV 를 통째로 덮어씀",
    "감시견: 1분마다 탭 점검",
    "  멈췄으면 탭 새로고침",
], BLUE_BG, BLUE)
box(50, 810, 350, 130, "팝업", [
    "수집 건수 · 상태 · CSV/JSON 저장",
    "판별 끝난 제목은 흐리게",
], BLUE_BG, BLUE)
box(40, 1000, 360, 110, "Yahoo 시세 (yfinance)", ["공개 1분봉 · 프리·애프터 장 포함", "  계좌·보유 종목은 보지 않음"], GRAY_BG, "#d0d7de")

# ---- column 2: files
group(470, 310, 400, 800, "C:/_c/saveticker", GREEN)
box(490, 340, 360, 130, "data/", [
    "saveticker_news_YYYY-MM-DD.csv",
    "  다운로드/saveticker 가",
    "  이 폴더로 연결(junction)됨",
], GREEN_BG, GREEN)
box(490, 490, 360, 110, "interests.md", ["내 관심사 · 알릴 필요 없는 것", "  고치면 다음 판별부터 반영"], GREEN_BG, GREEN)
box(490, 620, 360, 100, "news_feedback.jsonl", ["10 · 좋아요 · 별로 · 0 반응 기록"], GREEN_BG, GREEN)
box(490, 740, 360, 110, "news_judged.jsonl", ["점수 · 이유 · 사건 이름 · 읽을 말", "  알림 여부 · 늦게 잡힌 뉴스 표시"], GREEN_BG, GREEN)
box(490, 870, 360, 100, "news_moves.jsonl", ["뉴스 뒤 5분 · 30분 시세 움직임"], GREEN_BG, GREEN)
box(490, 990, 360, 100, "interests_suggest.json", ["관심사 고침 제안 (마지막 것)"], GREEN_BG, GREEN)

# ---- column 3: judge
group(920, 140, 440, 1040, "news_alert.py (백그라운드 · 윈도우 시작 시 자동 실행)", ORANGE)
box(940, 175, 400, 160, "1. 새 뉴스 찾기", [
    "10초마다 오늘·어제 CSV 확인",
    "  판별 안 한 뉴스 (12시간 이내)",
    "  새것 먼저, 밀린 것은 한 묶음씩",
    "  10건 모이거나 90초 지나면 묻기",
], ORANGE_BG, ORANGE)
box(940, 355, 400, 165, "2. 프롬프트 조립", [
    "관심사 (interests.md)",
    "+ 최근 반응 예시 (10점·0점 우선)",
    "+ 최근 3시간의 사건 이름과 그 기사 제목",
    "+ 새 뉴스 제목 (한글 / 원문)",
], ORANGE_BG, ORANGE)
box(940, 540, 400, 170, "3. LLM 판별", [
    "점수 · 이유 · 사건 이름 · 읽을 말",
    "① Ollama  qwen3.8:27b  (로컬, 무료)",
    "② 실패·꺼짐·형식 오류면",
    "   claude -p --model sonnet",
], ORANGE_BG, ORANGE)
box(940, 730, 400, 170, "4. 알릴지 결정", [
    "7점 이상 → 토스트 + 음성",
    "  나온 지 60분 넘었으면 목록에만",
    "같은 사건은 1시간에 한 번만",
    "  [2보]·[3보], 다른 매체의 같은 보도",
], ORANGE_BG, ORANGE)
box(940, 920, 400, 240, "5. 곁일 (따로 도는 일)", [
    "잠든 사이 요약",
    "  감시가 10분 넘게 끊겼으면, 밀린 판별 뒤",
    "  중요 뉴스를 한 번에 알림",
    "시세 기록  7점 이상·좋아요 뉴스, 35분 뒤",
    "관심사 제안  7일마다 Claude 에게",
    "  놓친 뉴스 · 헛알림 · 잘 맞은 뉴스로",
], ORANGE_BG, ORANGE)

# ---- column 4: outputs
box(1420, 175, 350, 230, "윈도우 알림 + 음성", [
    "[8점] 연준 금리 인상 우려",
    "  제목 클릭 → 뉴스 열기",
    "  [좋아요] [별로] 버튼",
    "말머리 소리 → Edge 음성",
    "  \"이란 휴전안 거부\"",
    "  안 되면 윈도우 기본 음성",
], PURPLE_BG, PURPLE)
box(1420, 450, 350, 320, "saveticker 필터링 페이지", [
    "http://127.0.0.1:18765",
    "맨 위 최근 알림 (알린 시각 순)",
    "판별 목록 · 점수 · 이유 · 시세",
    "  같은 사건은 한 줄로 접기 (+N건)",
    "  15초마다 자동 갱신",
    "사건 이름 → 타임라인 · 흐름 요약",
    "반응 버튼  10 · 좋아요 · 별로 · 0",
    "처음부터 다시: 기록을 .bak 으로",
], PURPLE_BG, PURPLE)
box(1420, 800, 350, 190, "점수 성적표  /stats", [
    "점수대별 좋음 · 싫음 · 시세 움직임",
    "기준 점수를 바꾸면 알림이 어떻게",
    "놓친 뉴스 · 헛알림 목록",
    "관심사 고침 제안 보기 · 받기",
], PURPLE_BG, PURPLE)
box(1420, 1030, 350, 130, "나", ["알림 보고 판단", "  반응할수록 판별이 내 취향에 맞춰짐"], "#ffffff", INK)

# ---- arrows
arrow([(360, 260), (360, 340)], "뉴스 응답", (370, 272), BLUE)
arrow([(225, 580), (225, 610)], color=BLUE)
arrow([(400, 695), (445, 695), (445, 405), (490, 405)], "CSV", (449, 560), GREEN)
arrow([(850, 405), (895, 405), (895, 255), (940, 255)], "읽기", (855, 330), ORANGE)
arrow([(850, 545), (905, 545), (905, 430), (940, 430)], None, None, ORANGE)
arrow([(850, 670), (915, 670), (915, 470), (940, 470)], None, None, ORANGE)
arrow([(1140, 335), (1140, 355)], color=ORANGE)
arrow([(1140, 520), (1140, 540)], color=ORANGE)
arrow([(1140, 710), (1140, 730)], color=ORANGE)
arrow([(1140, 900), (1140, 920)], color=ORANGE)
arrow([(940, 795), (850, 795)], None, None, ORANGE)
arrow([(940, 945), (850, 945)], None, None, ORANGE)
arrow([(940, 1040), (850, 1040)], None, None, ORANGE)
arrow([(1340, 780), (1382, 780), (1382, 290), (1420, 290)], "7점 이상", (1346, 240), PURPLE)
arrow([(1340, 990), (1368, 990), (1368, 340), (1420, 340)], "요약", (1343, 996), PURPLE)
arrow([(1340, 850), (1398, 850), (1398, 610), (1420, 610)], None, None, PURPLE)   # 판별 기록 → 목록
arrow([(1595, 405), (1595, 450)], "버튼", (1605, 415), PURPLE)
arrow([(1595, 770), (1595, 800)], color=PURPLE)
# 시세
arrow([(225, 1110), (225, 1195), (1140, 1195), (1140, 1160)], "시세", (600, 1172), MUTED)
# feedback loop back to feedback file
arrow([(1420, 730), (1410, 730), (1410, 1225), (888, 1225), (888, 705), (850, 705)],
      "반응 기록 → 다음 판별 예시로 되먹임", (950, 1233), PURPLE, dashed=True)
# popup dims judged
arrow([(1420, 755), (1416, 755), (1416, 1260), (440, 1260), (440, 875), (400, 875)],
      "판별 끝난 뉴스 목록 (/judged.json) → 팝업에서 흐리게", (500, 1268), MUTED, dashed=True)

# legend / run
d.text((40 * S, 1310 * S), "실행", font=font(20, True), fill=INK)
for i, t in enumerate([
    "news_alert_bg.vbs  창 없이 켜기 (시작프로그램 등록)   ·   news_alert_stop.bat  끄기   ·   로그  news_alert.log   ·   python news_alert.py --say \"...\"  음성 시험",
    "news_alert_config.json  기준 점수(threshold 7) · 알릴 나이(max_age_min 60) · 거슬러 판별(catchup_hours 12) · 음성(tts, tts_quiet) · 시세(moves) · 제안(suggest_days 7)",
    "Edge 확장: saveticker 뉴스 탭이 열려 있고 팝업의 '실시간 감시'가 켜져 있어야 새 뉴스가 들어온다",
]):
    d.text((40 * S, (1345 + i * 26) * S), t, font=font(16), fill=MUTED)

img = img.resize((W, H), Image.LANCZOS)
img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "architecture.png"))
print("saved")
