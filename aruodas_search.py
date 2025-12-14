#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

def _resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

def _force_playwright_browsers_path():
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return

    bundled = _resource_path("ms-playwright")
    if os.path.isdir(bundled):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled
        return

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(base, "ms-playwright")
    else:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")

_force_playwright_browsers_path()

from playwright.sync_api import sync_playwright


OUT_CSV_DEFAULT = "kainos.csv"
OUT_TXT_DEFAULT = "deals_top3.txt"

def script_dir() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def parse_money_eur(text: str):
    if not text:
        return None
    t = text.replace("\xa0", " ").replace("€", "").strip()
    digits = re.sub(r"[^\d]", "", t)
    return int(digits) if digits else None


def parse_eur_per_m2(text: str):
    if not text:
        return None
    t = text.replace("\xa0", " ").replace("€/m²", "").replace("€/m2", "").strip()
    digits = re.sub(r"[^\d]", "", t)
    return float(digits) if digits else None


def parse_rooms(text: str):
    if not text:
        return None
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


def parse_area_m2(text: str):
    if not text:
        return None
    t = text.replace("\xa0", " ").replace("m²", "").replace("m2", "").strip()
    t = t.replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    return float(m.group(1)) if m else None


def ensure_analyzer_path(p: str) -> str:
    p = (p or "").strip()
    if not p:
        return p
    if os.path.isabs(p) and os.path.exists(p):
        return p

    base = script_dir()
    cand = os.path.join(base, p)
    if os.path.exists(cand):
        return cand

    if os.name == "nt" and not p.lower().endswith(".exe"):
        cand_exe = os.path.join(base, p + ".exe")
        if os.path.exists(cand_exe):
            return cand_exe

    return cand


def append_to_csv(path: str, rows: list[dict]):
    is_new = not os.path.exists(path) or os.path.getsize(path) == 0
    fieldnames = [
        "scraped_at",
        "url",
        "price_eur",
        "eur_per_m2",
        "rooms",
        "area_m2",
        "irengtas",
        "location",
        "street",
    ]
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def parse_next_url(soup: BeautifulSoup, base_url: str):
    next_url = None

    next_a = soup.select_one("div.nav-toolbar-v2 div.button-next-v2 a[href]")
    if next_a:
        next_url = next_a.get("href")

    if not next_url:
        link = soup.find("link", rel=lambda x: x and "next" in x)
        next_url = link.get("href") if link else None

    if next_url:
        next_url = next_url.strip()
        if next_url and not next_url.startswith("http"):
            next_url = urljoin(base_url, next_url)

    return next_url


def parse_listing_block(block, base_url: str):
    a = block.select_one("a.object-image-link-big_thumbs[href]") or block.select_one("a[href]")
    if not a:
        return None
    href = (a.get("href") or "").strip()
    if not href:
        return None
    url = href if href.startswith("http") else urljoin(base_url, href)

    price_el = block.select_one(".price-main-v2")
    ppm_el = block.select_one(".price-per-v2")

    price = parse_money_eur(norm_space(price_el.get_text(" ", strip=True)) if price_el else "")
    eur_m2 = parse_eur_per_m2(norm_space(ppm_el.get_text(" ", strip=True)) if ppm_el else "")

    addr = [norm_space(x.get_text(" ", strip=True)) for x in block.select(".addressPiece")]
    location = addr[0] if addr else ""
    street = addr[1] if len(addr) > 1 else ""

    room_el = block.select_one(".description-item.desc-RoomNum .desc-img-txt")
    area_el = block.select_one(".description-item.desc-AreaOverall .desc-img-txt")
    state_el = block.select_one(".description-item.desc-HouseState .desc-img-txt")

    rooms = parse_rooms(norm_space(room_el.get_text(" ", strip=True)) if room_el else "")
    area_m2 = parse_area_m2(norm_space(area_el.get_text(" ", strip=True)) if area_el else "")
    state_txt = norm_space(state_el.get_text(" ", strip=True)) if state_el else ""
    irengtas = (state_txt == "Įrengtas")

    raw = norm_space(block.get_text(" ", strip=True))
    if rooms is None:
        m = re.search(r"(\d+)\s*(?:kamb\.|kamb|k\.)", raw, re.IGNORECASE)
        if m:
            rooms = int(m.group(1))
    if area_m2 is None:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", raw, re.IGNORECASE)
        if m:
            area_m2 = float(m.group(1).replace(",", "."))
    if not irengtas and "Įrengtas" in raw:
        irengtas = True

    if eur_m2 is None or eur_m2 <= 0:
        return None

    return {
        "url": url,
        "price_eur": price,
        "eur_per_m2": eur_m2,
        "rooms": rooms,
        "area_m2": area_m2,
        "irengtas": int(bool(irengtas)),
        "location": location,
        "street": street,
    }


def parse_page(html: str, base_url: str):
    soup = BeautifulSoup(html, "lxml")
    next_url = parse_next_url(soup, base_url)

    items = []
    for block in soup.select("li.result-item-big-thumb"):
        it = parse_listing_block(block, base_url=base_url)
        if it:
            items.append(it)

    return items, next_url


def run_cpp_analyzer(analyzer_path: str, market_csv: str, out_txt: str, top_n: int, min_street_n: int, street_only: bool, scraped_rows: list[dict]):
    header = ["scraped_at", "url", "price_eur", "eur_per_m2", "rooms", "area_m2", "irengtas", "location", "street"]

    def esc(v: str) -> str:
        v = "" if v is None else str(v)
        if any(ch in v for ch in [",", '"', "\n", "\r"]):
            v = v.replace('"', '""')
            return f'"{v}"'
        return v

    lines = []
    lines.append(",".join(header) + "\n")
    for r in scraped_rows:
        row = {
            "scraped_at": r.get("scraped_at", ""),
            "url": r.get("url", ""),
            "price_eur": "" if r.get("price_eur") is None else str(r.get("price_eur")),
            "eur_per_m2": "" if r.get("eur_per_m2") is None else str(r.get("eur_per_m2")),
            "rooms": "" if r.get("rooms") is None else str(r.get("rooms")),
            "area_m2": "" if r.get("area_m2") is None else str(r.get("area_m2")),
            "irengtas": "" if r.get("irengtas") is None else str(r.get("irengtas")),
            "location": r.get("location", ""),
            "street": r.get("street", ""),
        }
        lines.append(",".join(esc(row[h]) for h in header) + "\n")

    stdin_blob = "".join(lines).encode("utf-8", errors="replace")

    cmd = [
        analyzer_path,
        "--csv", market_csv,
        "--out", out_txt,
        "--top", str(max(1, int(top_n))),
        "--min-street-n", str(max(1, int(min_street_n))),
    ]
    if street_only:
        cmd.append("--street-only")

    r = subprocess.run(cmd, input=stdin_blob, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sys.stdout.write(r.stdout.decode("utf-8", errors="replace"))
    sys.stderr.write(r.stderr.decode("utf-8", errors="replace"))
    return r.returncode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="Startinis m.aruodas.lt URL")

    ap.add_argument("--out-csv", default=OUT_CSV_DEFAULT, help="kainos.csv (appendins)")
    ap.add_argument("--analyzer", default="aruodas_analyze.exe", help="C++ analizatorius")
    ap.add_argument("--market-csv", default=OUT_CSV_DEFAULT, help="CSV medianoms (tas pats kainos.csv)")

    ap.add_argument("--out-top3", default=OUT_TXT_DEFAULT, help="deals_top3.txt")
    ap.add_argument("--top", type=int, default=3, help="TOP N")
    ap.add_argument("--min-street-n", type=int, default=5)
    ap.add_argument("--street-only", action="store_true")

    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max-pages", type=int, default=0, help="0 = be limito")
    ap.add_argument("--max-items", type=int, default=0, help="0 = be limito")
    ap.add_argument("--delay", default="0.10,0.25")
    ap.add_argument("--timeout", type=int, default=25000)

    g = ap.add_mutually_exclusive_group()
    g.add_argument("--append-to-market", action="store_true", help="appendinti surinktus į market-csv")
    g.add_argument("--no-append-to-market", action="store_true", help="neappendinti į market-csv")

    args = ap.parse_args(argv)

    try:
        lo_s, hi_s = args.delay.split(",", 1)
        delay_range = (float(lo_s), float(hi_s))
    except Exception:
        print("Blogas --delay formatas. Naudok: --delay 0.10,0.25")
        return 2

    out_csv = args.out_csv
    if not os.path.isabs(out_csv):
        out_csv = os.path.join(script_dir(), out_csv)

    market_csv = args.market_csv
    if not os.path.isabs(market_csv):
        market_csv = os.path.join(script_dir(), market_csv)

    out_top3 = args.out_top3
    if not os.path.isabs(out_top3):
        out_top3 = os.path.join(script_dir(), out_top3)

    analyzer_path = ensure_analyzer_path(args.analyzer)
    if not os.path.exists(analyzer_path):
        print(f"NERASTAS analizatorius: {analyzer_path}")
        return 3

    append_to_market = True
    if args.no_append_to_market:
        append_to_market = False
    elif args.append_to_market:
        append_to_market = True

    scraped_at = datetime.now().isoformat(timespec="seconds")

    seen_listing_urls = set()
    seen_page_urls = set()

    collected = []
    total_written = 0

    url = args.url
    page_no = 0

    max_pages = args.max_pages if args.max_pages and args.max_pages > 0 else None
    max_items = args.max_items if args.max_items and args.max_items > 0 else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx = browser.new_context(
            locale="lt-LT",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"),
            viewport={"width": 1280, "height": 800},
        )

        def route_handler(route):
            rt = route.request.resource_type
            if rt in ("image", "media", "font"):
                return route.abort()
            return route.continue_()

        ctx.route("**/*", route_handler)
        page = ctx.new_page()

        try:
            while url:
                if url in seen_page_urls:
                    print(f"STOP: kartojasi puslapio URL: {url}")
                    break
                seen_page_urls.add(url)

                page_no += 1
                if max_pages and page_no > max_pages:
                    break

                print(f"[{page_no}] OPEN {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=args.timeout)

                try:
                    page.wait_for_selector("li.result-item-big-thumb", timeout=8000)
                except Exception:
                    pass

                html = page.content()
                items, next_url = parse_page(html, base_url=url)

                out_rows = []
                added = 0
                for it in items:
                    if max_items and (len(collected) >= max_items):
                        break
                    if it["url"] in seen_listing_urls:
                        continue
                    seen_listing_urls.add(it["url"])

                    row = {"scraped_at": scraped_at, **it}
                    collected.append(row)
                    out_rows.append(row)
                    added += 1

                if out_rows:
                    append_to_csv(out_csv, out_rows)
                    total_written += len(out_rows)

                lim_s = f"{len(collected)}/{max_items}" if max_items else f"{len(collected)}"
                print(f"  rasta: {len(items)} | nauja: {added} | viso surinkta: {lim_s} | į CSV: +{len(out_rows)} (viso {total_written})")

                if max_items and (len(collected) >= max_items):
                    break

                if not next_url or next_url == url:
                    break

                url = next_url
                lo, hi = delay_range
                time.sleep(random.uniform(lo, hi))

        except KeyboardInterrupt:
            print("\nCTRL+C: sustabdyta.")
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

    if not collected:
        print("0 skelbimų.")
        return 4

    if append_to_market and os.path.abspath(out_csv) != os.path.abspath(market_csv):
        try:
            append_to_csv(market_csv, collected)
        except Exception as e:
            print(f"CSV append klaida: {e}")

    rc = run_cpp_analyzer(
        analyzer_path=analyzer_path,
        market_csv=market_csv,
        out_txt=out_top3,
        top_n=args.top,
        min_street_n=args.min_street_n,
        street_only=args.street_only,
        scraped_rows=collected,
    )

    if rc != 0:
        print(f"Analizatorius grąžino klaidą: {rc}")
        return rc

    print(f"OK: įrašyta į {out_csv} (+{total_written} eilučių)")
    print(f"OK: TOP įrašyta į {out_top3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
