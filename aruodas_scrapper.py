#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import os
import random
import re
import time
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


OUT_CSV_DEFAULT = "kainos.csv"


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


def parse_next_url(soup: BeautifulSoup, base_url: str):
    next_url = None

    # Prefer "Kitas" navigation button
    next_a = soup.select_one("div.nav-toolbar-v2 div.button-next-v2 a[href]")
    if next_a:
        next_url = next_a.get("href")

    # Fallback to rel="next"
    if not next_url:
        link = soup.find("link", rel=lambda x: x and "next" in x)
        next_url = link.get("href") if link else None

    if next_url:
        next_url = next_url.strip()
        if next_url and not next_url.startswith("http"):
            next_url = urljoin(base_url, next_url)

    return next_url


def parse_page(html: str, base_url: str):
    soup = BeautifulSoup(html, "lxml")
    next_url = parse_next_url(soup, base_url)

    items = []
    for block in soup.select("li.result-item-big-thumb"):
        a = block.select_one("a.object-image-link-big_thumbs[href]") or block.select_one("a[href]")
        if not a:
            continue
        href = (a.get("href") or "").strip()
        if not href:
            continue
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

        # Fallback parsing when structured fields are unavailable
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

        items.append({
            "url": url,
            "price_eur": price,
            "eur_per_m2": eur_m2,
            "rooms": rooms,
            "area_m2": area_m2,
            "irengtas": int(bool(irengtas)),
            "location": location,
            "street": street,
        })

    return items, next_url


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="Start URL for m.aruodas.lt")
    ap.add_argument("--out-csv", default=OUT_CSV_DEFAULT, help="Output CSV (append)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max-pages", type=int, default=0, help="0 = unlimited")
    ap.add_argument("--delay", default="0.10,0.25", help="Delay between pages: min,max")
    ap.add_argument("--timeout", type=int, default=25000)
    args = ap.parse_args()

    try:
        lo_s, hi_s = args.delay.split(",", 1)
        delay_range = (float(lo_s), float(hi_s))
    except Exception:
        print("Netinkamas --delay formatas. Naudoti: --delay 0.10,0.25")
        return

    out_csv = args.out_csv
    if not os.path.isabs(out_csv):
        out_csv = os.path.join(script_dir(), out_csv)

    scraped_at = datetime.now().isoformat(timespec="seconds")

    seen_listing_urls = set()
    seen_page_urls = set()

    total_written = 0
    page_no = 0
    url = args.url

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx = browser.new_context(
            locale="lt-LT",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"),
            viewport={"width": 1280, "height": 800},
        )

        # Block non-essential resources
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
                if args.max_pages and args.max_pages > 0 and page_no > args.max_pages:
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
                for it in items:
                    if it["url"] in seen_listing_urls:
                        continue
                    seen_listing_urls.add(it["url"])
                    out_rows.append({
                        "scraped_at": scraped_at,
                        **it,
                    })

                if out_rows:
                    append_to_csv(out_csv, out_rows)
                    total_written += len(out_rows)

                print(f"  rasta: {len(items)} | nauja įrašyta: {len(out_rows)} | viso įrašyta: {total_written}")

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

    print(f"OK: įrašyta į {out_csv} (+{total_written} eilučių)")


if __name__ == "__main__":
    main()
