from __future__ import annotations

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

STOCK_ID = "2330"
STOCK_NAME = "台積電"

TAIPEI_TZ = timezone(timedelta(hours=8))

# User-requested TWSE source (usable endpoint in current public OpenAPI schema)
TWSE_EXRIGHT_OPENAPI_URL = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
MOPS_API_BASE = "https://mops.twse.com.tw/mops/api/"
MOPS_DIVIDEND_API = "t108sb19"
MOPS_DIVIDEND_DETAIL_WEB = "https://mops.twse.com.tw/mops/web/t108sb19"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TaiwanStockEvents/1.0)",
    "Accept": "application/json, text/plain, */*",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
# TWSE/MOPS currently serve certificates that fail strict validation on Python 3.13 in this env.
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


def get_current_taipei_year() -> int:
    return datetime.now(TAIPEI_TZ).year


def post_mops_api(api_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    resp = SESSION.post(f"{MOPS_API_BASE}{api_name}", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_twse_openapi_exright() -> List[Dict[str, Any]]:
    resp = SESSION.get(TWSE_EXRIGHT_OPENAPI_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def roc_to_iso_date(roc_year: int, month: int, day: int) -> Optional[str]:
    try:
        dt = datetime(roc_year + 1911, month, day)
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d")


def roc_compact_to_iso(roc_compact: str) -> Optional[str]:
    # e.g. "1150317"
    text = str(roc_compact).strip()
    if not re.fullmatch(r"\d{7,8}", text):
        return None
    roc_year = int(text[:-4])
    month = int(text[-4:-2])
    day = int(text[-2:])
    return roc_to_iso_date(roc_year, month, day)


def extract_exright_trade_date(detail_text: str) -> Optional[str]:
    patterns = [
        r"除權/除息交易日[:：]\s*(\d{2,3})年\s*(\d{1,2})月\s*(\d{1,2})日",
        r"除息交易日[:：]\s*(\d{2,3})年\s*(\d{1,2})月\s*(\d{1,2})日",
        r"除權交易日[:：]\s*(\d{2,3})年\s*(\d{1,2})月\s*(\d{1,2})日",
    ]
    for pattern in patterns:
        match = re.search(pattern, detail_text)
        if not match:
            continue
        roc_year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        return roc_to_iso_date(roc_year, month, day)
    return None


def fetch_dividend_events_from_twse_openapi(current_year: int) -> List[EventItem]:
    rows = get_twse_openapi_exright()
    events: List[EventItem] = []
    for row in rows:
        if str(row.get("Code", "")).strip() != STOCK_ID:
            continue

        iso_date = roc_compact_to_iso(str(row.get("Date", "")))
        if not iso_date:
            continue
        if int(iso_date[:4]) != current_year:
            continue

        events.append(
            EventItem(
                stock_id=STOCK_ID,
                stock_name=STOCK_NAME,
                type="dividend",
                title="台積電除權息",
                date=iso_date,
                source="TWSE OpenAPI TWT48U_ALL",
                url=TWSE_EXRIGHT_OPENAPI_URL,
            )
        )
    return events


def fetch_dividend_events_from_mops(current_year: int) -> List[EventItem]:
    roc_year = current_year - 1911
    payload = {
        "companyId": STOCK_ID,
        "dataType": "2",
        "year": str(roc_year),
        "month": "all",
        "firstDay": "1",
        "lastDay": "31",
    }
    result = post_mops_api(MOPS_DIVIDEND_API, payload)
    if result.get("code") != 200 or not result.get("result"):
        return []

    rows = result["result"].get("recordDateAnnouncement", {}).get("data") or []
    events: List[EventItem] = []

    for row in rows:
        if not isinstance(row, list) or len(row) < 5:
            continue

        subject = str(row[2]).strip() if len(row) > 2 else "台積電除權息"
        detail_ref = row[4]
        if not isinstance(detail_ref, dict):
            continue

        api_name = detail_ref.get("apiName")
        parameters = detail_ref.get("parameters")
        if not api_name or not isinstance(parameters, dict):
            continue

        detail = post_mops_api(str(api_name), parameters)
        if detail.get("code") != 200 or not detail.get("result"):
            continue

        detail_rows = detail["result"].get("data") or []
        if not detail_rows or not isinstance(detail_rows[0], list):
            continue

        detail_text = "\n".join(item for item in detail_rows[0] if isinstance(item, str))
        iso_date = extract_exright_trade_date(detail_text)
        if not iso_date:
            continue
        if int(iso_date[:4]) != current_year:
            continue

        events.append(
            EventItem(
                stock_id=STOCK_ID,
                stock_name=STOCK_NAME,
                type="dividend",
                title=f"台積電除權息（{subject}）",
                date=iso_date,
                source="MOPS 除權息公告 (t108sb19)",
                url=MOPS_DIVIDEND_DETAIL_WEB,
            )
        )

    return events


def build_payload(events: List[EventItem]) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    now_tpe = now_utc.astimezone(TAIPEI_TZ)

    unique: Dict[tuple, EventItem] = {}
    for event in events:
        key = (event.type, event.date, event.title)
        unique[key] = event

    final_events = sorted(
        [asdict(v) for v in unique.values()],
        key=lambda x: (x["date"], x["type"], x["title"]),
    )

    return {
        "updated_at_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "updated_at_taipei": now_tpe.strftime("%Y-%m-%d %H:%M:%S UTC+8"),
        "stock_id": STOCK_ID,
        "stock_name": STOCK_NAME,
        "events": final_events,
    }


def main() -> None:
    current_year = get_current_taipei_year()
    events: List[EventItem] = []

    try:
        events.extend(fetch_dividend_events_from_twse_openapi(current_year))
    except Exception as exc:
        print(f"[warn] twse openapi fetch failed: {exc}")

    try:
        events.extend(fetch_dividend_events_from_mops(current_year))
    except Exception as exc:
        print(f"[warn] mops dividend fetch failed: {exc}")

    payload = build_payload(events)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[ok] wrote {OUTPUT_PATH} with {len(payload['events'])} dividend events for {current_year}"
    )


if __name__ == "__main__":
    main()
