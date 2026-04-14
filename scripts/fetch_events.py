from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import urllib3

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH = DATA_DIR / "event.json"
DEFAULT_TARGET_YEAR = 2026

TAIPEI_TZ = timezone(timedelta(hours=8))

TWSE_EXRIGHT_OPENAPI_URL = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
YAHOO_EARNINGS_URL = "https://tw.stock.yahoo.com/calendar/earnings-call"

# 先放你目前確認可用的 MOPS 月曆 AJAX
# 之後可再補更多月份對應的 URL
MOPS_CALENDAR_AJAX_URLS = [
    "https://mopsov.twse.com.tw/mops/web/ajax_t108sb31new?parameters=32b138d25ee38c00fbf70ec5a53724972a4500829419c933492103358a9148bf8071084b1d15b7c2be8059c3409a33790215e2716103522dc12fcade661b00b9cb43e69e3adaae4bf31480e2c089bfa8",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/json,text/plain,*/*",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
SESSION.verify = False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass
class EventItem:
    stock_id: str
    stock_name: str
    type: str
    title: str
    date: str
    source: str
    url: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch stock events into data/event.json")
    parser.add_argument("--year", type=int, default=DEFAULT_TARGET_YEAR)
    return parser.parse_args()


def clean_text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def fetch_text(url: str) -> str:
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


# -------------------------
# 除權息：TWSE
# -------------------------
def roc_to_iso(roc: str) -> Optional[str]:
    if not re.fullmatch(r"\d{7,8}", roc):
        return None
    y = int(roc[:-4]) + 1911
    m = int(roc[-4:-2])
    d = int(roc[-2:])
    try:
        return f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        return None


def fetch_dividend(year: int) -> List[EventItem]:
    resp = SESSION.get(TWSE_EXRIGHT_OPENAPI_URL, timeout=30)
    resp.raise_for_status()
    rows = resp.json()

    events: List[EventItem] = []

    for r in rows:
        stock_id = clean_text(r.get("Code"))
        stock_name = clean_text(r.get("Name"))
        date = roc_to_iso(clean_text(r.get("Date")))

        if not stock_id or not stock_name or not date:
            continue
        if not date.startswith(str(year)):
            continue

        events.append(
            EventItem(
                stock_id=stock_id,
                stock_name=stock_name,
                type="dividend",
                title=f"{stock_id} {stock_name}(除權息)",
                date=date,
                source="TWSE",
                url=TWSE_EXRIGHT_OPENAPI_URL,
            )
        )

    return events


# -------------------------
# MOPS 月曆：除權息 / 股東會
# -------------------------
def yyyymmdd_to_iso(date_text: str) -> Optional[str]:
    date_text = clean_text(date_text)
    if not re.fullmatch(r"\d{8}", date_text):
        return None
    try:
        dt = datetime.strptime(date_text, "%Y%m%d")
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d")


def parse_mops(url: str) -> List[EventItem]:
    text = fetch_text(url)
    events: List[EventItem] = []
    entry_pattern = re.compile(
        r"COMP\.value='(?P<stock_id>[^']+)';document\.t108sb31new_fm2\.DATE1\.value='(?P<date>\d{8})';.*?\">(?P<link_text>.*?)</u>",
        re.S,
    )

    for m in entry_pattern.finditer(text):
        stock_id = clean_text(m.group("stock_id"))
        date = yyyymmdd_to_iso(m.group("date"))
        if not stock_id or not date:
            continue

        link_html = m.group("link_text")
        line = html.unescape(re.sub(r"<[^>]+>", "", link_html))
        line = line.replace("\xa0", " ")
        line = re.sub(r"\s+", " ", line).strip()

        row_match = re.match(
            rf"^{re.escape(stock_id)}\s+(.+?)[(（]([除股臨])[)）]$",
            line,
        )
        if not row_match:
            continue

        stock_name = row_match.group(1).strip()
        flag = row_match.group(2)

        if flag == "除":
            event_type = "dividend"
            label = "除權息"
        elif flag == "股":
            event_type = "shareholder_meeting"
            label = "股東會"
        else:
            event_type = "shareholder_meeting"
            label = "股東臨時會"

        events.append(
            EventItem(
                stock_id=stock_id,
                stock_name=stock_name,
                type=event_type,
                title=f"{stock_id} {stock_name}({label})",
                date=date,
                source="MOPS",
                url=url,
            )
        )

    return events


def fetch_mops(year: int) -> List[EventItem]:
    events: List[EventItem] = []

    for url in MOPS_CALENDAR_AJAX_URLS:
        try:
            month_events = parse_mops(url)
        except Exception as e:
            print(f"[warn] MOPS parse failed: {url} | {e}")
            continue

        for e in month_events:
            if e.date.startswith(str(year)):
                events.append(e)

    return events


# -------------------------
# Yahoo 法說會
# -------------------------
def parse_yahoo_datetime(text: str) -> Optional[str]:
    text = clean_text(text)
    if not text:
        return None

    m = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if m:
        return m.group(0)

    formats = ["%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_yahoo_symbol(symbol_text: str) -> str:
    symbol_text = clean_text(symbol_text)
    return re.sub(r"\.(TW|TWO)$", "", symbol_text, flags=re.IGNORECASE)


def parse_yahoo_state(html: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"root\.App\.main\s*=\s*(\{.*?\});\n", html, re.S)
    if not m:
        return None

    raw = m.group(1)
    normalized = raw
    normalized = re.sub(r":-Infinity([,}])", r":null\1", normalized)
    normalized = re.sub(r":Infinity([,}])", r":null\1", normalized)
    normalized = re.sub(r":NaN([,}])", r":null\1", normalized)
    normalized = re.sub(r":undefined([,}])", r":null\1", normalized)

    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        return None


def fetch_yahoo_earnings(year: int) -> List[EventItem]:
    html = fetch_text(YAHOO_EARNINGS_URL)
    state = parse_yahoo_state(html)
    if not state:
        return []

    calendars = (
        state.get("context", {})
        .get("dispatcher", {})
        .get("stores", {})
        .get("CalendarsStore", {})
        .get("data", {})
        .get("calendars", {})
    )

    events: List[EventItem] = []
    for _, day_data in calendars.items():
        if not isinstance(day_data, dict):
            continue

        earnings = day_data.get("earningsCall") or []
        if not isinstance(earnings, list):
            continue

        for item in earnings:
            if not isinstance(item, dict):
                continue

            stock_symbol = clean_text(item.get("symbol"))
            stock_name = clean_text(item.get("symbolName"))
            date_text = clean_text(item.get("date"))

            stock_id = normalize_yahoo_symbol(stock_symbol)
            iso_date = parse_yahoo_datetime(date_text)

            if not stock_id or not stock_name or not iso_date:
                continue
            if not iso_date.startswith(str(year)):
                continue

            events.append(
                EventItem(
                    stock_id=stock_id,
                    stock_name=stock_name,
                    type="earnings_call",
                    title=f"{stock_id} {stock_name}(法說會)",
                    date=iso_date,
                    source="Yahoo",
                    url=YAHOO_EARNINGS_URL,
                )
            )

    return events


# -------------------------
# 輸出
# -------------------------
def build(events: List[EventItem], year: int) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    now_tpe = now_utc.astimezone(TAIPEI_TZ)

    unique: Dict[tuple, EventItem] = {}
    for e in events:
        unique[(e.stock_id, e.date, e.type)] = e

    final = sorted(
        [asdict(v) for v in unique.values()],
        key=lambda x: (x["date"], x["stock_id"], x["type"], x["stock_name"]),
    )

    return {
        "year": year,
        "updated_at_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "updated_at_taipei": now_tpe.strftime("%Y-%m-%d %H:%M:%S UTC+8"),
        "events": final,
    }


def main() -> None:
    args = parse_args()
    year = args.year

    events: List[EventItem] = []

    try:
        events += fetch_dividend(year)
    except Exception as e:
        print(f"[warn] dividend failed: {e}")

    try:
        events += fetch_mops(year)
    except Exception as e:
        print(f"[warn] mops failed: {e}")

    try:
        events += fetch_yahoo_earnings(year)
    except Exception as e:
        print(f"[warn] yahoo earnings failed: {e}")

    data = build(events, year)

    OUTPUT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("done:", len(data["events"]))


if __name__ == "__main__":
    main()
