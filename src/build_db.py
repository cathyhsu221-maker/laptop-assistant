"""把 data/raw/asus_models.jsonl 的完整規格整理成可篩選的資料庫：data/asus_laptops.db（SQLite，表 laptops）與同內容的 CSV。
每個料號一列（level="sku"）；官網沒有料號資料的型號一列（level="model"，CPU、RAM 等列出所有選項）。
重要規格保留原文欄位，另外拆出數值／布林欄位（ram_gb、weight_kg、is_oled…）方便依需求篩選。"""
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

RAW = Path("data/raw/asus_models.jsonl")
DB = Path("data/asus_laptops.db")
CSV = Path("data/asus_laptops.csv")
CPU_CSV = Path("data/asus_cpus.csv")
CPU_OFFICIAL = Path("data/reference/cpu_official.csv")  # 由 cpu_official.py 產生
GPU_CSV = Path("data/asus_gpus.csv")
# 通路售價：(表名, 原始資料, CSV, 商品編號欄位)；原始資料分別由 pchome_prices.py、momo_prices.py 產生
STORES = {
    "pchome": (Path("data/raw/pchome_prices.jsonl"), Path("data/pchome_prices.csv"), "pchome_id"),
    "momo": (Path("data/raw/momo_prices.jsonl"), Path("data/momo_prices.csv"), "momo_id"),
}
GPU_OFFICIAL = Path("data/reference/gpu_official.csv")  # 由 gpu_official.py 產生
GPU_COLS = ["gpu_architecture", "gpu_cores", "gpu_official_boost_mhz_min", "gpu_official_boost_mhz_max",
            "gpu_power_min_w", "gpu_power_max_w", "gpu_official_memory", "gpu_bus_width", "gpu_ai_tops", "gpu_official_url"]
CPU_COLS = ["cpu_brand", "cpu_series", "cpu_number", "cpu_codename", "cpu_igpu", "cpu_cores", "cpu_p_cores", "cpu_e_cores", "cpu_lpe_cores",
            "cpu_threads", "cpu_base_ghz", "cpu_boost_ghz", "cpu_cache_mb", "cpu_l2_mb", "cpu_l3_mb", "cpu_npu_tops", "cpu_overall_tops",
            "cpu_base_power_w", "cpu_max_power_w", "cpu_min_power_w", "cpu_official_url"]

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
    "wireless": ["無線連線", "網路功能", "網路與通訊", "區域網路", "NetworkandCommunication"],
    "camera": ["攝影機", "Camera"],
    "battery": ["電池", "Battery"],
    "weight": ["重量", "Weight"],
    "dimensions": ["尺寸(寬x長x高)", "尺寸(寬x深x高)", "尺寸", "Dimensions(WxDxH)"],
    "military": ["軍規等級", "MilitaryGrade"],
    # 以下欄位選購時較少看，但同型號的料號常常只差在這幾項，要有它們每個料號的規格才分得開
    "color": ["材質/顏色", "Color"],
    "keyboard": ["鍵盤及觸控板", "鍵盤和觸控板", "鍵盤與觸控板", "Keyboard&Touchpad"],
    "power": ["電源", "PowerSupply"],
    "in_box": ["包裝盒內容", "盒裝內附", "IncludedintheBox", "IncludedintheBox(Optional)"],
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
    """抓出所有數字；pattern 有多個群組（如「A(數字)|(數字)B」兩種寫法）時取有值的那個"""
    found = re.findall(pattern, text or "", re.I)
    return [float(next((g for g in m if g), 0)) if isinstance(m, tuple) else float(m) for m in found]


def options(name: str, values: list[float]) -> dict:
    """一個型號常列出多種配置：name 欄位列出所有選項（如 "16/32/64"），name_max 是最大值，方便用數字篩選"""
    vals = sorted(set(values))
    text = "/".join(f"{v:g}" for v in vals) or None
    return {name: text, f"{name}_max": max(vals, default=None)}


def least(pattern: str, text: Optional[str]) -> Optional[float]:
    return min(nums(pattern, text), default=None)


def first(pattern: str, text: Optional[str]) -> Optional[float]:
    return next(iter(nums(pattern, text)), None)


def ram_gb(text: Optional[str]) -> list[float]:
    """已安裝的記憶體（不算「最高支援 32GB」）：16GB LPDDR5X、16G DDR4、16GB*2 LPDDR5X（= 32GB）"""
    found = re.findall(r"(\d+)\s*GB?\s*(?:\*\s*(\d+))?\s*(?:LP)?DDR", text or "", re.I)
    return [float(n) * int(k or 1) for n, k in found]


# 處理器型號：從原文抽出各品牌的系列與型號編號，例如
# 「Intel® Core™ Ultra 7 Processor 356H 1.9 GHz (...)」→ 系列 Core Ultra 7、編號 356H
_P = r"\W*(?:vPro\W*)?(?:Processor|處理器)?\s*"  # 型號中間可能夾著 ™、vPro®、Processor／處理器
CPU_MODELS = [  # (pattern, 系列格式, 編號格式)
    (rf"Core\W*Ultra\s*(X?\d){_P}(\d{{3}}[A-Z]{{0,2}})(\s*Plus)?", "Core Ultra {0}", "{1}{2}"),  # Core Ultra 9 290HX Plus
    (rf"Core\W*(i\d)[\s-]*{_P}(N?\d{{3,5}}[A-Z]{{0,2}}\d?)", "Core {0}", "{1}"),                # Core i7 13620H、Core i3 N305
    (rf"Core\W*(\d){_P}(\d{{3}}[A-Z]?)\b", "Core {0}", "{1}"),                                  # Core 5 120U、Core 7 350
    (r"(Celeron|Pentium\W*(?:Gold|Silver)?)\W*(N?\d{4})", "{0}", "{1}"),                       # Celeron N4020、Pentium Gold 8505
    (r"Intel\W*Processor\s*(N\d{3})", "Intel Processor", "{0}"),                               # Intel Processor N100
    (r"Ryzen\W*((?:AI\s*)?(?:MAX\+?|\d)(?:\s*HX)?)\s*(?:Pro\s*)?(\d{3,4}[A-Z0-9]*)", "Ryzen {0}", "{1}"),  # Ryzen AI 9 HX 370
    (r"Snapdragon\W*(X2?(?:\s*Elite|\s*Plus)?(?:\s*Extreme)?)[^/]{0,20}?(X\d[A-Z]?)[\s-]*(\d{2})[\s-]*(\d{3})",
     "Snapdragon {0}", "{1}-{2}-{3}"),                                                        # Snapdragon X Elite X1E-78-100
    (r"MediaTek\W*Kompanio\s*(\d+)", "Kompanio", "{0}"),                                      # Kompanio 540
    (r"RTX\s*Spark\s*(\w+)", "RTX Spark", "{0}"),                                             # RTX Spark N1X
]


def _num(pattern: str, text: str, pick=max) -> Optional[float]:
    vals = [float(v) for v in re.findall(pattern, text, re.I)]
    return pick(vals) if vals else None


def cpu_detail(seg: str) -> dict:
    """從單一處理器的原文拆出規格，例如
    「Core™ Ultra 5 處理器 226V 16GB 1.6 GHz (8MB 快取, 最高 4.5 GHz, 8 核心, 8 執行緒); Intel® AI Boost NPU 最高 40 TOPS」
    → 時脈 1.6、快取 8、最高 4.5、8 核心、8 執行緒、NPU 40。16GB 是封裝在處理器上的記憶體，等同整機 RAM，已在 ram_gb"""
    head = seg.split("(")[0].split("（")[0]  # 括號前才是基本時脈，括號內是最高時脈
    pe = re.search(r"(\d+)\s*P\s*\+\s*(\d+)\s*E", seg)  # 4P+8E cores
    return {
        "cpu_base_ghz": _num(r"(\d+(?:\.\d+)?)(?:\s*-\s*[\d.]+)?\s*G?Hz", head, pick=lambda v: v[0]),
        "cpu_boost_ghz": _num(r"(?:最高|up to)[^\d,()]{0,10}(\d+(?:\.\d+)?)\s*GHz", seg),
        "cpu_cache_mb": _num(r"(\d+)\s*MB?\s*(?:L3\s*)?(?:快取|cache)", seg),
        "cpu_cores": int(pe[1]) + int(pe[2]) if pe else _num(r"(\d+)\s*-?\s*(?:核心|cores?)(?!\s*GPU)", seg, pick=lambda v: v[0]),
        "cpu_threads": _num(r"(\d+)\s*-?\s*(?:執行緒|threads?)", seg, pick=lambda v: v[0]),
        "cpu_npu_tops": _num(r"(\d+)\s*TOPS", seg),
    }


def parse_cpus(text: Optional[str]) -> list[dict]:
    """找出原文中每一顆處理器（依原文順序、去重），每顆附上自己那段文字拆出的規格"""
    text = text or ""
    found = []
    for pattern, series_fmt, number_fmt in CPU_MODELS:
        for m in re.finditer(pattern, text, re.I):
            groups = [re.sub(r"[®™]", "", g or "") for g in m.groups()]
            series, number = (re.sub(r"\s+", " ", f.format(*groups)).strip() for f in (series_fmt, number_fmt))
            found.append((m.start(), series, number))
    found.sort()
    cpus = {}
    for i, (start, series, number) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else len(text)
        name = f"{series}-{number}" if re.fullmatch(r"Core i\d", series) else f"{series} {number}"  # Core i7-13620H
        if name not in cpus:
            cpus[name] = {"cpu_model": name, "cpu_series": series, "cpu_number": number, **cpu_detail(text[start:end])}
    return list(cpus.values())


# 獨立顯卡型號，例如「NVIDIA® GeForce RTX™ 5070 Ti Laptop GPU」→ GeForce RTX 5070 Ti（key：rtx 5070 ti）
GPU_MODELS = [  # (pattern, 名稱格式, key 格式)
    (r"GeForce\W*RTX\W*(\d{4})(\s*Ti)?", "GeForce RTX {0}{1}", "rtx {0}{1}"),
    (r"RTX\W*(A\d{4})", "RTX {0}", "rtx {0}"),                                   # Quadro RTX A2000
    (r"Radeon\W*RX\W*(\d{4}[A-Z]*)(\s*XT)?", "Radeon RX {0}{1}", "rx {0}{1}"),  # Radeon RX 7600S
]


def parse_gpus(text: Optional[str]) -> list[tuple[str, str]]:
    """找出原文中的獨立顯卡（依原文順序、去重），回傳 (名稱, key)"""
    found = []
    for pattern, name_fmt, key_fmt in GPU_MODELS:
        for m in re.finditer(pattern, text or "", re.I):
            g = [x or "" for x in m.groups()]
            name = re.sub(r"\s+", " ", name_fmt.format(*g)).strip()
            key = re.sub(r"\s+", " ", key_fmt.format(*g)).strip().lower().replace(" xt", "xt")
            found.append((m.start(), name, key))
    return list(dict.fromkeys((n, k) for _, n, k in sorted(found)))


def gpu_power(text: Optional[str]) -> dict:
    """筆電給獨顯的功耗（TGP）。ASUS 的寫法有好幾種，常見的是「基本 + Dynamic Boost」：
    「115W+25W Dynamic Boost」、「85W(70+15)」→ 總計 140 / 85、基本 115 / 70；
    「60W (70W with Dynamic Boost)」→ 總計 70、基本 60；「up to 95W(SmartShift)」→ 總計 95。
    有 Turbo / Manual 等多種模式時取最高的那組"""
    text = text or ""
    cands = [(int(b) + int(d), int(b)) for b, d in re.findall(r"(\d+)\s*W?\s*\+\s*(\d+)(?!\s*MHz)\s*W?", text)]
    cands += [(int(t), int(b)) for b, t in re.findall(r"(\d+)\s*W\s*\(\s*(\d+)\s*W\s*with Dynamic Boost", text, re.I)]
    cands += [(int(w), None) for w in re.findall(r"(\d+)\s*W\b", text)]
    total, base = max(cands, key=lambda c: (c[0], c[1] is not None), default=(None, None))
    return {"gpu_tgp_w": total, "gpu_tgp_base_w": base,
            "gpu_boost_mhz": max((int(m) for m in re.findall(r"(\d{3,4})\s*MHz", text, re.I)), default=None)}


def most(pattern: str, text: Optional[str]) -> Optional[float]:
    return max(nums(pattern, text), default=None)


def ram_slots(ram: Optional[str], expansion: Optional[str]) -> int:
    """SO-DIMM 插槽數：擴充插槽欄寫「2x DDR5 SO-DIMM slots」「1x DDR5 SO-DIMM 插槽」；
    沒寫數量但記憶體欄有 SO-DIMM 時算 1 個"""
    n = nums(r"(\d+)\s*x\s*(?:DDR\d\s*)?SO-?DIMM", expansion)
    if n:
        return int(max(n))
    return 1 if re.search(r"SO-?DIMM", f"{ram or ''} {expansion or ''}", re.I) else 0


def base_model(model: Optional[str], series: str) -> Optional[str]:
    """UX3407QA → UX3407QA；G615LR-0071C290HX-NBL → G615LR；
    沒有型號、或型號欄放的是產品名時，取名稱裡像型號代碼的部分：
    ExpertBook P1 (P1403) → P1403、ExpertBook B5 (B5602, 13th Gen Intel) → B5602、Zenbook Flip 13 BX363 → BX363"""
    if model and " " not in model:
        return model.split("-")[0]
    m = re.search(r"\b([A-Z]{1,3}\d{3,4}[A-Z]*)\b", model or series)
    return m.group(1) if m else None


def found(pairs: list[tuple[str, str]], text: Optional[str]) -> Optional[str]:
    """依序找出原文出現的選項（用「/」分隔），例如作業系統、面板種類"""
    hits = [label for pattern, label in pairs if re.search(pattern, text or "", re.I)]
    return "/".join(dict.fromkeys(hits)) or None


def has(pattern: str, text: Optional[str]) -> bool:
    return bool(re.search(pattern, text or "", re.I))


def port_counts(ports: Optional[str]) -> dict:
    """「1x USB 3.2 Gen 2 Type-A / 2x Thunderbolt™ 4 支援顯示/供電 / 1x HDMI 2.1 FRL」→ 各類接孔數量"""
    usb_c = usb_a = 0
    for n, item in re.findall(r"(\d+)\s*x\s*([^/,，]*)", ports or "", re.I):
        if re.search(r"Type-?C|Thunderbolt|USB\s*4", item, re.I):
            usb_c += int(n)
        elif re.search(r"Type-?A|USB\s*2\.0", item, re.I):
            usb_a += int(n)
    hdmi = re.findall(r"HDMI\s*(\d\.\d)", ports or "")
    return {
        "usb_c_ports": usb_c or None, "usb_a_ports": usb_a if ports else None,
        "has_usb4": has(r"USB\s*4", ports),
        "hdmi_version": max(hdmi, key=float) if hdmi else ("有" if has("HDMI", ports) else None),
        "has_rj45": has(r"RJ-?45|LAN|Ethernet", ports),
        "card_reader": found([(r"SD Express", "SD Express"), (r"micro\s*SD", "microSD"),
                              (r"(?<!micro)(?<!micro )SD(?! Express)|讀卡機|card reader", "SD")], ports),
        "has_audio_jack": has(r"3\.5\s*mm|音訊插孔|Audio Jack", ports),
    }


def extra(t: dict) -> dict:
    """把其餘規格原文拆成欄位，讓 os 之後的原文欄位可以刪除"""
    display, ports = t["display"], t["ports"]
    dims = re.search(r"([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)(?:\s*~\s*([\d.]+))?\s*cm", t["dimensions"] or "", re.I)
    # 「Windows 11 Home - ASUS 推薦商務用 Windows 11 Pro」後半是廣告詞，不是可選的作業系統
    os_text = re.sub(r"ASUS\s*(?:推薦商務用|recommends)\s*Windows\s*1\d\s*Pro(?:\s*for business)?", "", t["os"] or "", flags=re.I)
    sdr_nits = nums(r"(\d{3,4})\s*(?:尼特|nits)(?!\s*HDR)(?![^,，]*峰值)", display)
    return {
        "os": found([(r"Windows 11 Pro Education", "Windows 11 Pro Education"),
                     (r"Windows 11 Pro(?! Education)", "Windows 11 Pro"),
                     (r"Windows 11 Home\s*\(?S\s*模式|Windows 11 Home in S mode", "Windows 11 Home S"),
                     (r"Windows 11 Home(?!\s*\(?S\s*模式)", "Windows 11 Home"),
                     (r"Windows 10 Pro", "Windows 10 Pro"), (r"Windows 10 Home", "Windows 10 Home"),
                     (r"Chrome\s*OS", "ChromeOS"), (r"Linux|Ubuntu", "Linux"), (r"FreeDOS|without OS|無作業系統", "無")],
                    os_text),
        # 螢幕
        "panel_type": found([(r"OLED", "OLED"), (r"Mini\s*LED", "Mini LED"), (r"IPS", "IPS"), (r"\bTN\b", "TN")], display),
        "aspect_ratio": found([(r"16\s*:\s*10", "16:10"), (r"16\s*:\s*9", "16:9"), (r"3\s*:\s*2", "3:2")], display),
        "brightness_nits": max(sdr_nits, default=None),  # 一般亮度，不含 HDR 峰值亮度
        "hdr_peak_nits": most(r"(\d{3,4})\s*(?:尼特|nits)\s*HDR", display),
        "dci_p3_pct": most(r"DCI-?P3[^\d,，]{0,10}(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*DCI-?P3", display),
        "srgb_pct": most(r"sRGB[^\d,，]{0,6}(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*sRGB", display),
        "ntsc_pct": most(r"NTSC[^\d,，]{0,6}(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*NTSC", display),
        "display_finish": found([(r"鏡面|glossy", "鏡面"), (r"霧面|防眩光|anti-?glare|抗反光|anti-?reflect", "霧面")], display),
        "has_gsync": has(r"G-?SYNC", f"{display} {t['gpu']}"),
        "has_mux": has(r"MUX|Advanced Optimus", f"{display} {t['gpu']}"),
        "stylus_support": has(r"觸控筆|stylus|\bpen\b", display),
        # 記憶體、儲存
        "ram_type": found([(r"LPDDR5X", "LPDDR5X"), (r"LPDDR5(?!X)", "LPDDR5"), (r"LPDDR4X", "LPDDR4X"),
                           (r"(?<!LP)DDR5", "DDR5"), (r"(?<!LP)DDR4", "DDR4")], t["ram"]),
        "ram_speed_mts": most(r"DDR\dX?[-\s]+(\d{4})", t["ram"]),
        "storage_interface": found([(r"PCIe\W*5\.0", "PCIe 5.0"), (r"PCIe\W*4\.0", "PCIe 4.0"), (r"PCIe\W*3\.0", "PCIe 3.0"),
                                    (r"UFS", "UFS"), (r"eMMC", "eMMC"), (r"HDD", "HDD")], t["storage"]),
        "m2_slots": int(sum(nums(r"(\d+)\s*x\s*M\.2", t["expansion"]))) or None,
        "has_25_bay": has(r"2\.5\s*(?:吋|inch|\")", t["expansion"]),
        # 接孔、無線
        **port_counts(ports),
        "wifi": found([(r"Wi-?Fi\s*7", "Wi-Fi 7"), (r"Wi-?Fi\s*6E", "Wi-Fi 6E"), (r"Wi-?Fi\s*6(?!E)", "Wi-Fi 6"),
                       (r"Wi-?Fi\s*5|802\.11ac", "Wi-Fi 5")], t["wireless"]),
        "bluetooth": most(r"Bluetooth\W*(?:藍牙\s*)?(\d\.\d)", t["wireless"]),
        # 視訊鏡頭
        "camera": found([(r"5\.?0?\s*M\b|5\s*MP", "5MP"), (r"FHD|1080\s*p", "1080p"), (r"(?<!F)HD\b|720\s*p", "720p"),
                         (r"VGA", "VGA")], t["camera"]),
        "camera_ir": has(r"紅外線|\bIR\b|Windows Hello", t["camera"]),
        "camera_shutter": has(r"遮罩|shutter|privacy", t["camera"]),
        # 機身
        "width_cm": float(dims[1]) if dims else None,
        "depth_cm": float(dims[2]) if dims else None,
        "thickness_min_cm": float(dims[3]) if dims else None,
        "thickness_max_cm": float(dims[4] or dims[3]) if dims else None,
        "mil_std": found([(r"810H", "MIL-STD 810H"), (r"810G", "MIL-STD 810G")], t["military"]),
        # 鍵盤
        "kb_backlight": ("Per-key RGB" if has(r"per-?key|單鍵", t["keyboard"]) else "RGB" if has("RGB", t["keyboard"])
                         else "有" if has(r"背光|backlit", t["keyboard"]) else "無" if t["keyboard"] else None),
        "kb_numpad": has(r"數字鍵|number\s*key|numeric|numpad(?!.*NumberPad)", t["keyboard"]),
        "touchpad_numberpad": has(r"NumberPad", t["keyboard"]),
        "kb_travel_mm": most(r"(\d\.\d+)\s*mm", t["keyboard"]),
        "kb_spill_resistant": has(r"防潑水|spill", t["keyboard"]),
        "copilot_key": has(r"Copilot", t["keyboard"]),
        # 電源、隨附配件
        "usb_c_charging": has(r"TYPE-?C", t["power"]),
        "bundled_mouse": has(r"滑鼠|mouse", t["in_box"]),
        "bundled_bag": has(r"背包|攜帶包|保護包|保護套|sleeve|backpack|bag", t["in_box"]),
        "bundled_stylus": has(r"觸控筆|stylus|pen", t["in_box"]),
        "bundled_hdd_kit": has(r"HDD housing|硬碟(?:擴充|套件)", t["in_box"]),  # 附 2.5 吋硬碟擴充套件
        "color": t["color"],  # 顏色名稱本身就是乾淨的值，直接保留
    }


def derive(t: dict, level: str) -> dict:
    """從原文拆出數值／布林欄位。一個型號常列出多種配置（如 16GB / 32GB / 64GB），
    這類欄位列出所有選項，另附 _max 欄位供數字篩選（見 options）；
    重量取第一個數字（可拆式機種後面會再列機身、鍵盤各自的重量）"""
    cpu, gpu, display = t["cpu"] or "", t["gpu"] or "", t["display"] or ""
    storage_gb = [n * 1024 for n in nums(r"(\d+(?:\.\d+)?)\s*TB", t["storage"])] + nums(r"(\d+)\s*GB?\b", t["storage"])
    res = sorted(set(re.findall(r"(\d{3,4})\s*[xX]\s*(\d{3,4})", display)), key=lambda r: int(r[0]) * int(r[1]))
    return {
        # 處理器只記型號（對照 cpus 表查固定規格）；型號層級有多顆可選時用「/」分隔
        "cpu_model": "/".join(c["cpu_model"] for c in parse_cpus(cpu)) or None,
        # 獨立顯卡：GeForce RTX 5060、RTX PRO 2000、Radeon™ RX 7600S；RTX Spark 是 CPU/GPU 整合晶片，不算
        "has_dgpu": bool(re.search(r"GeForce|RTX\W*(?:PRO\s*)?A?\d|Radeon\W*RX", gpu, re.I)),
        # 獨顯只記型號（對照 gpus 表查固定規格），加上 ASUS 為這台設定的瓦數與時脈
        "gpu_model": "/".join(n for n, _ in parse_gpus(gpu)) or None,
        **gpu_power(gpu),
        **options("vram_gb", nums(r"(\d+)\s*GB\s*GDDR", gpu)),
        # 料號的記憶體若列了多條，是同時安裝（如 8GB 內建 + 16GB SO-DIMM = 24GB）；型號層級則是可選配置
        **options("ram_gb", [sum(ram_gb(t["ram"]))] if level == "sku" and ram_gb(t["ram"]) else ram_gb(t["ram"])),
        # 記憶體能否後續加裝：有 SO-DIMM 插槽才能自己換或加；LPDDR／on board／內建 是焊死在主機板上的
        "ram_upgradeable": bool(re.search(r"SO-?DIMM", f"{t['ram'] or ''} {t['expansion'] or ''}", re.I)),
        "ram_slots": ram_slots(t["ram"], t["expansion"]),
        "ram_soldered": bool(re.search(r"LPDDR|on\s*board|內建|on\s*package", t["ram"] or "", re.I)),
        # 官方標示的最高支援容量（「最高支援：32GB」「最大容量64GB」「Memory Max Up to: 40GB」）。
        # 有插槽的機種代表可擴充到多少；全焊死的機種則只是同型號最高配置，不能自己加
        "ram_max_gb": most(r"(?:最高支援|最大容量|Max\s*Up\s*to|最高)\s*[:：]?\s*/?\s*(\d+)\s*GB", t["ram"]),
        **options("storage_gb", storage_gb),
        "screen_inch": least(r"(\d{2}(?:\.\d)?)\s*-?\s*(?:吋|inch|\"|”)", display),
        "resolution": "/".join("x".join(r) for r in res) or None,
        "is_oled": "OLED" in display,
        **options("refresh_hz", nums(r"(\d{2,3})\s*Hz", display)),  # 舊款商務機多半沒寫，空值通常就是 60Hz
        "is_touch": bool(re.search(r"(?<!非)觸控螢幕|(?<!non-)touch\s*screen", display, re.I)),
        **options("battery_wh", nums(r"(\d+(?:\.\d+)?)\s*Wh", t["battery"])),
        "weight_kg": first(r"(\d+(?:\.\d+)?)\s*(?:kg|公斤)", t["weight"]),
        "has_thunderbolt": "thunderbolt" in (t["ports"] or "").lower(),
        # 變壓器瓦數：「65W AC 變壓器」「100W Ultra mini AC Adapter」；只取緊接著 adapter／變壓器的數字，
        # 避免抓到「TYPE-C 傳輸線：240W」這類線材規格。可當成整機功耗等級的指標
        **options("adapter_w", nums(r"(\d{2,3})\s*W\b(?=[^,，;/]{0,25}?(?:adapter|變壓器))", t["power"])),
    }


def cpu_power(specs: dict) -> Optional[float]:
    """ASUS 為這台設定的 CPU 瓦數。官網規格極少寫，目前只在 Note 欄位看過
    「Max combined system power … 135W (35W CPU + 100W GPU)」這種寫法，所以搜尋所有欄位"""
    text = " ".join(clean(v) or "" for v in specs.values())
    return max(nums(r"(\d+)\s*W\s*CPU", text) + nums(r"CPU\s*[:：]?\s*(\d+)\s*W", text), default=None)


def build_row(r: dict) -> dict:
    specs = {norm_key(k): v for k, v in r["specs"].items()}
    texts = {f: clean(next((specs[norm_key(n)] for n in names if specs.get(norm_key(n))), None))
             for f, names in FIELDS.items()}
    series = clean(r["series"])
    return {
        "part_no": r.get("part_no"),
        "sales_model": r.get("sales_model"),
        "base_model": base_model(r.get("model") or r.get("sales_model"), series),
        "level": r["level"],
        "series": series,
        "source": r["source"],
        "category": "ROG" if r["source"] == "rog" else r["category"],  # ROG 各系列（Strix、Zephyrus…）統一歸為 ROG
        "price": float(r["price"]) if r.get("price") else None,  # ASUS Store 售價，只有部分料號有
        **derive(texts, r["level"]),
        "cpu_power_w": cpu_power(r["specs"]),
        **extra(texts),
        **{f"text_{k}": v for k, v in texts.items()},  # 原文只用來檢查規格唯一性，寫入資料庫前刪除
        "has_spec": bool(r["specs"]),  # False：舊頁面只有整段 HTML，規格欄位都是空的
        "url": r["url"],
        "online_date": r["online_date"],
        "fetched_at": r["fetched_at"],
    }


def official_key(series: str, number: str, model: str) -> str:
    """對應 cpu_official.csv 的 key：AMD 用完整名稱（ryzen ai 9 hx 370）、Intel 用處理器編號（226v、i7-13620h）"""
    if series.startswith("Ryzen"):
        return model.lower()
    if re.fullmatch(r"Core i\d", series):
        return f"{series.split()[1]}-{number}".lower()
    return number.lower()


def igpu_from_text(gpu: Optional[str]) -> Optional[str]:
    """ASUS 顯示晶片原文中的內顯名稱（只在官方資料沒有時使用，如 Snapdragon 的 Adreno）：
    取第一段不是獨顯的描述，例如「Qualcomm® Adreno™ 顯示晶片」→ Qualcomm Adreno"""
    for part in re.split(r"\s*/\s*|,\s*", gpu or ""):
        if part and not re.search(r"GeForce|RTX\W*(?:PRO\s*)?A?\d|Radeon\W*RX|\d+\s*GB", part, re.I):
            name = re.sub(r"[®™]|顯示晶片|\*.*", "", part).strip()
            if name:
                return re.sub(r"\s+", " ", name)
    return None


def build_cpus(cpu_texts: list[str]) -> pd.DataFrame:
    """處理器規格表：每顆處理器一列。
    先從 ASUS 原文拆出規格（同一顆處理器在不同產品頁寫法偶有出入，取最常見的值），
    再用 Intel、AMD 官方規格覆蓋（官方有值就以官方為準），並補上大小核數量、L2/L3、功耗。
    cpu_cache_mb 保留 ASUS 標示的快取（Intel 多為 L3、AMD 多為 L2+L3），官方分層數字在 cpu_l2_mb、cpu_l3_mb"""
    asus_cols = ["cpu_series", "cpu_number", "cpu_base_ghz", "cpu_boost_ghz", "cpu_cache_mb", "cpu_cores",
                 "cpu_threads", "cpu_npu_tops"]
    cpus = pd.DataFrame([c for t in cpu_texts for c in parse_cpus(t)])
    mode = lambda s: s.mode().iloc[0] if s.notna().any() else None  # noqa: E731
    cpus = cpus.groupby("cpu_model", as_index=False).agg({c: mode for c in asus_cols})
    brands = [("Core", "Intel"), ("Celeron", "Intel"), ("Pentium", "Intel"), ("Intel", "Intel"), ("Ryzen", "AMD"),
              ("Snapdragon", "Qualcomm"), ("Kompanio", "MediaTek"), ("RTX Spark", "NVIDIA")]
    cpus["cpu_brand"] = [next((b for k, b in brands if s.startswith(k)), None) for s in cpus.cpu_series]
    if CPU_OFFICIAL.exists():
        official = pd.read_csv(CPU_OFFICIAL, dtype={"key": str}).drop(columns=["vendor", "official_name", "launch", "notes"])
        official = official.rename(columns={c: f"cpu_{c}" for c in official.columns if c != "key"})
        official = official.rename(columns={"cpu_source_url": "cpu_official_url"})
        cpus["key"] = [official_key(*r) for r in cpus[["cpu_series", "cpu_number", "cpu_model"]].itertuples(index=False)]
        cpus = cpus.merge(official, on="key", how="left", suffixes=("", "_official")).drop(columns="key")
        # 官方有值就以官方為準。NPU 算力特別需要：ASUS 有時寫 NPU、有時寫平台總和（如 8840HS 寫 38 TOPS，官方 NPU 是 16）
        for c in ["cpu_cores", "cpu_threads", "cpu_base_ghz", "cpu_boost_ghz", "cpu_npu_tops"]:
            cpus[c] = cpus.pop(f"{c}_official").combine_first(cpus[c])
    return cpus.reindex(columns=["cpu_model", *CPU_COLS])


def build_gpus(gpu_texts: list[str]) -> pd.DataFrame:
    """獨立顯卡規格表：每款 GPU 一列，附上 NVIDIA、AMD 官方規格（含官方允許的功耗範圍）"""
    gpus = pd.DataFrame(list(dict.fromkeys(g for t in gpu_texts for g in parse_gpus(t))), columns=["gpu_model", "key"])
    if GPU_OFFICIAL.exists():
        official = pd.read_csv(GPU_OFFICIAL).drop(columns=["vendor", "official_name", "notes"])
        official.columns = ["key"] + [f"gpu_{c}" for c in official.columns[1:]]
        official = official.rename(columns={
            "gpu_boost_mhz_min": "gpu_official_boost_mhz_min", "gpu_boost_mhz_max": "gpu_official_boost_mhz_max",
            "gpu_memory": "gpu_official_memory", "gpu_source_url": "gpu_official_url"})
        gpus = gpus.merge(official, on="key", how="left")
    return gpus.drop(columns="key").reindex(columns=["gpu_model", *GPU_COLS])


def load_store(store: str) -> pd.DataFrame:
    """通路商品清單：每個商品一列。沒找到商品的基礎型號只是續跑標記，不入表"""
    raw, _, id_col = STORES[store]
    if not raw.exists():
        return pd.DataFrame()
    rows = [json.loads(l) for l in raw.open(encoding="utf-8")]
    return pd.DataFrame([r for r in rows if r.get(id_col)]).drop_duplicates(id_col)


def store_summary(df: pd.DataFrame, store: str, items: pd.DataFrame) -> pd.DataFrame:
    """laptops 的通路最低價：只算全新、原廠配置、單機（排除特仕、福利品、組合包）的商品。
    料號層級對銷售型號（momo 一個商品可能對到多個只差顏色的料號，以「/」分隔，各料號都算）；
    型號層級沒有銷售型號，對基礎型號（同型號任一配置的最低價）"""
    price_col, n_col = f"{store}_price_min", f"{store}_listings"
    if items.empty:
        return df.assign(**{price_col: None, n_col: 0})
    ok = items[~items.is_custom & ~items.is_refurb & ~items.get("is_bundle", pd.Series(False, index=items.index))]
    per_sku = ok.dropna(subset=["sales_model"]).assign(sales_model=lambda x: x.sales_model.str.split("/")).explode("sales_model")
    by_sales = per_sku.groupby("sales_model").price.agg(["min", "size"])
    by_base = ok.groupby("base_model").price.agg(["min", "size"])
    sku = df.level == "sku"
    df[price_col] = df.sales_model.map(by_sales["min"]).where(sku, df.base_model.map(by_base["min"]))
    df[n_col] = df.sales_model.map(by_sales["size"]).where(sku, df.base_model.map(by_base["size"])).fillna(0).astype(int)
    return df


def main():
    raw = [json.loads(l) for l in RAW.open(encoding="utf-8")]
    df = pd.DataFrame([build_row(r) for r in raw])
    # 處理器、獨顯的固定規格各自成表，laptops 只留型號（cpu_model、gpu_model）供對照，
    # 以及 ASUS 為這台機器設定的部分（cpu_power_w、gpu_tgp_w、gpu_tgp_base_w、gpu_boost_mhz）
    # NPU 欄位接在處理器原文後面一起解析（Snapdragon 的 NPU 算力只寫在 NPU 欄位）
    cpus = build_cpus((df.text_cpu + " ; " + df.text_npu.fillna("")).dropna().tolist())
    # 內顯：官方資料沒有的（Qualcomm、MediaTek、NVIDIA），改用 ASUS 原文，只取單一處理器的料號／型號
    single = df[df.cpu_model.notna() & ~df.cpu_model.str.contains("/", na=False)]
    asus_igpu = single.assign(i=single.text_gpu.map(igpu_from_text)).dropna(subset=["i"]).groupby("cpu_model").i.agg(
        lambda s: s.mode().iloc[0])
    cpus["cpu_igpu"] = cpus.cpu_igpu.fillna(cpus.cpu_model.map(asus_igpu))
    gpus = build_gpus(df.text_gpu.dropna().tolist())
    # 檢查每個料號的規格是否唯一：同型號下 FIELDS 的原文欄位完全相同的料號標成 False
    cols = ["base_model", *(f"text_{f}" for f in FIELDS)]
    sku = df.level == "sku"
    df["spec_unique"] = None
    df.loc[sku, "spec_unique"] = ~df[sku].fillna("").duplicated(cols, keep=False)
    # 規格原文都已拆成欄位（處理器、獨顯的固定規格在 cpus、gpus 表），刪除原文；原文仍保存在 data/raw
    df = df.drop(columns=[c for c in df.columns if c.startswith("text_")])
    cols = [c for c in df.columns if c != "cpu_power_w"]
    df = df[cols[:cols.index("cpu_model") + 1] + ["cpu_power_w"] + cols[cols.index("cpu_model") + 1:]]
    stores = {name: load_store(name) for name in STORES}
    for name, items in stores.items():
        df = store_summary(df, name, items)
    price_cols = [c for name in STORES for c in (f"{name}_price_min", f"{name}_listings")]
    cols = [c for c in df.columns if c not in price_cols]
    i = cols.index("price") + 1  # 通路價格放在 ASUS Store 售價旁邊
    df = df[cols[:i] + price_cols + cols[i:]]
    with sqlite3.connect(DB) as con:
        df.to_sql("laptops", con, if_exists="replace", index=False)
        cpus.to_sql("cpus", con, if_exists="replace", index=False)
        gpus.to_sql("gpus", con, if_exists="replace", index=False)
        for name, items in stores.items():
            if not items.empty:
                items.to_sql(f"{name}_prices", con, if_exists="replace", index=False)
    df.to_csv(CSV, index=False, encoding="utf-8-sig")  # utf-8-sig 讓 Excel 正確顯示中文
    cpus.to_csv(CPU_CSV, index=False, encoding="utf-8-sig")
    gpus.to_csv(GPU_CSV, index=False, encoding="utf-8-sig")
    for name, items in stores.items():
        if not items.empty:
            items.to_csv(STORES[name][1], index=False, encoding="utf-8-sig")
    print(f"{len(df)} 筆（料號 {(df.level == 'sku').sum()}、型號 {(df.level == 'model').sum()}）→ {DB}、{CSV}")
    print(f"處理器 {len(cpus)} 顆 → {DB}（表 cpus）、{CPU_CSV}")
    print(f"獨立顯卡 {len(gpus)} 款 → {DB}（表 gpus）、{GPU_CSV}")
    for name, items in stores.items():
        if not items.empty:
            print(f"{name} 商品 {len(items)} 筆 → {DB}（表 {name}_prices）、{STORES[name][1]}")
    dup = df[df.spec_unique == False]  # noqa: E712
    print(f"\n規格無法區分的料號 {len(dup)} 個：")
    print(dup[["sales_model", "part_no"]].to_string(index=False))
    print("\n各欄位缺值數：")
    print(df.isna().sum()[lambda s: s > 0].to_string())


if __name__ == "__main__":
    main()
