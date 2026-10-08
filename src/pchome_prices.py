"""依資料庫中 ASUS 在售的型號，到 PChome 24h 搜尋售價，存成 data/raw/pchome_prices.jsonl（可中斷後續跑）。
build_db.py 會把結果寫進資料庫的 pchome_prices 表，並在 laptops 補上 pchome_price_min。

做法：
- 用基礎型號（如 UX3407QA）搜尋：直接搜完整銷售型號時 PChome 的斷詞效果差，常搜到別的型號
- 依相關度翻頁，商品名稱含基礎型號的才保留；某頁完全沒有就停止（後面多半是保護貼、鍵盤膜等配件）
- 從商品名稱抽出銷售型號（如 UX3407QA-0212G26100），對照資料庫的料號層級資料
- 標記「特仕」（通路自行加大記憶體或硬碟，配置與原廠不同）與「福利品、展示機」等非全新品
PChome 的 robots.txt 未禁止此搜尋 API；請求之間會間隔，避免造成負擔。"""
import json
import random
import re
import sqlite3
import time
from datetime import date
from pathlib import Path

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (laptop-assistant personal study project)"}
DB = Path("data/asus_laptops.db")
OUT = Path("data/raw/pchome_prices.jsonl")
SEARCH = "https://ecshweb.pchome.com.tw/search/v3.3/all/results"
MAX_PAGES = 10
ACCESSORY = re.compile(r"螢幕貼|保護貼|鍵盤膜|包膜|機身貼|變壓器|充電器|電池|轉接|保護殼|保護套|筆電包|背包", re.I)


def search(q: str, page: int) -> list[dict]:
    r = requests.get(SEARCH, params=dict(q=q, page=page, sort="rnk/dc"), headers=HEADERS, timeout=20)
    r.raise_for_status()
    time.sleep(random.uniform(1.0, 2.0))  # 放慢速度，避免造成網站負擔
    return r.json().get("prods") or []


def listings(base: str, known: set[str]) -> list[dict]:
    """搜尋一個基礎型號，回傳商品名稱含該型號的所有商品"""
    rows, seen = [], set()
    name_re = re.compile(rf"(?<![A-Z0-9]){re.escape(base)}(?![A-Z0-9])", re.I)
    sales_re = re.compile(rf"(?<![A-Z0-9]){re.escape(base)}-[0-9A-Z]+(?:-[0-9A-Z]+)?", re.I)
    for page in range(1, MAX_PAGES + 1):
        prods = search(base, page)
        # 名稱含型號的還有大量配件（螢幕貼、鍵盤膜、變壓器…）；筆電本身通常帶銷售型號，或價格明顯較高
        hits = [p for p in prods if name_re.search(p["name"]) and p["Id"] not in seen
                and (sales_re.search(p["name"]) or (p["price"] >= 8000 and not ACCESSORY.search(p["name"])))]
        for p in hits:
            seen.add(p["Id"])
            sales = [s.upper() for s in sales_re.findall(p["name"])]
            rows.append({
                "base_model": base,
                "sales_model": next((s for s in sales if s in known), sales[0] if sales else None),
                "in_asus_db": any(s in known for s in sales),  # 名稱中的銷售型號是否在 ASUS 官網料號資料中
                "pchome_id": p["Id"],
                "name": p["name"],
                "price": p["price"],
                "origin_price": p["originPrice"],
                "is_pchome": bool(p.get("isPChome")),  # True：PChome 自營；False：商店街等第三方賣家
                "is_custom": "特仕" in p["name"],  # 通路特製配置（加大記憶體、硬碟等），規格與原廠料號不同
                "is_refurb": bool(re.search(r"福利品|展示|整新|拆封|二手|福利機", p["name"])),
                "url": f"https://24h.pchome.com.tw/prod/{p['Id']}",
            })
        if not hits or len(prods) < 20:  # 這頁已沒有該型號的商品，或已到最後一頁
            break
    return rows


def main():
    with sqlite3.connect(DB) as con:
        bases = [r[0] for r in con.execute(
            "SELECT DISTINCT base_model FROM laptops WHERE base_model IS NOT NULL ORDER BY base_model")]
        known = {r[0] for r in con.execute("SELECT sales_model FROM laptops WHERE sales_model IS NOT NULL")}
    done = set()
    if OUT.exists():  # 續跑：跳過已搜尋過的基礎型號
        done = {json.loads(l)["base_model"] for l in OUT.open(encoding="utf-8")}
    todo = [b for b in bases if b not in done]
    print(f"基礎型號 {len(bases)} 個，已完成 {len(done)}，待處理 {len(todo)}")

    today = date.today().isoformat()
    with OUT.open("a", encoding="utf-8") as f:
        for i, base in enumerate(todo, 1):
            try:
                rows = listings(base, known)
            except (requests.RequestException, ValueError) as e:
                print(f"略過 {base}：{e}")
                continue
            # 沒找到也記一筆，續跑時才會跳過
            for r in rows or [{"base_model": base, "pchome_id": None}]:
                f.write(json.dumps(r | {"fetched_at": today}, ensure_ascii=False) + "\n")
            f.flush()
            exact = sum(r["in_asus_db"] for r in rows)
            print(f"{i} / {len(todo)}  {base}  → {len(rows)} 筆（對到官網料號 {exact}）")


if __name__ == "__main__":
    main()
