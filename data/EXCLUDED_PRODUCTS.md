# Excluded products（未进入基准的波段定义产品）

由 `data/dataset_products.json`（56 个波段类产品，49 个具波段定义）与
`data/dataset_matching_extended.json`（33 个基准产品）程序化对账生成；
复算脚本断言：49 − 33 = 16 = 单波段 13 + 多波段 3。

## 多波段产品（3 个：与任何算子未构成有效候选选择题）

| 产品 | 类别 | 波段数 |
|---|---|---|
| `Global_DOM10` | 全球正射影像 | 3 |
| `MODIS09Q1` | MODIS系列产品 | 4 |
| `S2A_MSIL2A` | Sentinel系列产品 | 25 |

## 单波段产品（13 个：仅一个候选成员，不构成候选选择任务）

| 产品 | 类别 |
|---|---|
| `ERA5_2mTemperature_China_Monthly` | ERA5系列产品 |
| `ERA5_TotalPrecipitation_China_Monthly` | ERA5系列产品 |
| `GISA2.0` | GISA系列产品 |
| `GPM_Precipitation_China_Monthly` | GPM系列产品 |
| `LC08_L1TP_Hubei1420_AOD` | HiGLASS系列产品 |
| `LC08_L1TP_Hubei1420_FVC` | HiGLASS系列产品 |
| `LC08_L1TP_Hubei1420_Fmask4` | HiGLASS系列产品 |
| `LC08_L1TP_Hubei1420_NDVI` | HiGLASS系列产品 |
| `LC08_L1TP_Hubei1420_albedo` | HiGLASS系列产品 |
| `LC_Fmask4` | 定量遥感产品 |
| `LJ01_L2` | 珞珈系列产品 |
| `LJ4I_UVI` | 珞珈系列产品 |
| `ASTER_GDEM_DEM30` | 高程数据 |

## 溯源

- `dataset_products.json` sha256[:12] = `950dc5c0caf8`
- `dataset_matching_extended.json` sha256[:12] = `74cb5f4c412a`
- 生成脚本：`scripts/make_excluded_products.py`（本文件由其输出，勿手改）
