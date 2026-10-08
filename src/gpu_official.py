"""從 NVIDIA、AMD 官方資料整理筆電獨立顯卡規格，存成 data/reference/gpu_official.csv，供 build_db.py 併入 gpus 表。
重點是官方允許的功耗範圍（power_min_w ~ power_max_w）：同一張 GPU 在不同筆電上的實際瓦數由筆電廠決定，
可以拿筆電的 gpu_tgp_w 對照官方範圍，看這台給的瓦數偏高還是偏低。

來源：
- NVIDIA：GeForce 筆電 GPU 比較頁（RTX 50、40 系列一頁，30 系列另一頁）
- AMD：amd.com 顯示卡規格總表（頁面內嵌 JSON），只取筆電用（Board Type = Notebook）
- 其他（如 RTX A2000 筆電版）：手動從官方文件查到後記在 data/reference/gpu_manual.csv
NVIDIA 官方的「GPU Subsystem Power」上限不含 Dynamic Boost；ASUS 標示的瓦數常是「基本 + Dynamic Boost」，
例如 RTX 5070 Ti 官方 60–115W，ROG 標 140W（115W + 25W Dynamic Boost）。"""
import html
import json
import re
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
OUT = Path("data/reference/gpu_official.csv")
MANUAL = Path("data/reference/gpu_manual.csv")
NVIDIA_URLS = [
    "https://www.nvidia.com/en-us/geforce/laptops/compare/",  # RTX 50、40 系列
    "https://www.nvidia.com/en-us/geforce/laptops/compare/30-series/",
]
AMD_URL = "https://www.amd.com/en/products/specifications/graphics.html"
COLS = ["key", "vendor", "official_name", "architecture", "cores", "boost_mhz_min", "boost_mhz_max", "power_min_w",
        "power_max_w", "memory", "bus_width", "ai_tops", "notes", "source_url"]


def gpu_key(name: str) -> str | None:
    """'G eForce RTX 3080 T i Laptop GPU' → 'rtx 3080 ti'；'AMD Radeon™ RX 7600S' → 'rx 7600s'
    （NVIDIA 頁面的字被拆在不同標籤裡，先去掉所有空白再比對）"""
    s = re.sub(r"[\s®™]", "", name).lower()
    m = re.search(r"rtx(a?\d{4})(ti)?", s) or re.search(r"rx(\d{4}[a-z]*)", s)
    if not m:
        return None
    prefix = "rtx" if s[m.start():].startswith("rtx") else "rx"
    return f"{prefix} {m.group(1)}" + (" ti" if len(m.groups()) > 1 and m.group(2) else "")


def nums(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")]


def nvidia(url: str) -> list[dict]:
    soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=60).content.decode("utf-8"), "html.parser")
    rows = []
    for table in soup.find_all("table"):
        cells = [[re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
                 for tr in table.find_all("tr")]
        names = cells[0][1:] if cells else []
        if not names or not all(gpu_key(n) for n in names):  # 跳過系列比較表等其他表格
            continue
        spec = {r[0]: r[1:] for r in cells[1:] if r and r[0]}
        get = lambda label: next((v for k, v in spec.items() if k.startswith(label)), [None] * len(names))  # noqa: E731
        arch = get("NVIDIA Architecture")
        for i, name in enumerate(names):
            clock, power = nums(get("Boost Clock")[i]), nums(get("GPU Subsystem Power")[i])
            rows.append({
                "key": gpu_key(name), "vendor": "NVIDIA", "official_name": re.sub(r"G eForce|T i", lambda m: m[0].replace(" ", ""), name),
                "architecture": arch[i], "cores": max(nums(get("NVIDIA CUDA")[i]), default=None),
                "boost_mhz_min": min(clock, default=None), "boost_mhz_max": max(clock, default=None),
                "power_min_w": min(power, default=None), "power_max_w": max(power, default=None),
                "memory": get("Standard Memory Config")[i], "bus_width": get("Memory Interface Width")[i],
                "ai_tops": max(nums(get("AI TOPS")[i]), default=None), "source_url": url,
            })
    return rows


def amd() -> list[dict]:
    page = requests.get(AMD_URL, headers=HEADERS, timeout=60).content.decode("utf-8")
    items = json.loads(html.unescape(re.search(r'data-json="(\{&#34;[^"]+)"', page).group(1)))["items"]
    rows = []
    for it in items:
        e = {k: v.get("formatValue") for k, v in it["elements"].items()}
        if "Notebook" not in (e.get("boardType") or []) or not gpu_key(e["name"]):
            continue
        sp = nums(" ".join(e.get("streamProcessors") or []))
        rows.append({
            "key": gpu_key(e["name"]), "vendor": "AMD", "official_name": e["name"],
            "cores": max(sp, default=None), "boost_mhz_max": max(nums(e.get("gameFrequency")), default=None),
            "power_max_w": max(nums(e.get("gpuPower")), default=None),
            "memory": f"{e.get('maxMemorySize')} GB {''.join(e.get('memoryType') or [])}" if e.get("maxMemorySize") else None,
            "bus_width": e.get("memoryInterface"), "notes": "AMD 標示的是 Game Frequency，非最高加速時脈",
            "source_url": AMD_URL,
        })
    return rows


def main():
    rows = [r for url in NVIDIA_URLS for r in nvidia(url)] + amd()
    df = pd.concat([pd.DataFrame(rows), pd.read_csv(MANUAL)]).drop_duplicates("key", keep="last").reindex(columns=COLS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"NVIDIA {(df.vendor == 'NVIDIA').sum()} 款、AMD {(df.vendor == 'AMD').sum()} 款 → {OUT}")


if __name__ == "__main__":
    main()
