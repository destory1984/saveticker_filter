"""docs/architecture.png 를 그린다: python docs/draw_architecture.py (윈도우 맑은 고딕 필요)"""
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1800, 1250
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
d.text((40 * S, 78 * S), "뉴스 수집(Edge 확장) → 날짜별 CSV → LLM 판별 → 윈도우 알림 · 반응이 다음 판별에 되먹임",
       font=font(19), fill=MUTED)

BLUE, BLUE_BG = "#0969da", "#ddf4ff"
GREEN, GREEN_BG = "#1a7f37", "#dafbe1"
ORANGE, ORANGE_BG = "#bc4c00", "#fff1e5"
PURPLE, PURPLE_BG = "#8250df", "#fbefff"
GRAY_BG = "#f6f8fa"

# ---- column 1: web + Edge
box(40, 140, 360, 120, "saveticker.com", ["뉴스 API  /api/news/list", "  Cloudflare 보호 · 원문 → 번역 제목"], GRAY_BG, "#d0d7de")

group(30, 310, 390, 610, "Edge 브라우저 (확장 프로그램)", BLUE)
box(50, 340, 350, 200, "saveticker 뉴스 탭", [
    "hook.js  페이지가 받는 뉴스 응답 복사",
    "content.js  실시간 감시",
    "  60초마다 1·2페이지 확인",
    "  새 뉴스 · 번역된 제목 저장",
], BLUE_BG, BLUE)
box(50, 570, 350, 170, "background.js", [
    "새 뉴스가 오면 5초 뒤 자동 저장",
    "  그날 CSV 를 통째로 덮어씀",
    "감시견: 1분마다 탭 점검",
    "  멈췄으면 탭 새로고침",
], BLUE_BG, BLUE)
box(50, 770, 350, 130, "팝업", [
    "수집 건수 · 상태 · CSV/JSON 저장",
    "판별 끝난 제목은 흐리게",
], BLUE_BG, BLUE)

# ---- column 2: files
group(470, 310, 400, 610, "C:/_c/saveticker", GREEN)
box(490, 340, 360, 150, "data/", [
    "saveticker_news_YYYY-MM-DD.csv",
    "  다운로드/saveticker 가",
    "  이 폴더로 연결(junction)됨",
], GREEN_BG, GREEN)
box(490, 520, 360, 120, "interests.md", ["내 관심사 · 알릴 필요 없는 것", "  고치면 다음 판별부터 반영"], GREEN_BG, GREEN)
box(490, 670, 360, 110, "news_feedback.jsonl", ["🔔10 · 👍 · 👎 · 🔕0 반응 기록".replace("🔔", "").replace("👍", "좋아요").replace("👎", "별로").replace("🔕", "")], GREEN_BG, GREEN)
box(490, 800, 360, 100, "news_judged.jsonl", ["점수 · 이유 · 사건 이름 · 알림 여부"], GREEN_BG, GREEN)

# ---- column 3: judge
group(920, 140, 440, 780, "news_alert.py (백그라운드 · 윈도우 시작 시 자동 실행)", ORANGE)
box(940, 175, 400, 140, "1. 새 뉴스 찾기", [
    "10초마다 오늘·어제 CSV 확인",
    "  판별 안 한 뉴스 (60분 이내)",
    "  10건 모이거나 90초 지나면 묻기",
], ORANGE_BG, ORANGE)
box(940, 335, 400, 165, "2. 프롬프트 조립", [
    "관심사 (interests.md)",
    "+ 최근 반응 예시 (10점·0점 우선)",
    "+ 최근 3시간의 사건 이름",
    "+ 새 뉴스 제목 (한글 / 원문)",
], ORANGE_BG, ORANGE)
box(940, 520, 400, 170, "3. LLM 판별  점수 + 사건 이름", [
    "① Ollama  qwen3.8:27b  (로컬, 무료)",
    "② 실패·꺼짐·형식 오류면",
    "   claude -p --model sonnet",
    "  도구·MCP 없이 호출: 10건에 약 3천 토큰",
], ORANGE_BG, ORANGE)
box(940, 710, 400, 190, "4. 알릴지 결정", [
    "7점 이상 → 알림",
    "같은 사건은 1시간에 한 번만",
    "  발언마다 뜨는 속보, [2보]·[3보],",
    "  다른 매체의 같은 보도를 한 사건으로",
], ORANGE_BG, ORANGE)

# ---- column 4: outputs
box(1420, 175, 350, 200, "윈도우 알림 (토스트)", [
    "[8점] 연준 금리 인상 우려",
    "  제목 클릭 → 뉴스 열기",
    "  [좋아요] [별로] 버튼",
], PURPLE_BG, PURPLE)
box(1420, 430, 350, 290, "saveticker 필터링 페이지", [
    "http://127.0.0.1:18765",
    "판별 목록 · 점수 · 이유 · 제공처",
    "  같은 사건은 한 줄로 접기 (+N건)",
    "  15초마다 자동 갱신",
    "반응 버튼  10 · 좋아요 · 별로 · 0",
    "  별로 · 0점 · 3점 이하는 숨김",
    "처음부터 다시: 기록을 .bak 으로",
], PURPLE_BG, PURPLE)
box(1420, 770, 350, 130, "나", ["알림 보고 판단", "  반응할수록 판별이 내 취향에 맞춰짐"], "#ffffff", INK)

# ---- arrows
arrow([(360, 260), (360, 340)], "뉴스 응답", (370, 272), BLUE)
arrow([(225, 540), (225, 570)], color=BLUE)
arrow([(400, 655), (445, 655), (445, 415), (490, 415)], "CSV", (449, 560), GREEN)
arrow([(850, 415), (895, 415), (895, 250), (940, 250)], "읽기", (855, 330), ORANGE)
arrow([(850, 580), (905, 580), (905, 430), (940, 430)], None, None, ORANGE)
arrow([(850, 725), (915, 725), (915, 460), (940, 460)], None, None, ORANGE)
arrow([(1140, 315), (1140, 335)], color=ORANGE)
arrow([(1140, 500), (1140, 520)], color=ORANGE)
arrow([(1140, 690), (1140, 710)], color=ORANGE)
arrow([(1340, 820), (1385, 820), (1385, 275), (1420, 275)], "7점 이상", (1300 + 50, 520 - 290), PURPLE)
arrow([(1340, 850), (1395, 850), (1395, 575), (1420, 575)], "판별 기록", (1300, 925), PURPLE)
arrow([(1595, 375), (1595, 430)], "버튼", (1605, 390), PURPLE)
# feedback loop back to feedback file
arrow([(1420, 650), (1408, 650), (1408, 950), (890, 950), (890, 750), (850, 750)], "반응 기록 → 다음 판별 예시로 되먹임", (950, 958), PURPLE, dashed=True)
arrow([(940, 820), (870, 820), (870, 850), (850, 850)], None, None, ORANGE)
# popup dims judged
arrow([(1420, 690), (1414, 690), (1414, 1000), (225, 1000), (225, 900)], "판별 끝난 뉴스 목록 (/judged.json) → 팝업에서 흐리게", (500, 1008), MUTED, dashed=True)

# legend / run
d.text((40 * S, 1060 * S), "실행", font=font(20, True), fill=INK)
for i, t in enumerate([
    "news_alert_bg.vbs  창 없이 켜기 (시작프로그램 등록)   ·   news_alert_stop.bat  끄기   ·   로그  news_alert.log",
    "news_alert_config.json  기준 점수(threshold 7) · 모으는 시간(max_wait_sec 90) · 판별 모델 · 숨김 점수(hide_max_score 3)",
    "Edge 확장: saveticker 뉴스 탭이 열려 있고 팝업의 '실시간 감시'가 켜져 있어야 새 뉴스가 들어온다",
]):
    d.text((40 * S, (1095 + i * 30) * S), t, font=font(17), fill=MUTED)

img = img.resize((W, H), Image.LANCZOS)
img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "architecture.png"))
print("saved")
