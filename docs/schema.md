# ASUS 筆電資料庫欄位說明

資料庫：`data/asus_laptops.db`（SQLite），每張表另有同內容的 CSV。

| 表 | CSV | 內容 |
|---|---|---|
| `laptops` | `data/asus_laptops.csv` | 每台筆電一列：料號層級（`level = sku`）或型號層級（`level = model`） |
| `cpus` | `data/asus_cpus.csv` | 處理器固定規格，用 `cpu_model` 對照 |
| `gpus` | `data/asus_gpus.csv` | 獨立顯卡固定規格，用 `gpu_model` 對照 |
| `pchome_prices` | `data/pchome_prices.csv` | PChome 24h 上的商品與售價，用 `sales_model` 或 `base_model` 對照 |
| `momo_prices` | `data/momo_prices.csv` | momo 購物網上的商品與售價，用 `sales_model` 或 `base_model` 對照 |

## 設計原則

- **晶片固定規格不放在 `laptops`**：處理器、獨顯的核心數、快取、算力等由晶片決定的規格，放在 `cpus`、`gpus`，`laptops` 只記型號。
- **ASUS 為這台機器做的設定放在 `laptops`**：例如 GPU 瓦數（`gpu_tgp_w`）、CPU 瓦數（`cpu_power_w`）、記憶體與儲存配置。
- **官方規格優先**：`cpus`、`gpus` 的數值以 Intel、AMD、NVIDIA 官方資料為準，官方沒有時才用 ASUS 規格原文。
- **規格原文不入庫**：ASUS 規格原文已全部拆成欄位，原文保存在 `data/raw/asus_models.jsonl`。

## 料號層級與型號層級

| `level` | 一列代表 | 規格值 | 料號、售價 |
|---|---|---|---|
| `sku` | 一個實際販售的配置（一個料號） | 單一值，配置確定 | 有（售價只有部分料號有） |
| `model` | 一個型號底下所有可能的配置 | 可能有多個選項，以 `/` 分隔，看不出搭配 | 無 |

官網只對 ASUS Store 有販售的機種提供料號資料，其餘機種只有型號層級。

**多選項欄位與 `_max`**：型號層級常列出多種配置，例如 `ram_gb = 16/32/64`；對應的 `_max` 欄位（如 `ram_gb_max = 64`）是最大值，用於數字篩選。

**型號欄位含多個值時**：型號層級的 `cpu_model`、`gpu_model` 可能是 `Core Ultra 7 255H/Core Ultra 5 225H`，要先以 `/` 拆開再查表。

---

## `laptops`

### 識別與分類

| 欄位 | 型別 | 說明 |
|---|---|---|
| `part_no` | 文字 | 料號，例如 `90NB1501-M00AS0`；型號層級為空 |
| `sales_model` | 文字 | 銷售型號，例如 `UX3407QA-0072D26100`；與料號一對一 |
| `base_model` | 文字 | 基礎型號，例如 `UX3407QA`、`G615LR` |
| `level` | 文字 | `sku`（料號層級）或 `model`（型號層級） |
| `series` | 文字 | 系列名稱，例如 `ASUS Zenbook A14 (UX3407)` |
| `source` | 文字 | 資料來源：`asus`（一般機種）或 `rog` |
| `category` | 文字 | 產品線，例如 Zenbook、Vivobook、TUF-Gaming；ROG 各系列統一為 `ROG` |
| `price` | 數字 | ASUS Store 售價（新台幣），只有部分料號有 |
| `pchome_price_min` | 數字 | PChome 最低售價，只算全新、原廠配置（排除特仕、福利品）。料號層級對銷售型號；型號層級對基礎型號（同型號任一配置的最低價） |
| `pchome_listings` | 數字 | 上述計算用到的 PChome 商品數；0 表示 PChome 沒有販售 |
| `momo_price_min` | 數字 | momo 最低售價，規則同 PChome，另外排除組合包（加購滑鼠、Office 等） |
| `momo_listings` | 數字 | 上述計算用到的 momo 商品數 |

### 處理器、獨顯

| 欄位 | 型別 | 說明 |
|---|---|---|
| `cpu_model` | 文字 | 處理器型號，對照 `cpus` 表 |
| `cpu_power_w` | 數字 | ASUS 設定的 CPU 瓦數；官網極少標示，目前只有 2 筆 |
| `has_dgpu` | 布林 | 是否有獨立顯卡 |
| `gpu_model` | 文字 | 獨顯型號，對照 `gpus` 表 |
| `gpu_tgp_w` | 數字 | ASUS 設定的 GPU 總瓦數（基本 + Dynamic Boost） |
| `gpu_tgp_base_w` | 數字 | GPU 基本瓦數（不含 Dynamic Boost）；比較不同筆電時建議看這欄 |
| `gpu_boost_mhz` | 數字 | ASUS 標示的 GPU 加速時脈（含 ASUS 超頻） |
| `vram_gb` / `vram_gb_max` | 文字 / 數字 | 獨顯的顯示記憶體容量 |
| `has_mux` | 布林 | 有 MUX 獨顯直連或 Advanced Optimus |
| `has_gsync` | 布林 | 支援 G-SYNC |

### 記憶體、儲存

| 欄位 | 型別 | 說明 |
|---|---|---|
| `ram_gb` / `ram_gb_max` | 文字 / 數字 | 記憶體容量；料號若同時有內建與插槽記憶體，為加總（如 8GB + 16GB = 24） |
| `ram_type` | 文字 | 記憶體種類：DDR4、DDR5、LPDDR4X、LPDDR5、LPDDR5X |
| `ram_speed_mts` | 數字 | 記憶體速度（MT/s） |
| `ram_upgradeable` | 布林 | 有 SO-DIMM 插槽，可自行更換或加裝 |
| `ram_slots` | 數字 | SO-DIMM 插槽數 |
| `ram_soldered` | 布林 | 有焊在主機板上（或封裝在處理器上）的記憶體 |
| `ram_max_gb` | 數字 | 官方標示的最高支援容量。有插槽時代表可擴充上限；全焊死時只是同型號最高配置 |
| `storage_gb` / `storage_gb_max` | 文字 / 數字 | 儲存空間容量（GB，1TB = 1024） |
| `storage_interface` | 文字 | PCIe 5.0、PCIe 4.0、PCIe 3.0、UFS、eMMC、HDD |
| `m2_slots` | 數字 | M.2 插槽數（含已使用） |
| `has_25_bay` | 布林 | 有 2.5 吋硬碟槽 |

### 螢幕

| 欄位 | 型別 | 說明 |
|---|---|---|
| `screen_inch` | 數字 | 螢幕尺寸（吋） |
| `resolution` | 文字 | 解析度，例如 `2880x1800` |
| `aspect_ratio` | 文字 | 長寬比：16:10、16:9、3:2 |
| `panel_type` | 文字 | 面板：OLED、Mini LED、IPS、TN；原文沒寫時為空 |
| `is_oled` | 布林 | 是否為 OLED |
| `refresh_hz` / `refresh_hz_max` | 文字 / 數字 | 更新率（Hz）；舊款商務機常未標示，通常為 60Hz |
| `brightness_nits` | 數字 | 一般亮度（nits），不含 HDR 峰值 |
| `hdr_peak_nits` | 數字 | HDR 峰值亮度（nits） |
| `dci_p3_pct`、`srgb_pct`、`ntsc_pct` | 數字 | 色域覆蓋率（%） |
| `display_finish` | 文字 | 鏡面或霧面（含防眩光、抗反光） |
| `is_touch` | 布林 | 觸控螢幕 |
| `stylus_support` | 布林 | 支援觸控筆 |

### 接孔、無線、鏡頭

| 欄位 | 型別 | 說明 |
|---|---|---|
| `usb_c_ports` | 數字 | USB-C 數量（含 Thunderbolt、USB4） |
| `usb_a_ports` | 數字 | USB-A 數量 |
| `has_thunderbolt` | 布林 | 有 Thunderbolt |
| `has_usb4` | 布林 | 有 USB4 |
| `hdmi_version` | 文字 | HDMI 版本，例如 `2.1`；有 HDMI 但未標版本時為 `有` |
| `has_rj45` | 布林 | 有有線網路孔 |
| `card_reader` | 文字 | 讀卡機：SD、microSD、SD Express |
| `has_audio_jack` | 布林 | 有 3.5mm 耳機孔 |
| `wifi` | 文字 | Wi-Fi 5、Wi-Fi 6、Wi-Fi 6E、Wi-Fi 7 |
| `bluetooth` | 數字 | 藍牙版本 |
| `camera` | 文字 | 鏡頭解析度：5MP、1080p、720p、VGA |
| `camera_ir` | 布林 | 紅外線鏡頭（支援 Windows Hello 臉部辨識） |
| `camera_shutter` | 布林 | 實體鏡頭遮罩 |

### 電池、電源、機身

| 欄位 | 型別 | 說明 |
|---|---|---|
| `battery_wh` / `battery_wh_max` | 文字 / 數字 | 電池容量（Wh） |
| `adapter_w` / `adapter_w_max` | 文字 / 數字 | 變壓器瓦數，可作為整機功耗等級的指標 |
| `usb_c_charging` | 布林 | 可用 USB-C 充電 |
| `weight_kg` | 數字 | 重量（kg）；可拆式機種為整機重量 |
| `width_cm`、`depth_cm` | 數字 | 寬、深（cm） |
| `thickness_min_cm`、`thickness_max_cm` | 數字 | 最薄、最厚處厚度（cm） |
| `mil_std` | 文字 | 軍規認證，例如 `MIL-STD 810H` |
| `color` | 文字 | 顏色；ROG 規格無此資訊 |

### 鍵盤、作業系統、隨附配件

| 欄位 | 型別 | 說明 |
|---|---|---|
| `kb_backlight` | 文字 | 鍵盤背光：無、有、RGB、Per-key RGB |
| `kb_numpad` | 布林 | 實體數字鍵 |
| `touchpad_numberpad` | 布林 | 觸控板上的虛擬數字鍵（NumberPad） |
| `kb_travel_mm` | 數字 | 鍵程（mm） |
| `kb_spill_resistant` | 布林 | 防潑水鍵盤 |
| `copilot_key` | 布林 | 有 Copilot 鍵 |
| `os` | 文字 | 作業系統，例如 `Windows 11 Home`、`ChromeOS` |
| `bundled_mouse`、`bundled_bag`、`bundled_stylus`、`bundled_hdd_kit` | 布林 | 隨附滑鼠、包、觸控筆、硬碟擴充套件 |

### 資料管理

| 欄位 | 型別 | 說明 |
|---|---|---|
| `has_spec` | 布林 | 有結構化規格；舊頁面只有整段 HTML 的為 False，規格欄位皆空 |
| `spec_unique` | 布林 | 料號規格是否唯一。官網規格完全相同的 8 組（16 個料號）為 False；型號層級為空 |
| `url` | 文字 | 官網產品頁 |
| `online_date` | 文字 | 官網上架日期 |
| `fetched_at` | 文字 | 抓取日期 |

---

## `cpus`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `cpu_model` | 文字 | 對照用的 key，例如 `Core Ultra 5 226V`、`Ryzen AI 9 HX 370` |
| `cpu_brand` | 文字 | Intel、AMD、Qualcomm、MediaTek、NVIDIA |
| `cpu_series` | 文字 | 系列，例如 `Core Ultra 5`、`Ryzen AI 9 HX` |
| `cpu_number` | 文字 | 編號，例如 `226V`、`370` |
| `cpu_codename` | 文字 | 架構代號，例如 Lunar Lake、Strix Point |
| `cpu_igpu` | 文字 | 內建顯示晶片；無內顯的型號為 `無內顯（需搭配獨顯）` |
| `cpu_cores` | 數字 | 總核心數 |
| `cpu_p_cores`、`cpu_e_cores`、`cpu_lpe_cores` | 數字 | 大核、小核、低功耗小核數（Intel；AMD 官方未分） |
| `cpu_threads` | 數字 | 執行緒數 |
| `cpu_base_ghz` | 數字 | 基本時脈；Intel 多數仍為 ASUS 標示值 |
| `cpu_boost_ghz` | 數字 | 最高時脈 |
| `cpu_cache_mb` | 數字 | ASUS 標示的快取（Intel 多為 L3，AMD 多為 L2 + L3，不可跨品牌比較） |
| `cpu_l2_mb` | 數字 | 官方 L2 快取；Intel 大多未公布 |
| `cpu_l3_mb` | 數字 | 官方 L3 快取（Intel 為 Smart Cache） |
| `cpu_npu_tops` | 數字 | NPU 算力（TOPS，只算 NPU） |
| `cpu_overall_tops` | 數字 | 平台總算力（CPU + GPU + NPU） |
| `cpu_base_power_w` | 數字 | 基礎功耗（Intel Processor Base Power / AMD Default TDP） |
| `cpu_max_power_w` | 數字 | 最大功耗（Intel Maximum Turbo Power / AMD cTDP 上限） |
| `cpu_min_power_w` | 數字 | 最低功耗（Intel Minimum Assured Power / AMD cTDP 下限） |
| `cpu_official_url` | 文字 | 官方資料來源 |

## `gpus`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `gpu_model` | 文字 | 對照用的 key，例如 `GeForce RTX 5070 Ti` |
| `gpu_architecture` | 文字 | 架構，例如 Blackwell、Ada Lovelace |
| `gpu_cores` | 數字 | NVIDIA CUDA 核心數 / AMD 串流處理器數 |
| `gpu_official_boost_mhz_min`、`gpu_official_boost_mhz_max` | 數字 | 官方加速時脈範圍（AMD 為 Game Frequency） |
| `gpu_power_min_w`、`gpu_power_max_w` | 數字 | 官方功耗範圍，不含 Dynamic Boost；可與 `laptops.gpu_tgp_base_w` 對照 |
| `gpu_official_memory` | 文字 | 官方顯示記憶體配置 |
| `gpu_bus_width` | 文字 | 記憶體匯流排寬度 |
| `gpu_ai_tops` | 數字 | NVIDIA 標示的 AI 算力；計算條件與 NPU 不同，不可直接比較 |
| `gpu_official_url` | 文字 | 官方資料來源 |

## `pchome_prices`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `base_model` | 文字 | 搜尋用的基礎型號 |
| `sales_model` | 文字 | 商品名稱中的銷售型號；名稱沒寫時為空 |
| `in_asus_db` | 布林 | 該銷售型號是否在 ASUS 官網料號資料中 |
| `pchome_id` | 文字 | PChome 商品編號 |
| `name` | 文字 | 商品名稱 |
| `price` | 數字 | 目前售價（不含折價券） |
| `origin_price` | 數字 | 原價 |
| `is_pchome` | 布林 | PChome 24h 自營（False 為第三方賣家） |
| `is_custom` | 布林 | 特仕版：通路自行加大記憶體或硬碟，配置與原廠料號不同 |
| `is_refurb` | 布林 | 福利品、展示機、整新品等非全新品 |
| `url` | 文字 | 商品頁 |
| `fetched_at` | 文字 | 抓取日期 |

## `momo_prices`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `base_model` | 文字 | 搜尋用的基礎型號 |
| `sales_model` | 文字 | 對到的銷售型號；一個商品可能對到多個只差顏色的料號，以 `/` 分隔；對不到時為空 |
| `match_type` | 文字 | `exact`：名稱寫了銷售型號；`config`：名稱只有型號與配置，依處理器、記憶體、儲存容量、OLED 與否比對；空：對不到 |
| `momo_id` | 文字 | momo 商品編號（自營為數字 i_code，第三方商店為 TP 開頭編號） |
| `name` | 文字 | 商品名稱 |
| `price` | 數字 | 目前售價（不含折價、滿額折） |
| `is_momo` | 布林 | momo 自營（False 為第三方商店） |
| `is_bundle` | 布林 | 組合包（名稱有「★」或「組」，如滑鼠組、Office2024 組） |
| `is_custom` | 布林 | 特仕版 |
| `is_refurb` | 布林 | 福利品、展示機等非全新品 |
| `url` | 文字 | 商品頁 |
| `fetched_at` | 文字 | 抓取日期 |

---

## 查詢範例

```sql
-- 料號層級、附處理器與獨顯固定規格
SELECT l.sales_model, l.price, l.cpu_model, c.cpu_p_cores, c.cpu_l3_mb,
       l.gpu_model, l.gpu_tgp_base_w, g.gpu_power_max_w
FROM laptops l
LEFT JOIN cpus c USING (cpu_model)
LEFT JOIN gpus g USING (gpu_model)
WHERE l.level = 'sku';

-- 可自行加裝記憶體、且還有擴充空間的料號
SELECT sales_model, ram_gb, ram_slots, ram_max_gb
FROM laptops
WHERE level = 'sku' AND ram_slots > 0 AND ram_max_gb > ram_gb_max;
```

## 資料來源與更新

| 資料 | 來源 | 產生方式 |
|---|---|---|
| 筆電規格 | ASUS 台灣官網 API（產品列表、型號規格、料號規格、ROG 規格） | `src/asus_catalog.py` → `data/raw/asus_models.jsonl` |
| 處理器官方規格 | AMD 規格總表與產品頁、Intel 官方比較表 PDF、Intel 官網規格頁（手動查詢記於 `data/reference/intel_ark.csv`、`intel_npu.csv`） | `src/cpu_official.py` → `data/reference/cpu_official.csv` |
| PChome 售價 | PChome 24h 搜尋 API，以基礎型號搜尋，從商品名稱比對銷售型號 | `src/pchome_prices.py` → `data/raw/pchome_prices.jsonl` |
| momo 售價 | momo 搜尋結果頁內嵌的商品清單（schema.org ItemList），以基礎型號搜尋，依名稱中的銷售型號或配置比對 | `src/momo_prices.py` → `data/raw/momo_prices.jsonl` |
| 獨顯官方規格 | NVIDIA 筆電 GPU 比較頁、AMD 顯示卡規格總表、NVIDIA 行動工作站產品表（手動記於 `data/reference/gpu_manual.csv`） | `src/gpu_official.py` → `data/reference/gpu_official.csv` |

更新流程：

1. 刪除 `data/raw/asus_models.jsonl`，執行 `py src/asus_catalog.py`（約 15 分鐘）
2. 執行 `py src/cpu_official.py`、`py src/gpu_official.py`
3. 執行 `py src/build_db.py`
4. 更新售價：刪除 `data/raw/pchome_prices.jsonl`、`data/raw/momo_prices.jsonl`，執行 `py src/pchome_prices.py`（約 20 分鐘）、`py src/momo_prices.py`（約 30–40 分鐘），再執行一次 `py src/build_db.py`
