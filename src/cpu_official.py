"""從 Intel、AMD 官方資料整理處理器規格，存成 data/reference/cpu_official.csv，供 build_db.py 併入 cpus 表。
ASUS 規格頁只寫總核心數與單一快取數字，這裡補上大小核數量、L2/L3 快取、功耗等官方數值。

來源：
- AMD：amd.com 處理器規格總表（頁面內嵌所有處理器的 JSON），含 L2、L3、核心、時脈、TDP
- Intel：官方筆電處理器比較表 PDF（大小核數量、快取、基礎功耗），
  比較表沒收錄的型號與 PDF 沒有的欄位（L2、最大睿頻功耗等），手動從 Intel 官網規格頁查到後記在 data/reference/intel_ark.csv
  （Intel 官網會擋程式抓取，只能手動查）
Intel 標示的「Cache / Intel Smart Cache」是最後一層快取（L3）；Intel 大多不公布 L2，只有少數型號（如 HX 系列）有寫。

AI 算力分兩欄：npu_tops 只算 NPU，overall_tops 是 CPU + GPU + NPU 的平台總和（皆為官方標示，Intel 為 INT8）。
- AMD：各處理器產品頁的「NPU TOPS」「Overall TOPS」（規格總表 JSON 沒有這兩欄，只對有 NPU 的世代逐頁抓）
- Intel：官網規格頁的「NPU Peak TOPS (Int8)」「Overall Peak TOPS (Int8)」，手動查後記在 data/reference/intel_npu.csv"""
import html
import json
import random
import re
import time
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (laptop-assistant personal study project)"}
OUT = Path("data/reference/cpu_official.csv")
INTEL_MANUAL = Path("data/reference/intel_ark.csv")
INTEL_NPU = Path("data/reference/intel_npu.csv")
AMD_NPU_CODENAMES = {"Phoenix", "Hawk Point", "Strix Point", "Krackan Point", "Strix Halo", "Gorgon Point", "Gorgon Halo"}
AMD_URL = "https://www.amd.com/en/products/specifications/processors.html"
INTEL_PDFS = [  # 後面的覆蓋前面的（新版比較表優先）
    "https://cdrdv2-public.intel.com/841783/Intel-Core-Comparsion.pdf",
    "https://cdrdv2-public.intel.com/851467/Intel-Core-Ultra-Series1-Series2-Series3-Comparison.pdf",
]
COLS = ["key", "vendor", "official_name", "codename", "launch", "cores", "p_cores", "e_cores", "lpe_cores", "threads",
        "base_ghz", "boost_ghz", "l2_mb", "l3_mb", "npu_tops", "overall_tops", "igpu", "base_power_w", "max_power_w", "min_power_w",
        "notes", "source_url"]


def num(text) -> float | None:
    """'5.1 GHz2,4' → 5.1（去掉註腳）；'12 MB' → 12；'N/A' → None"""
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(text or ""))
    return float(m.group(1)) if m else None


def gpu_name(text) -> str | None:
    """'/Intel® Arc™ Graphics 130V' → 'Intel Arc Graphics 130V'；'AMD Radeon™ 890M' → 'AMD Radeon 890M'"""
    text = re.sub(r"[®™]", "", str(text or "")).strip(" /")
    text = re.sub(r"^T(?=Intel)", "", text)  # 比較表 PDF 有一格多出字首 T（'TIntel Arc 140T GPU'）
    if re.search(r"Discrete Graphics Card Required", text, re.I):  # AMD 標示沒有內顯的型號，如 Ryzen 7 7435HS
        return "無內顯（需搭配獨顯）"
    return re.sub(r"\s+", " ", text).strip() or None


def amd_key(name: str) -> str:
    """'AMD Ryzen™ AI 9 HX 370' → 'ryzen ai 9 hx 370'，與 build_db 的 cpu_model 轉小寫後相同"""
    name = re.sub(r"[®™]", " ", name).replace("AMD", " ")
    return re.sub(r"\s+", " ", name).strip().lower()


def amd() -> list[dict]:
    page = requests.get(AMD_URL, headers=HEADERS, timeout=60).content.decode("utf-8")  # 伺服器沒標編碼，requests 會誤判
    items = json.loads(html.unescape(re.search(r'data-json="(\{&#34;[^"]+)"', page).group(1)))["items"]
    rows = []
    for it in items:
        e = {k: v.get("formatValue") for k, v in it["elements"].items()}
        if "Laptops" not in (e.get("formFactor") or []):
            continue
        ctdp = re.findall(r"\d+", str(e.get("amdConfigurableTdpCtdp") or ""))
        rows.append({
            "key": amd_key(e["name"]), "vendor": "AMD", "official_name": e["name"],
            "codename": ", ".join(e.get("formerCodename") or []) or None, "launch": e.get("launchDate"),
            "cores": num(e.get("numOfCpuCores")), "threads": num(e.get("numOfThreads")),
            "base_ghz": num(e.get("baseClock")), "boost_ghz": num(e.get("maxBoostClock")),
            "l2_mb": num(e.get("l2Cache")), "l3_mb": num(e.get("l3Cache")), "igpu": gpu_name(e.get("graphicsModel")),
            "base_power_w": num(e.get("defaultTdp")),
            "min_power_w": float(ctdp[0]) if ctdp else None, "max_power_w": float(ctdp[-1]) if ctdp else None,
            "source_url": it["productPages"].get("en") or AMD_URL,
        })
    return rows


def amd_tops(url: str) -> dict:
    """AMD 產品頁的「AI Engine Capabilities」區塊：NPU TOPS | Up to 50 TOPS、Overall TOPS | Up to 80 TOPS"""
    page = requests.get(url, headers=HEADERS, timeout=60).content.decode("utf-8")
    time.sleep(random.uniform(1.0, 2.0))
    text = BeautifulSoup(page, "html.parser").get_text(" | ", strip=True)
    get = lambda label: num((re.search(rf"{label}\s*\|\s*(?:Up to\s*)?([\d.]+)\s*TOPS", text) or [None, None])[1])  # noqa: E731
    return {"npu_tops": get("NPU TOPS"), "overall_tops": get("Overall TOPS")}


def intel_key(number: str) -> str:
    """比較表的處理器編號可能黏著註腳數字（'i3-1315U6'、'i5-13500H7'），去掉後轉小寫"""
    number = re.sub(r"(?<=[HUPX])\d$", "", number.strip())
    return number.lower()


def intel_pdf(url: str) -> list[dict]:
    doc = fitz.open(stream=requests.get(url, headers=HEADERS, timeout=60).content, filetype="pdf")
    rows, header = [], None
    for page in doc:
        for table in page.find_tables().tables:
            for r in table.extract():
                r = [re.sub(r"\s+", " ", c or "").strip() for c in r]
                if r[0].startswith("Processor Number"):
                    header = [re.sub(r"[\s-]", "", h).lower() for h in r]  # 表頭換行會斷字，如 "Performan ce-cores"
                    continue
                if not header or not r[0]:
                    continue
                c = dict(zip(header, r))
                get = lambda prefix: next((v for k, v in c.items() if k.startswith(prefix)), None)  # noqa: E731
                rows.append({
                    "key": intel_key(r[0]), "vendor": "Intel", "official_name": r[0],
                    "launch": get("yearlaunched"),
                    "cores": num(get("#cores")), "p_cores": num(get("#ofperforman")),
                    "e_cores": num(get("#ofefficient")), "lpe_cores": num(get("#oflowpower")),
                    "threads": num(get("#threads")), "boost_ghz": num(get("maxturbo")),
                    "l3_mb": num(get("cache")), "base_power_w": num(get("processorbasepower")),
                    "igpu": gpu_name(get("processorgraphics")),
                    "min_power_w": num(get("minimumassuredpower")), "source_url": url,
                })
    return rows


def main():
    intel = {}
    for url in INTEL_PDFS:
        intel.update({r["key"]: r for r in intel_pdf(url)})
    # 手動查的官網規格頁：補上比較表沒有的型號與欄位
    for r in pd.read_csv(INTEL_MANUAL, dtype={"key": str}).to_dict("records"):
        r = {k: v for k, v in r.items() if pd.notna(v)}
        intel[r["key"]] = {**intel.get(r["key"], {"vendor": "Intel", "official_name": r["key"].upper()}), **r}
    for r in pd.read_csv(INTEL_NPU, dtype={"key": str}).to_dict("records"):
        intel.setdefault(r["key"], {"key": r["key"], "vendor": "Intel", "official_name": r["key"].upper()})
        intel[r["key"]].update(npu_tops=r["npu_tops"], overall_tops=r["overall_tops"])
    amd_rows = amd()
    for r in amd_rows:  # 只有這幾代有 NPU，且要有產品頁才查得到
        if r["codename"] in AMD_NPU_CODENAMES and "/products/processors/laptop/" in r["source_url"]:
            r.update(amd_tops(r["source_url"]))
    df = pd.DataFrame(amd_rows + list(intel.values())).reindex(columns=COLS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"AMD {(df.vendor == 'AMD').sum()} 顆、Intel {(df.vendor == 'Intel').sum()} 顆 → {OUT}")


if __name__ == "__main__":
    main()
