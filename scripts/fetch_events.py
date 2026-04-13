from __future__ import annotations

import argparse
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TaiwanStockEvents/1.0)",
    "Accept": "application/json, text/plain, */*",
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
    parser = argparse.ArgumentParser(description="Fetch TWSE dividend events into data/event.json")
    parser.add_argument(
        "--year",
        type=int,
        default=DEFAULT_TARGET_YEAR,
        help=f"Target year to fetch (default: {DEFAULT_TARGET_YEAR})",
    )
    return parser.parse_args()


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
    text = str(roc_compact).strip()
    if not re.fullmatch(r"\d{7,8}", text):
        return None
    roc_year = int(text[:-4])
    month = int(text[-4:-2])
    day = int(text[-2:])
    return roc_to_iso_date(roc_year, month, day)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def fetch_all_dividend_events_from_twse_openapi(target_year: int) -> List[EventItem]:
    rows = get_twse_openapi_exright()
    events: List[EventItem] = []
    start_date = f"{target_year:04d}-01-01"
    end_date = f"{target_year:04d}-12-31"

    for row in rows:
        stock_id = clean_text(row.get("Code"))
        stock_name = clean_text(row.get("Name"))
        iso_date = roc_compact_to_iso(clean_text(row.get("Date")))

        if not stock_id or not stock_name or not iso_date:
            continue

        if not (start_date <= iso_date <= end_date):
            continue

        events.append(
            EventItem(
                stock_id=stock_id,
                stock_name=stock_name,
                type="dividend",
                title=f"{stock_id} {stock_name}(除權息)",
                date=iso_date,
                source="TWSE OpenAPI TWT48U_ALL",
                url=TWSE_EXRIGHT_OPENAPI_URL,
            )
        )

    return events


def build_payload(events: List[EventItem], target_year: int) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    now_tpe = now_utc.astimezone(TAIPEI_TZ)

    unique: Dict[tuple, EventItem] = {}
    for event in events:
        key = (event.stock_id, event.date, event.type)
        unique[key] = event

    final_events = sorted(
        [asdict(v) for v in unique.values()],
        key=lambda x: (x["date"], x["stock_id"], x["stock_name"]),
    )

    return {
        "target_year": target_year,
        "updated_at_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "updated_at_taipei": now_tpe.strftime("%Y-%m-%d %H:%M:%S UTC+8"),
        "events": final_events,
    }


def main() -> None:
    args = parse_args()
    target_year = args.year
    events: List[EventItem] = []

    try:
        events.extend(fetch_all_dividend_events_from_twse_openapi(target_year))
    except Exception as exc:
        print(f"[warn] twse openapi fetch failed: {exc}")

    payload = build_payload(events, target_year)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[ok] wrote {OUTPUT_PATH} with {len(payload['events'])} events (year={target_year})")


if __name__ == "__main__":
    main()
