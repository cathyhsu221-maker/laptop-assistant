"""從 ASUS 台灣官網抓目前在售（官網「全系列」列表上）的筆電，以料號為單位原封不動存下完整規格到 data/raw/asus_models.jsonl。
一個料號（如 90NB1501-M00AS0）對應一個銷售型號（如 UX3407QA-0072D26100）與一組固定配置（CPU、RAM、螢幕、電池、顏色、變壓器…）。
流程：官網產品列表 API → 每個產品的型號 → 每個型號的料號與規格（一般機種走 odinapi、ROG 走 api-rog）→ 逐料號寫出（可中斷後續跑）
官網頁面的規格表是前端用 JavaScript 載入的，直接抓 HTML 拿不到，所以改呼叫官網背後的 API。
挑欄位、轉數值交給 build_db.py，這裡只負責保存原始資料。"""
import json
import random
import time
from datetime import date
from pathlib import Path

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (laptop-assistant personal study project)"}
OUT = Path("data/raw/asus_models.jsonl")
ODIN = "https://odinapi.asus.com/recent-data/apiv2/"
SKU_PRICE = "https://odinapi.asus.com/apiv2/GetModelSkuPrice"
ROG = "https://api-rog.asus.com/recent-data/api/v5/Product/ModelSpec"
PAGE_SIZE = 100


def get_json(url: str, **params) -> dict:
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    time.sleep(random.uniform(1.5, 3.0))  # 放慢速度，避免造成網站負擔
    return r.json()


def list_products() -> list[dict]:
    """官網「筆記型電腦 全系列」列表（含 ROG），只會列出目前在售的機種"""
    products, page = {}, 1
    while True:
        result = get_json(
            ODIN + "SeriesFilterResult", SystemCode="asus", WebsiteCode="tw",
            ProductLevel1Code="laptops", ProductLevel2Code="", PageSize=PAGE_SIZE, PageIndex=page,
            CategoryName="", SeriesName="", SubSeriesName="", Spec="", SubSpec="",
            PriceMin="", PriceMax="", Sort="Recommend", siteID="www", sitelang="",
        )["Result"]
        for p in result["ProductList"]:
            products.setdefault(p["ProductURL"], p)  # ROG 每個配置一張卡片，同一產品頁會重複出現
        if page * PAGE_SIZE >= result["TotalCount"] or not result["ProductList"]:
            return list(products.values())
        page += 1


def sku_rows(model: str, url: str) -> list[dict]:
    """一般機種的料號層級資料：GetModelSkuPrice 給料號清單與售價，PartNoPageResult 給每個料號的完整規格。
    只有 ASUS Store 有販售的型號才有料號資料，其餘回傳空清單"""
    skus = get_json(SKU_PRICE, SystemCode="asus", WebsiteCode="tw", ProductWebPath=model.lower(),
                    ModelType=2, group_id=0, siteID="www", sitelang="")
    prices = {s["PartNo"]: (s["Ec"] or [{}])[0] for s in (skus.get("Result") or {}).get("PartNoList") or []}
    if not prices:
        return []
    path = url.rstrip("/").split("/")  # https://www.asus.com/tw/laptops/for-home/zenbook/asus-zenbook-a14-ux3407
    part_nos, rows = list(prices), []
    for i in range(0, len(part_nos), 20):  # 一次查 20 個料號，避免網址過長
        result = get_json(
            ODIN + "PartNoPageResult", SystemCode="asus", WebsiteCode="tw", PartNo=",".join(part_nos[i:i + 20]),
            ProductWebPath=path[-1], ProductLevel1Code=path[-4], ProductLevel2Code=path[-3], siteID="www", sitelang="",
        )["Result"]
        for s in result.get("ProductList") or []:
            ec = prices.get(s["PartNo"], {})
            rows.append({
                "level": "sku", "model": model, "part_no": s["PartNo"], "sales_model": s["SalesModelName"],
                "price": ec.get("Mapping_Price") or None, "regular_price": ec.get("Regular_Price") or None,
                "specs": s["SpecList"],
            })
    return rows


def asus_models(p: dict) -> list[dict]:
    """一般機種：先用 PDTechSpecM2List 找出產品頁上的型號（如 UX3407QA、UX3407NA），
    有料號資料的型號逐料號存；沒有的只能存型號層級的規格（CPU、RAM 等列出所有選項，看不出搭配）。
    少數舊頁面沒有逐型號資料，只有一整段排版過的 HTML，就整段存在 spec_html。"""
    url = p["ProductURL"]
    params = dict(SystemCode="asus", WebSiteCode="tw", ProductWebPath=url.rstrip("/").split("/")[-1],
                  siteID="www", sitelang="")
    models = get_json(ODIN + "PDTechSpecM2List", particular="3w", **params)["Result"].get("TechSpec") or []
    rows = []
    for m in models:
        rows += sku_rows(m["Name"], url) or [{"level": "model", "model": m["Name"], "specs": m["SpecList"]}]
    if rows:
        return rows
    result = get_json(ODIN + "PDTechSpec", **params)["Result"]
    if result.get("SpecList"):
        return [{"level": "model", "specs": {s["Title"]: s["Content"] for s in result["SpecList"]}}]
    if result.get("SpecHTML"):
        return [{"level": "model", "specs": {}, "spec_html": result["SpecHTML"]}]
    return []


def rog_models(p: dict) -> list[dict]:
    """ROG：規格放在 api-rog，本身就是料號層級，例如料號 90NR0LR1-M00N30、銷售型號 G615LR-0071C290HX-NBL"""
    result = get_json(ROG, m1Id=p["M1Id"], WebsiteCode="tw")["result"]
    return [
        {
            "level": "sku",
            "part_no": s["partNo"],
            "sales_model": s["skuName"],
            "series": s["mktName"],
            "specs": {c["displayField"]: c["descriptionText"] for c in s["specContent"]},
        }
        for s in result.get("specObj") or []
    ]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    products = list_products()
    done = set()
    if OUT.exists():  # 續跑：跳過已處理的產品頁
        done = {json.loads(l)["url"] for l in OUT.open(encoding="utf-8")}
    todo = [p for p in products if p["ProductURL"] not in done]
    print(f"官網在售筆電 {len(products)} 個，已完成 {len(done)}，待處理 {len(todo)}")

    today = date.today().isoformat()
    empty = []
    with OUT.open("a", encoding="utf-8") as f:
        for i, p in enumerate(todo, 1):
            url = p["ProductURL"]
            try:
                models = rog_models(p) if p["isRogFlag"] else asus_models(p)
            except (requests.RequestException, KeyError, ValueError) as e:
                print(f"略過 {url}：{e}")
                continue
            for m in models:
                row = {
                    "url": url,
                    "source": "rog" if p["isRogFlag"] else "asus",
                    "series": m.pop("series", None) or p["Name"],
                    "category": p["Level3Path"],
                    "online_date": p["ProductOnlineDt"],
                    **m,
                    "fetched_at": today,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if not models:  # 不寫入，下次續跑會重試
                empty.append(url)
            f.flush()
            print(f"{i} / {len(todo)}  {url}  → {len(models)} 筆（料號 {sum(m['level'] == 'sku' for m in models)}）")
    if empty:
        print(f"\n{len(empty)} 個產品沒抓到規格：", *empty, sep="\n")


if __name__ == "__main__":
    main()
