"""목표가 표에 쓰는 현재가 (야후 5분봉, yfinance). stocknews_filter 의 moves.last_prices 와 같은 일을 한다.

목표가 DB 의 티커는 미국 종목이면 "MU", 한국 종목이면 거래소 코드 "005930" 이다.
한국 종목은 코스피(.KS)와 코스닥(.KQ)을 둘 다 물어 받히는 쪽을 쓴다.
"""
import time

KEEP_SEC = 300     # 이만큼 묵혀 쓴다 (표를 열 때마다 야후에 묻지 않게)
_cache = {"key": None, "at": 0.0, "data": {}}


def yahoo_symbols(ticker: str) -> list:
    """목표가 DB 의 티커를 야후 티커 후보로: "MU" → ["MU"], "005930" → ["005930.KS", "005930.KQ"]."""
    return [f"{ticker}.KS", f"{ticker}.KQ"] if ticker.isdigit() else [ticker]


def last_prices(tickers) -> dict:
    """{티커: (마지막 값, 그 시각)} 마지막 5분봉 (장 전·장 뒤 포함, 주말이면 금요일 장 뒤 값).
    받지 못한 티커는 빠진다. 야후가 안 되면 묵은 값이나 빈 것을 준다."""
    tickers = sorted({t for t in tickers if t})
    if not tickers:
        return {}
    if _cache["key"] == tickers and time.time() - _cache["at"] < KEEP_SEC:
        return _cache["data"]
    symbols = {s: t for t in tickers for s in yahoo_symbols(t)}
    try:
        import yfinance as yf
        df = yf.download(sorted(symbols), period="5d", interval="5m", prepost=True, progress=False,
                         auto_adjust=False, group_by="ticker", threads=True)
    except Exception:
        return _cache["data"] if _cache["key"] == tickers else {}
    out = {}
    for s, t in symbols.items():
        try:
            close = df[s]["Close"].dropna()
            if len(close) and t not in out:
                out[t] = (float(close.iloc[-1]), close.index[-1].to_pydatetime())
        except (KeyError, TypeError, ValueError):
            continue
    if out or _cache["key"] != tickers:
        _cache.update(key=tickers, at=time.time(), data=out)
    return _cache["data"]
