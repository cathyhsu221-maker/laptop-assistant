"""把 data/raw/asus_models.jsonl 的完整規格整理成可篩選的資料庫：data/asus_laptops.db（SQLite，表 laptops）與同內容的 CSV。
每個型號一列：重要規格保留原文欄位，另外拆出數值／布林欄位（ram_gb、weight_kg、is_oled…）方便依需求篩選。"""
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

RAW = Path("data/raw/asus_models.jsonl")
DB = Path("data/asus_laptops.db")
CSV = Path("data/asus_laptops.csv")

# 我們的欄位 → 官網規格欄位名稱（比對前會先去掉空白與冒號、全形括號轉半形、轉小寫）
# 名稱來自實際抓到的資料：一般機種、ROG、舊頁面三種寫法不同，還有中英混用
FIELDS = {
    "os": ["作業系統", "OperatingSystem"],
    "cpu": ["處理器", "Processor"],
    "npu": ["神經網路處理器", "NeuralProcessor"],
    "gpu": ["顯示晶片", "顯示卡", "Graphics"],
    "display": ["螢幕", "顯示器", "Display"],
    "ram": ["記憶體", "Memory"],
    "storage": ["儲存空間", "資料儲存應用", "Storage"],
    "expansion": ["擴充插槽(包含已使用的)", "擴充插槽(包含已使用)", "ExpansionSlots(includesused)"],
    "ports": ["介面", "I/O連接埠", "I/OPorts"],
    "wireless": ["無線連線", "網路功能", "網路與通訊", "NetworkandCommunication"],
    "camera": ["攝影機", "Camera"],
    "battery": ["電池", "Battery"],
    "weight": ["重量", "Weight"],
    "dimensions": ["尺寸(寬x長x高)", "尺寸(寬x深x高)", "尺寸", "Dimensions(WxDxH)"],
    "military": ["軍規等級", "MilitaryGrade"],
}


def norm_key(k: str) -> str:
    k = k.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s:：]", "", k).lower()


def clean(html: Optional[str]) -> Optional[str]:
    """規格內容夾雜 <br>、</p><p> 等標籤；多個選項之間改用「 / 」分隔"""
    if not html:
        return None
    text = re.sub(r"(?i)</p>\s*<p>|<br\s*/?>", " / ", html)
    text = re.sub(r"<[^>]+>", "", text).replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip(" /,")
    return text or None


def nums(pattern: str, text: Optional[str]) -> list[float]:
    return [float(m) for m in re.findall(pattern, text or "", re.I)]


def most(pattern: str, text: Optional[str]) -> Optional[float]:
    return max(nums(pattern, text), default=None)


def least(pattern: str, text: Optional[str]) -> Optional[float]:
    return min(nums(pattern, text), default=None)


def first(pattern: str, text: Optional[str]) -> Optional[float]:
    return next(iter(nums(pattern, text)), None)


def ram_gb(text: Optional[str]) -> Optional[float]:
    """已安裝的記憶體（不算「最高支援 32GB」）：16GB LPDDR5X、16G DDR4、16GB*2 LPDDR5X（= 32GB）"""
    found = re.findall(r"(\d+)\s*GB?\s*(?:\*\s*(\d+))?\s*(?:LP)?DDR", text or "", re.I)
    return max((float(n) * int(k or 1) for n, k in found), default=None)


def base_model(model: Optional[str], series: str) -> Optional[str]:
    """UX3407QA → UX3407QA；G615LR-0071C290HX-NBL → G615LR；
    沒有型號、或型號欄放的是產品名時，取名稱裡像型號代碼的部分：
    ExpertBook P1 (P1403) → P1403、ExpertBook B5 (B5602, 13th Gen Intel) → B5602、Zenbook Flip 13 BX363 → BX363"""
    if model and " " not in model:
        return model.split("-")[0]
    m = re.search(r"\b([A-Z]{1,3}\d{3,4}[A-Z]*)\b", model or series)
    return m.group(1) if m else None


def derive(t: dict) -> dict:
    """從原文拆出數值／布林欄位。一個型號常列出多種配置（如 16GB / 32GB），容量類取最大；
    重量取第一個數字（可拆式機種後面會再列機身、鍵盤各自的重量）"""
    cpu, gpu, display = t["cpu"] or "", t["gpu"] or "", t["display"] or ""
    storage_gb = [n * 1024 for n in nums(r"(\d+(?:\.\d+)?)\s*TB", t["storage"])] + nums(r"(\d+)\s*GB?\b", t["storage"])
    res = re.findall(r"(\d{3,4})\s*[xX]\s*(\d{3,4})", display)
    return {
        "cpu_brand": next((b for k, b in [("Intel", "Intel"), ("AMD", "AMD"), ("Ryzen", "AMD"),
                                         ("Snapdragon", "Qualcomm"), ("MediaTek", "MediaTek"),
                                         ("NVIDIA", "NVIDIA")] if k in cpu), None),
        "npu_tops": most(r"(\d+)\s*TOPS", f"{t['npu'] or ''} {cpu}"),
        # 獨立顯卡：GeForce RTX 5060、RTX PRO 2000、Radeon™ RX 7600S；RTX Spark 是 CPU/GPU 整合晶片，不算
        "has_dgpu": bool(re.search(r"GeForce|RTX\W*(?:PRO\s*)?A?\d|Radeon\W*RX", gpu, re.I)),
        "vram_gb": most(r"(\d+)\s*GB\s*GDDR", gpu),
        "ram_gb": ram_gb(t["ram"]),
        "ram_upgradeable": bool(re.search(r"SO-?DIMM", f"{t['ram'] or ''} {t['expansion'] or ''}", re.I)),
        "storage_gb": max(storage_gb, default=None),
        "screen_inch": least(r"(\d{2}(?:\.\d)?)\s*-?\s*(?:吋|inch|\"|”)", display),
        "resolution": "x".join(max(res, key=lambda r: int(r[0]))) if res else None,
        "is_oled": "OLED" in display,
        "refresh_hz": most(r"(\d{2,3})\s*Hz", display),  # 舊款商務機多半沒寫，空值通常就是 60Hz
        "is_touch": bool(re.search(r"(?<!非)觸控螢幕|(?<!non-)touch\s*screen", display, re.I)),
        "battery_wh": most(r"(\d+(?:\.\d+)?)\s*Wh", t["battery"]),
        "weight_kg": first(r"(\d+(?:\.\d+)?)\s*(?:kg|公斤)", t["weight"]),
        "has_thunderbolt": "thunderbolt" in (t["ports"] or "").lower(),
        "price": float(p) if (p := t.pop("sort_price")) else None,
    }


def build_row(r: dict) -> dict:
    specs = {norm_key(k): v for k, v in r["specs"].items()}
    texts = {f: clean(next((specs[norm_key(n)] for n in names if specs.get(norm_key(n))), None))
             for f, names in FIELDS.items()}
    series = clean(r["series"])
    texts["sort_price"] = r["sort_price"]
    return {
        "base_model": base_model(r["model"], series),
        "model": r["model"],
        "series": series,
        "source": r["source"],
        "category": r["category"],
        **derive(texts),
        **texts,
        "has_spec": bool(r["specs"]),  # False：舊頁面只有整段 HTML，規格欄位都是空的
        "url": r["url"],
        "online_date": r["online_date"],
        "fetched_at": r["fetched_at"],
    }


def main():
    rows = [build_row(json.loads(l)) for l in RAW.open(encoding="utf-8")]
    df = pd.DataFrame(rows)
    with sqlite3.connect(DB) as con:
        df.to_sql("laptops", con, if_exists="replace", index=False)
    df.to_csv(CSV, index=False, encoding="utf-8-sig")  # utf-8-sig 讓 Excel 正確顯示中文
    print(f"{len(df)} 個型號 → {DB}、{CSV}")
    print("\n各欄位缺值數：")
    print(df.isna().sum()[lambda s: s > 0].to_string())


if __name__ == "__main__":
    main()
