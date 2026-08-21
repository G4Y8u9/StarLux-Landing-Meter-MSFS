# StarLux-Landing-Meter-MSFS

[![LICENSE](https://img.shields.io/badge/license-Anti%20996-blue.svg)](https://github.com/996icu/996.ICU/blob/master/LICENSE)

**English:** [README_EN.md](README_EN.md)

> 本仓库是 [Starlux531/StarLux-Landing-Meter](https://github.com/Starlux531/StarLux-Landing-Meter)（X-Plane 12 + FlyWithLua 落地率插件 v1.1）的 **Python + SimConnect 移植版**，用于 **Microsoft Flight Simulator 2020 / 2024**。

---

## 快速开始

本仓库的 **Releases** 页面提供了打包好的程序（即 `dist` 文件夹内的两个文件），同时仓库内也保留了全部 Python 源码，因此有两种运行方式：

| 方式 | 适用人群 | 需要安装 |
| --- | --- | --- |
| **① Release 里的 exe** | 不想折腾环境 | 无（零依赖，双击即用） |
| **② 本地 Python 运行源码** | 想查看 / 修改代码 | `pip install SimConnect` |

### 方式一：直接运行 Release 中的 exe（推荐，零依赖）

1. 前往本仓库的 [Releases](https://github.com/G4Y8u9/StarLux-Landing-Meter-MSFS/releases) 页面，下载最新版本；
2. Release 附件包含 **dist 文件夹内的两个文件**：
   - `StarLux-Landing-Meter-MSFS.exe` —— 打包好的落地监视程序（含桌面 / 窗口 / 托盘图标，界面中英双语），双击即可运行；
   - `LMM_Report_Reader_v2.html` —— 配套报告阅读器，用浏览器打开；
3. 启动 MSFS 并加载好飞机，再运行 exe。程序会自动连接监听，主轮接地的瞬间自动分析，约 1.2 秒冲击采集结束后把报告保存到桌面 `Starlux_Report_*.txt`；
4. 把生成的 TXT 报告拖入（或选择）`LMM_Report_Reader_v2.html`，即可可视化复盘评分、载荷、风向姿态、100 ft 后多参数轨迹与完整原始报告。

### 方式二：本地 Python 运行（需安装 SimConnect 库）

仓库本身带有 `starlux_LMM_pyver.py` 源码，可以本地运行：

```bash
# 安装依赖
pip install SimConnect

# 运行主程序（纯控制台）
python starlux_LMM_pyver.py
```

其余流程与方式一完全相同：连接 MSFS → 监听落地 → 自动生成报告 → 用 `LMM_Report_Reader_v2.html`（或 `LMM_Report_Reader_Light.html`）打开报告复盘。

> **说明**：exe 只是把 Python 环境与依赖（SimConnect / pystray / PIL / tkinter）打包好了，两种方式生成的报告与可视化结果完全一致。

---

## 一、项目简介

StarLux-Landing-Meter-MSFS 是一款飞行模拟复盘工具：飞机主轮接地后自动计算 **触地下降率（FPM）与接地过载（G）**，并输出评级（NICE / STABLE / ATTENTION / UNSTABLE），附带 100 ft 后拉平轨迹、弹跳检测、风向姿态等复盘数据。

[原项目](https://github.com/Starlux531/StarLux-Landing-Meter)在 X-Plane 内以 FlyWithLua 脚本运行，本移植版改为 **Python 脚本通过 SimConnect 读取 MSFS 数据**，生成与 Lua 版同格式的 TXT 报告，再用配套的 HTML 报告阅读器可视化。

> **算法逻辑说明**：核心算法（三链 FPM 验证、AGL 几何闭合链、G 过载与冲量一致性、拉平曲线、弹跳评分等）完整复现自原 Lua 项目，具体公式与设计思路请查看[原项目仓库](https://github.com/Starlux531/StarLux-Landing-Meter)。

---

## 二、运行环境

> 本小节针对**方式二（本地 Python 运行）**；方式一（Release 的 exe）无需任何安装。

- **Python 版本**：3.13.x（开发与测试环境为 Python 3.13.7）
- **依赖库**：[SimConnect](https://pypi.org/project/SimConnect/)

   ```bash
   pip install SimConnect
   ```

- **模拟器**：Microsoft Flight Simulator 2020 / 2024（建议先启动游戏并加载好飞机，再运行程序）

---

## 三、文件说明

| 文件 | 说明 |
| --- | --- |
| `starlux_LMM_pyver.py` | Python 主程序源码：连接 MSFS、采样、落地分析、生成 TXT 报告 |
| `LMM_Report_Reader_v2.html` | 最新版本地 HTML 报告阅读器（中英双语，随 Release 发布） |
| `Starlux_Report_2026-08-21_15-15-03.txt` | 一份真实落地的报告**样本**，可直接拖入 HTML 阅读器查看效果 |

Release 内容：

| 文件 | 说明 |
| --- | --- |
| `StarLux-Landing-Meter-MSFS.exe` | 打包好的程序，双击即用，无需安装 Python / SimConnect |
| `LMM_Report_Reader_v2.html` | 配套报告阅读器，双击用浏览器打开即可 |

---

## 四、使用方法

1. 启动 MSFS，加载飞机（两种运行方式任选其一，见上文“快速开始”）：
   - **exe 方式**：直接双击 Release 里的 `StarLux-Landing-Meter-MSFS.exe`；
   - **Python 方式**：`python starlux_LMM_pyver.py`。
2. 程序连接 MSFS 后开始以 16 Hz 监听。主轮接地的瞬间自动触发起落分析，约 1.2 秒冲击采集结束后自动生成报告并在窗口提示保存路径（默认保存到桌面 `Starlux_Report_*.txt`）；
3. 用浏览器打开 `LMM_Report_Reader_v2.html`，把生成的 TXT 报告（或项目内样本）**拖入 / 选择**，即可可视化查看评分、载荷、风向姿态、100 ft 后多参数轨迹和完整原始报告。

> 报告为纯本地文件，阅读器完全在浏览器本地解析，不会上传任何数据。

---

## 五、Python 代码移植与改动（`starlux_LMM_pyver.py`）

- **数据读取**：用 `SimConnect` 的 `AircraftRequests` 逐项读取（单次往返约 15ms、13 个变量一帧约 200ms、实际仅 ~4Hz），因此自定义了 `BatchSimConnect`——把所有 simvar 放进**同一条数据定义**，每帧一次往返读取全部 20 个变量，采样率恢复到 **16 Hz**（`1/16s` 精确整除）。
- **垂直速度数据源**：弃用严重失真的 `VELOCITY_BODY_Y`（本环境约高 7~8 倍），改用世界系 `VELOCITY_WORLD_Y`（fps→m/s），与 X-Plane 的 `local_vy` 语义一致。
- **离地高度（AGL）数据源**：优先使用真实无线电高度 `RADIO_HEIGHT`；针对 MSFS 触地前约 11.7 ft 的 AGL 平台，终端窗口改为纯时间窗（触地前 250ms、离地样本），AGL 几何闭合链改用更长的 **0.85s** 窗口。
- **16 Hz 适配**：`MAX_VALID_SAMPLE_GAP_SECONDS` 由 0.050 上调到 0.10，避免 G 分析在 16Hz 下被误判为"物理样本不足"。
- **异常 G 过滤**：`projected_vertical_g` 先做 `sanitize_g`（0.2 < G ≤ 5.0），防止 MSFS 偶发的异常读数（如脉冲到数十 G）污染峰值、局部包络与冲量一致性。
- **横滚方向**：本环境下 `PLANE_BANK_DEGREES` 符号与真实横滚相反（左倾却报右倾），读取时取反（正=右倾、负=左倾）。

---

## 六、HTML 报告阅读器改动（`LMM_Report_Reader_v2.html`）

- **修复解析 bug**：`parseNumber` 改为只解析"以数字开头"的值，避免把"使用全局P75"里的 75 误显示成 75 G；横滚"左倾/右倾"文字在前改为专用 `anyNumber` 提取。
- **交互**：首页加号 `＋` 可点击选择文件；拖拽仅在有真实文件时才触发导入（在原始 TXT 里拖选文字不再误报"没有找到 TXT 文件"）。
- **中英双语切换**：新增右上角一键中英切换按钮；界面文案与报告内嵌的中文取值（评价、下降率来源、相对风、横滚、轨迹结论、弹跳等）会实时翻译为英文。
- **布局调整**：删除了机场/跑道/机型等未实现识别的内容显示；删除"跑道触地点"卡片、"下载原始 TXT"按钮与上下文切换按钮；着陆上下文与图表区域撑满卡片；"完整原始 TXT"默认展开。
- **页脚**：版本标记为 v2，并附原项目与本仓库作者的链接。

---

## 七、移植声明

本移植工作由 **AI（GitHub Copilot，基于 DeepSeek V4 Flash 模型）** 辅助完成：包括 Lua → Python 的算法复现、MSFS SimConnect 数据源适配、采样率与数据质量问题的定位修复，以及 HTML 阅读器的解析/排版改动。

移植与修改过程中**未改动原项目的算法逻辑**——三链验证、冲量一致性、拉平曲率、弹跳评分等均保持与原 Lua 版一致（仅针对 MSFS 数据特征做了少量输入适配，均已在代码注释中说明）。

> 如需深入了解算法细节，请前往[原项目仓库](https://github.com/Starlux531/StarLux-Landing-Meter)查阅源码与文档。

---

## 八、许可证

本项目采用 [Anti-996 License](https://github.com/996icu/996.ICU/blob/master/LICENSE)。
**在 MIT 许可的基础上，禁止违反劳动法及推行 996 制度的企业商用。**

原项目版权归 [Starlux531](https://github.com/Starlux531) 所有。
