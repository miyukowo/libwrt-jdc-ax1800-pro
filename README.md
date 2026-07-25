<p align="center">
	<img width="256" src="/images/libwrt.png"/>
</p>

# LibWrt build for JDC AX1800 Pro (RE-SS-01)

## Build Status
| Workflow | Status |
| :------: | :----: |
| JDC-AX1800-PRO (WiFi) | [![](https://github.com/miyukowo/libwrt-jdc-ax1800-pro/actions/workflows/JDC-AX1800-PRO.yml/badge.svg)](https://github.com/miyukowo/libwrt-jdc-ax1800-pro/actions/workflows/JDC-AX1800-PRO.yml) |
| JDC-AX1800-PRO-NOWIFI | [![](https://github.com/miyukowo/libwrt-jdc-ax1800-pro/actions/workflows/JDC-AX1800-PRO-NOWIFI.yml/badge.svg)](https://github.com/miyukowo/libwrt-jdc-ax1800-pro/actions/workflows/JDC-AX1800-PRO-NOWIFI.yml) |

## Disclaimer [![](https://img.shields.io/badge/-Personal_Disclaimer-FFFFFF.svg)](#disclaimer-)
- **I am not responsible for any theoretical or actual losses caused by using this firmware.**
- **This firmware is strictly prohibited for commercial use. Please comply with all relevant national internet regulations.**

---

## Project Info [![](https://img.shields.io/badge/-Project_Overview-FFFFFF.svg)](#project-info-)
- Default management address: `192.168.1.1`
  Default user: `root`
  Default password: `password`
- Source code: [LiBwrt](https://github.com/LiBwrt/LibWrt) (branch `25.12-nss`)
- Cloud build repo: [miyukowo/libwrt-jdc-ax1800-pro](https://github.com/miyukowo/libwrt-jdc-ax1800-pro)
- Original build repo (Archived): [haiibo/OpenWrt](https://github.com/haiibo/OpenWrt)

---

## Firmware Download [![](https://img.shields.io/badge/-Build_Status_&_Download-FFFFFF.svg)](#firmware-download-)
Click the badge below to download firmware for your device.

[![](https://img.shields.io/badge/Download-Releases-blueviolet.svg?style=flat&logo=hack-the-box)](https://github.com/miyukowo/libwrt-jdc-ax1800-pro/releases)

---

## Custom Build [![](https://img.shields.io/badge/-How_To_Compile-FFFFFF.svg)](#custom-build-)
1. Log in to GitHub and fork this project into your own repo.
2. Edit the corresponding file under the `configs` directory to add/remove packages, or upload your own `.config` file.
3. For plugin names & features, refer to this guide: [Applications Plugin Notes](https://www.right.com.cn/forum/thread-3682029-1-1.html).
4. Modify `libwrt.sh` if you want to add custom packages or adjustments.
5. Edit or add the `xx.yml` workflow file, then trigger the desired `Actions` workflow to start building.
6. Build time is ~40 minutes to 1.5 hours (longer on first build after a source/branch change, due to toolchain cache miss). After completion, firmware will be available in [Releases](https://github.com/miyukowo/libwrt-jdc-ax1800-pro/releases) under the corresponding Tag.

If editing config files feels complicated, you can try extracting configs locally:
👉 https://github.com/LiBwrt/LibWrt

**Video tutorial (YouTube): [OpenWrt Build Interface Setup](https://www.youtube.com/watch?v=jEE_J6-4E3Y&list=WL&index=7)**

### Best of luck to you!

---

<a href="#readme">
<img src="https://img.shields.io/badge/-Back_to_Top-FFFFFF.svg" title="Back to Top" align="right"/>
</a>
