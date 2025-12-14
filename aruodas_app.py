#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os

import aruodas_search


def _resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def main():
    url = input("URL: ").strip()
    if not url:
        print("Tuščias URL.")
        return

    top_s = input("TOP N: ").strip()
    top_n = int(top_s) if top_s.isdigit() and int(top_s) > 0 else 3

    argv = [
        url,
        "--top", str(top_n),
        "--analyzer", _resource_path("aruodas_analyze.exe"),
        "--market-csv", _resource_path("kainos.csv"),
        "--out-top3", "deals_top3.txt",
        "--append-to-market",
    ]

    aruodas_search.main(argv)


if __name__ == "__main__":
    main()
