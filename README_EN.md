# StarLux-Landing-Meter-MSFS

[![LICENSE](https://img.shields.io/badge/license-Anti%20996-blue.svg)](https://github.com/996icu/996.ICU/blob/master/LICENSE)

**中文:** [README.md](README.md)

> This repository is a **Python + SimConnect port** of [Starlux531/StarLux-Landing-Meter](https://github.com/Starlux531/StarLux-Landing-Meter) (an X-Plane 12 + FlyWithLua landing-rate add-on, v1.1), made for **Microsoft Flight Simulator 2020 / 2024**.

---

## Quick Start

The **Releases** page of this repository ships ready-to-run binaries (the two files in the `dist` folder), while the repo also keeps the full Python source — so there are two ways to run it:

| Method | For | Install needed |
| --- | --- | --- |
| **① exe from Releases** | Users who don't want to set up an environment | None (zero dependencies, double-click to run) |
| **② Run the Python source** | Users who want to read / modify the code | `pip install SimConnect` |

### Method 1: Run the exe from Releases (recommended, zero dependencies)

1. Go to the [Releases](https://github.com/G4Y8u9/StarLux-Landing-Meter-MSFS/releases) page and download the latest version;
2. The release assets contain **the two files from the `dist` folder**:
   - `StarLux-Landing-Meter-MSFS.exe` — the packaged landing monitor (with desktop / window / tray icons and a bilingual EN/CN UI). Double-click to run;
   - `LMM_Report_Reader_v2.html` — the companion report reader; open it in a browser;
3. Start MSFS and load your aircraft, then run the exe. It connects and monitors automatically; the moment the main gear touches down it analyses the landing and, after ~1.2 s of impact capture, saves the report to the desktop (`Starlux_Report_*.txt`);
4. Drag (or pick) the generated TXT report into `LMM_Report_Reader_v2.html` to review the rating, load, wind & attitude, the multi-parameter trajectory after 100 ft, and the full raw report.

### Method 2: Run locally with Python (requires the SimConnect library)

The repo ships the `starlux_LMM_pyver.py` source, so you can run it locally:

```bash
# install the dependency
pip install SimConnect

# run the main program (plain console)
python starlux_LMM_pyver.py
```

The rest of the flow is identical to Method 1: connect to MSFS → monitor landings → auto-generate the report → open it with `LMM_Report_Reader_v2.html` (or `LMM_Report_Reader_Light.html`).

> **Note**: the exe is simply the Python environment with its dependencies (SimConnect / pystray / PIL / tkinter) bundled. Both methods produce exactly the same reports and visualization.

---

## 1. About

StarLux Landing Meter is a flight-sim debrief tool: right after the main gear touches down, it automatically computes the **touchdown sink rate (FPM)** and **landing load (G)**, outputs a rating (NICE / STABLE / ATTENTION / UNSTABLE), and also captures the flare trajectory after 100 ft, bounce detection, wind & attitude and other debrief data.

The original add-on runs inside X-Plane via FlyWithLua. This port instead uses a **Python script that reads MSFS data through SimConnect**, generates TXT reports in the same format as the Lua version, and visualizes them with the bundled HTML report reader.

> **Algorithm notes**: the core algorithms (three-chain FPM validation, AGL geometric closure, G-load / impulse consistency, flare curve, bounce scoring, etc.) are a faithful reproduction of the original Lua project. See the [original repository](https://github.com/Starlux531/StarLux-Landing-Meter) for the formulas and design rationale.

---

## 2. Environment

> This section applies to **Method 2 (local Python)**; Method 1 (the release exe) needs no installation at all.

- **Python version**: 3.13.x (developed / tested on Python 3.13.7)
- **Dependency**: [SimConnect](https://pypi.org/project/SimConnect/)

   ```bash
   pip install SimConnect
   ```

- **Optional dependency** (only needed to run the tray launcher `starlux_tray_launcher.py`):

   ```bash
   pip install pystray pillow
   ```

- **Simulator**: Microsoft Flight Simulator 2020 / 2024 (start the game and load an aircraft before launching the program)

---

## 3. Files

| File | Description |
| --- | --- |
| `starlux_LMM_pyver.py` | Main Python source: connects to MSFS, samples, analyses landings, writes TXT reports |
| `starlux_tray_launcher.py` | Tray launcher source: windowed UI + system tray, bilingual EN/CN (the exe is built from this) |
| `StarLux_LMM.spec` | PyInstaller build config (onefile / noconsole / icon) |
| `make_icon.py` | Generates the multi-size `starlux_icon.ico` from `1.png` |
| `starlux_icon.ico` | App icon (shared by desktop / window / tray) |
| `LMM_Report_Reader_v2.html` | Latest local HTML report reader (bilingual EN/CN, shipped with Releases) |
| `LMM_Report_Reader_Light.html` | Report reader (light / compact variant, same source as v2) |
| `LMM_Report_Reader.html` | Report reader (early version) |
| `Starlux_Report_2026-08-19_16-13-45.txt` | A real-landing report **sample** — drag it into the HTML reader to see the effect |

`dist/` (build output, published with Releases):

| File | Description |
| --- | --- |
| `StarLux-Landing-Meter-MSFS.exe` | Packaged program; double-click to run, no Python / SimConnect needed |
| `LMM_Report_Reader_v2.html` | Companion report reader; open in a browser |

---

## 4. Usage

1. Start MSFS and load your aircraft (pick either run method above — see “Quick Start”):
   - **exe**: double-click `StarLux-Landing-Meter-MSFS.exe` from the Release;
   - **Python**: `python starlux_LMM_pyver.py`.
2. Once connected, the program monitors at 16 Hz. The instant the main gear touches down it starts the landing analysis and, ~1.2 s after impact capture, writes the report and shows the save path in the window (default: desktop `Starlux_Report_*.txt`);
3. Open `LMM_Report_Reader_v2.html` (release) or `LMM_Report_Reader_Light.html` in a browser and **drag / pick** the generated TXT report (or the sample) to review the rating, load, wind & attitude, the 100 ft multi-parameter trajectory, and the full raw report.

> Reports are purely local; the reader parses everything in your browser and uploads nothing.

---

## 5. Python port & changes (`starlux_logger.py`)

- **Data reading**: the stock `SimConnect.AircraftRequests` reads variables one by one (~15 ms per round trip; 13 variables ≈ 200 ms per frame, i.e. only ~4 Hz), so a custom `BatchSimConnect` was added — all simvars go into **one data definition**, every frame reads all 20 variables in a single round trip, restoring the sampling rate to **16 Hz** (exactly `1/16 s`).
- **Vertical speed source**: the severely distorted `VELOCITY_BODY_Y` (roughly 7–8× too high in this environment) is dropped in favour of world-axis `VELOCITY_WORLD_Y` (fps→m/s), matching X-Plane's `local_vy` semantics.
- **AGL source**: the real radio altitude `RADIO_HEIGHT` is preferred; because MSFS shows an AGL plateau of ~11.7 ft right before touchdown, the terminal window is a pure time window (250 ms before touch, airborne samples only) and the AGL geometric closure uses a longer **0.85 s** window.
- **16 Hz adaptation**: `MAX_VALID_SAMPLE_GAP_SECONDS` was raised from 0.050 to 0.10 so the G analysis isn't wrongly flagged as “insufficient physical samples” at 16 Hz.
- **Spurious-G filter**: `projected_vertical_g` runs `sanitize_g` first (0.2 < G ≤ 5.0) so rare MSFS glitches (e.g. pulses to tens of G) don't poison the peak, local envelope, or impulse-consistency calculations.
- **Roll direction**: in this environment `PLANE_BANK_DEGREES` reports the opposite sign (left bank shown as right), so the sign is inverted on read (positive = right bank, negative = left bank).

---

## 6. HTML report reader changes (`LMM_Report_Reader_v2.html`)

- **Parsing bug fix**: `parseNumber` now only parses values that *start with a digit*, so “use global P75”'s 75 is no longer shown as 75 G; roll values with a “左倾/右倾” prefix use a dedicated `anyNumber` extraction.
- **Interaction**: the home `＋` is clickable to pick files; drag only triggers import when real files are dropped (dragging text selections inside the raw TXT no longer reports “no TXT file found”).
- **Bilingual switch**: added a one-click EN/CN language toggle (top-right button); both the UI strings and the Chinese values embedded in reports (rating, FPM source, relative wind, roll, trajectory conclusion, bounce, etc.) are translated to English in real time.
- **Layout**: removed the display of unimplemented airport / runway / aircraft identification; removed the “touchdown distance” card, the “download raw TXT” button and the context-switch buttons; landing context and chart areas fill their cards; “Full Raw TXT” is expanded by default.
- **Footer**: version marked v2 with links to the original project and this repo's author.

---

## 7. Porting note

This port was assisted by **AI (GitHub Copilot, based on the DeepSeek V4 Flash model)**: reproducing the Lua → Python algorithms, adapting the MSFS SimConnect data source, locating and fixing sampling-rate / data-quality issues, and the HTML reader parsing / layout changes.

The port and modifications **did not change the original algorithm logic** — the three-chain validation, impulse consistency, flare curvature, bounce scoring, etc. remain consistent with the original Lua version (only minor input adaptations for MSFS data characteristics, all documented in the code comments).

> For deep algorithm details, please see the [original repository](https://github.com/Starlux531/StarLux-Landing-Meter) for source and docs.

---

## 8. License

This project is licensed under the [Anti-996 License](https://github.com/996icu/996.ICU/blob/master/LICENSE).
**Based on the MIT license, it additionally prohibits commercial use by companies that violate labor laws or promote 996 work schedules.**

The original project is copyrighted by [Starlux531](https://github.com/Starlux531).
