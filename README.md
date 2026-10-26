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

## Firmware Highlights [![](https://img.shields.io/badge/-What's_Included-FFFFFF.svg)](#firmware-highlights-)
- **Full NSS hardware offload** (`kmod-qca-nss-drv*`, `kmod-qca-nss-ecm`, `kmod-qca-nss-crypto`, `kmod-qca-nss-dp`) — PPPoE, L2TP, PPTP, GRE, VLAN, bridge, MAP-T, 6rd/DS-Lite, and crypto are hardware-accelerated on the `ipq60xx` NSS cores.
- **Two build variants:**
  - **WiFi (`JDC-AX1800-PRO-IPQ60XX-6.12-WIFI`):** Includes `ath11k` + NSS WiFi offload/mesh and `dawn` (802.11k/v/r roaming).
  - **NoWiFi (`JDC-AX1800-PRO-IPQ60XX-6.12-NOWIFI`):** Pure wired router build with `ath11k`, `mac80211`/`cfg80211`, `wpad`, and wireless firmwares completely stripped out for lower memory footprint.
- **Kernel-space & user-space VPN ready:**
  - **WireGuard:** `kmod-wireguard`, `wireguard-tools`, and `luci-proto-wireguard` pre-installed.
  - **TUN device (`/dev/net/tun`):** `kmod-tun` is pre-installed in the firmware and shipped in `Packages.tar.gz`, enabling user-space VPNs such as Tailscale, ZeroTier, EasyTier, and OpenVPN out of the box ([#5](https://github.com/miyukowo/libwrt-jdc-ax1800-pro/issues/5)).
- **Included LuCI apps & networking tools:** `luci-app-mwan3`, `luci-app-argon-config` (Argon theme), `luci-app-package-manager`, `luci-app-ttyd`, `luci-app-vnstat2`, `watchcat`, `kmod-tcp-bbr`, plus comprehensive USB Ethernet (`r8152`, ASIX, Aquantia, CDC/RNDIS, iPhone USB tethering) and USB-Serial drivers.
- **Patched `dnsmasq` DNS hijack:** Supports `option dns_redirect_port` so DNS hijacking works properly even when `dnsmasq`'s own DNS listener is disabled (`port=0`) in favor of AdGuard Home or Pi-hole.
- **Package manager:** Base system uses `apk` (not `opkg`), signed with the ImmortalWrt `openwrt-25.12` / `immortalwrt-25.12` release keys.

---

## Known apk Feed Limitations [![](https://img.shields.io/badge/-Read_Before_Reporting_Issues-FFFFFF.svg)](#known-apk-feed-limitations-)
Builds from this branch use `apk` for package management. A few things to know before you run `apk update`/`apk upgrade`:

- **Feed URL/signature mismatch (fixed):** older builds had `CONFIG_VERSION_REPO` pointing at a mismatched OpenWrt *snapshot* URL while the on-device keyring only trusts the *release*-track `openwrt-25.12`/`immortalwrt-25.12` keys, causing `apk update` to fail with `UNTRUSTED signature` on almost every feed. Fixed in [#4](https://github.com/miyukowo/libwrt-jdc-ax1800-pro/pull/4) — `CONFIG_VERSION_REPO` now points at `downloads.immortalwrt.org/releases/25.12-SNAPSHOT`, matching the embedded keys. If you flashed a firmware built before this fix, either reflash a newer build or manually edit `/etc/apk/repositories.d/distfeeds.list` on the router to match.
- **`nss_packages` / `sqm_scripts_nss` are not remotely updatable.** These feeds (`qosmio/nss-packages`, `qosmio/sqm-scripts-nss`) are compiled from source during the CI build and baked directly into the firmware image — they were never published to any public apk mirror. `CONFIG_FEED_nss_packages`/`CONFIG_FEED_sqm_scripts_nss` are disabled so `apk update` doesn't try (and fail) to fetch them. Packages already on your router work fine; getting a newer version requires a full firmware rebuild/reflash, not `apk upgrade`.
- **`video` feed is disabled.** It only contains desktop/GPU packages (Wayland/Weston/wlroots, Qt5, GTK, plus a couple of games like GZDoom/VICE) — nothing networking-related — and ImmortalWrt doesn't publish it for `aarch64_cortex-a53` at all (only OpenWrt's own CDN does). Not needed for routing/PPPoE/NSS use cases, so it's left off by default. If you specifically need it, you can add a line to `/etc/apk/repositories.d/distfeeds.list` pointing at `https://downloads.openwrt.org/releases/packages-25.12/aarch64_cortex-a53/video/packages.adb` (its `openwrt-25.12.pem` key is already trusted on-device), but expect the occasional dependency-resolution failure since those packages are built against vanilla OpenWrt, not ImmortalWrt.

---

## Custom Build [![](https://img.shields.io/badge/-How_To_Compile-FFFFFF.svg)](#custom-build-)
1. Log in to GitHub and fork this project into your own repo.
2. Edit the minimal seed config files under the `configs` directory (`jdc-ax1800-pro-wifi.config` or `jdc-ax1800-pro-nowifi.config`) to add/remove packages, or upload your own `.config` file (`make defconfig` will automatically expand all dependencies during build).
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
