"""從 ASUS 台灣官網抓目前在售（官網「全系列」列表上）的筆電型號，原封不動存下完整規格到 data/raw/asus_models.jsonl。
流程：官網產品列表 API → 每個產品的規格 API（一般機種走 odinapi、ROG 走 api-rog）→ 逐型號寫出（可中斷後續跑）
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
            products.setdefault(p["ProductURL"], p)  # ROG 每個料號一張卡片，同一產品頁會重複出現
        if page * PAGE_SIZE >= result["TotalCount"] or not result["ProductList"]:
            return list(products.values())
        page += 1


def asus_models(p: dict) -> list[dict]:
    """一般機種：PDTechSpecM2List 回傳該產品頁上每個型號（如 UX3407QA、UX3407NA）的完整規格。
    少數舊頁面沒有逐型號資料，只有一整段排版過的 HTML，就整段存在 spec_html。"""
    web_path = p["ProductURL"].rstrip("/").split("/")[-1]
    params = dict(SystemCode="asus", WebSiteCode="tw", ProductWebPath=web_path, siteID="www", sitelang="")
    models = get_json(ODIN + "PDTechSpecM2List", particular="3w", **params)["Result"].get("TechSpec") or []
    if models:
        return [{"model": m["Name"], "specs": m["SpecList"]} for m in models]
    result = get_json(ODIN + "PDTechSpec", **params)["Result"]
    if result.get("SpecList"):
        return [{"model": None, "specs": {s["Title"]: s["Content"] for s in result["SpecList"]}}]
    if result.get("SpecHTML"):
        return [{"model": None, "specs": {}, "spec_html": result["SpecHTML"]}]
    return []


def rog_models(p: dict) -> list[dict]:
    """ROG：規格放在 api-rog，以料號（SKU）為單位，例如 G615LR-0071C290HX-NBL"""
    result = get_json(ROG, m1Id=p["M1Id"], WebsiteCode="tw")["result"]
    return [
        {
            "model": s["skuName"],
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
                    "sort_price": p["SortPrice"] or None,  # 列表上的排序用價格，多數機種是空的
                    "online_date": p["ProductOnlineDt"],
                    **m,
                    "fetched_at": today,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if not models:  # 不寫入，下次續跑會重試
                empty.append(url)
            f.flush()
            print(f"{i} / {len(todo)}  {url}  → {len(models)} 個型號")
    if empty:
        print(f"\n{len(empty)} 個產品沒抓到規格：", *empty, sep="\n")


if __name__ == "__main__":
    main()
