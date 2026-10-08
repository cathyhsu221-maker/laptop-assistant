"""依資料庫中 ASUS 在售的型號，到 momo 購物網搜尋售價，存成 data/raw/momo_prices.jsonl（可中斷後續跑）。
build_db.py 會把結果寫進資料庫的 momo_prices 表，並在 laptops 補上 momo_price_min。

做法：
- 用基礎型號（如 UX3407QA）搜尋，讀取搜尋結果頁內嵌的商品清單（schema.org ItemList），依頁數翻頁
- momo 的商品名稱多半只寫基礎型號與配置（如「Zenbook A16 UX3407QA/Snapdragon X1 26 100/16G/512G/W11」），
  沒有銷售型號，所以用配置比對：同基礎型號的料號中，記憶體、儲存容量、處理器編號都相符的才算對到。
  只差在顏色的料號規格相同，會一起對到（sales_model 以「/」分隔）
- 名稱有寫銷售型號時直接比對（match_type = exact）
- 標記組合包（如「滑鼠組★」「Office2024組★」，價格含贈品或軟體）、特仕版、福利品、第三方商店
momo 的 robots.txt 禁止 /api/、/ajax/ 等路徑，這裡只讀一般的搜尋結果頁；請求之間會間隔，避免造成負擔。"""
import html
import json
import random
import re
import sqlite3
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Safari/537.36 (laptop-assistant personal study project)"}
DB = Path("data/asus_laptops.db")
OUT = Path("data/raw/momo_prices.jsonl")
SEARCH = "https://www.momoshop.com.tw/search/{q}"
MAX_PAGES = 5
ACCESSORY = re.compile(r"螢幕貼|保護貼|鍵盤膜|包膜|機身貼|變壓器|充電器|電池|轉接|保護殼|保護套|筆電包|背包|防窺", re.I)


def search(q: str, page: int, retry: int = 2) -> tuple[list[dict], int]:
    """回傳 (商品清單, 總頁數)。偶爾會拿到沒有商品資料的頁面（防爬蟲或暫時性錯誤），等一下再重試"""
    r = requests.get(SEARCH.format(q=q), params={"curPage": page}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    time.sleep(random.uniform(2.0, 3.5))  # 放慢速度，避免造成網站負擔
    if '"ItemList"' not in r.text and "noResult" not in r.text and retry:
        time.sleep(10)
        return search(q, page, retry - 1)
    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for tag in soup.find_all("script", type="application/ld+json"):
        for g in json.loads(tag.string or "{}").get("@graph", []):
            if g.get("@type") == "ItemList":
                items += g.get("itemListElement", [])
    pages = re.search(r'maxPage\\?"\s*:\s*(\d+)', r.text)
    return items, int(pages.group(1)) if pages else 1


def norm(s: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", s.upper())


def config(name: str) -> dict:
    """從名稱括號內的「/」分段取記憶體與儲存容量：…/16G/512G/W11)、…/32G/1T/OLED)"""
    sizes = [int(m[1]) * (1024 if m[2].upper().startswith("T") else 1)
             for p in re.split(r"[/(（)）]", name)
             if (m := re.fullmatch(r"(\d+)\s*(G|GB|T|TB)\s*(?:SSD)?", p.strip(), re.I))]
    # 名稱裡依序是記憶體、儲存容量
    return {"ram_gb": sizes[0] if sizes else None, "storage_gb": sizes[1] if len(sizes) > 1 else None}


def match(name: str, base: str, skus: list[dict]) -> tuple[list[str], str | None]:
    """回傳 (對到的銷售型號清單, 比對方式)"""
    in_name = [s for s in (x["sales_model"] for x in skus) if s and norm(s) in norm(name)]
    if in_name:
        return in_name, "exact"
    cfg = config(name)
    if not skus or cfg["ram_gb"] is None or cfg["storage_gb"] is None:
        return [], None
    cands = [x for x in skus if x["ram_gb"] == cfg["ram_gb"] and x["storage_gb"] == cfg["storage_gb"]]
    with_cpu = [x for x in cands if x["cpu_number"] and norm(x["cpu_number"]) in norm(name)]
    cands = with_cpu or cands
    # 面板：名稱有 OLED 就只留 OLED 料號；沒寫則排除 OLED 料號（momo 的 OLED 機種名稱幾乎都會標示）
    is_oled = "OLED" in name.upper()
    cands = [x for x in cands if ("OLED" in (x["display_key"] or "")) == is_oled] or (cands if not is_oled else [])
    # 對到的料號規格必須一致（只差顏色）；不一致代表名稱資訊不足以分辨，寧可不對
    specs = {(x["cpu_number"], x["ram_gb"], x["storage_gb"], x["display_key"]) for x in cands}
    return ([x["sales_model"] for x in cands], "config") if cands and len(specs) == 1 else ([], None)


def listings(base: str, skus: list[dict]) -> list[dict]:
    rows, seen = [], set()
    name_re = re.compile(rf"(?<![A-Z0-9]){re.escape(base)}(?![A-Z0-9])", re.I)
    page, pages = 1, 1
    while page <= min(pages, MAX_PAGES):
        items, pages = search(base, page)
        for it in items:
            name, url = html.unescape(it.get("name", "")), it.get("url", "").strip()
            price = (it.get("offers") or {}).get("price")
            if not name_re.search(name) or not price or price < 8000 or ACCESSORY.search(name) or url in seen:
                continue
            seen.add(url)
            sales, how = match(name, base, skus)
            code = re.search(r"i_code=(\d+)|goodsDetail/(\w+)", url)
            rows.append({
                "base_model": base,
                "sales_model": "/".join(sales) or None,
                "match_type": how,  # exact：名稱有銷售型號；config：依配置比對；空：對不到料號
                "momo_id": next((g for g in code.groups() if g), None) if code else None,
                "name": name,
                "price": price,
                "is_momo": "/goods/GoodsDetail" in url,  # True：momo 自營；False：第三方商店（TP）
                "is_bundle": bool(re.search(r"組★|組合|★", name)),  # 加購滑鼠、Office、充電頭等的組合包
                "is_custom": "特仕" in name,
                "is_refurb": bool(re.search(r"福利品|展示|整新|拆封|二手|福利機", name)),
                "url": re.sub(r"&(Area|mdiv|oid|cid|kw|ecTagNos)=[^&]*", "", url),
            })
        page += 1
    return rows


def main():
    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            "SELECT l.base_model, l.sales_model, l.ram_gb_max AS ram_gb, l.storage_gb_max AS storage_gb, "
            "l.resolution || l.panel_type AS display_key, c.cpu_number "
            "FROM laptops l LEFT JOIN cpus c USING (cpu_model) WHERE l.base_model IS NOT NULL")]
    bases = sorted({r["base_model"] for r in rows})
    skus = {b: [r for r in rows if r["base_model"] == b and r["sales_model"]] for b in bases}
    done = set()
    if OUT.exists():  # 續跑：跳過已搜尋過的基礎型號
        done = {json.loads(l)["base_model"] for l in OUT.open(encoding="utf-8")}
    todo = [b for b in bases if b not in done]
    print(f"基礎型號 {len(bases)} 個，已完成 {len(done)}，待處理 {len(todo)}")

    today = date.today().isoformat()
    with OUT.open("a", encoding="utf-8") as f:
        for i, base in enumerate(todo, 1):
            try:
                found = listings(base, skus[base])
            except (requests.RequestException, ValueError) as e:
                print(f"略過 {base}：{e}")
                continue
            for r in found or [{"base_model": base, "momo_id": None}]:  # 沒找到也記一筆，續跑時才會跳過
                f.write(json.dumps(r | {"fetched_at": today}, ensure_ascii=False) + "\n")
            f.flush()
            matched = sum(bool(r["sales_model"]) for r in found)
            print(f"{i} / {len(todo)}  {base}  → {len(found)} 筆（對到官網料號 {matched}）")


if __name__ == "__main__":
    main()
