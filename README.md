# onepluspad-2pro-mainline

Mainline Linux and Ubuntu on the OnePlus Pad 2 Pro (OPD2413, Qualcomm SM8750P,
board codename `erhai`), driven by fastboot RAM-boot sessions that never touch
the internal flash.

This repository is the **integration tooling**: kernel build, initramfs
profiles, ABL-compatible image packaging and the RAM-rooted Ubuntu desktop
delivery. The kernel itself lives in a separate Git (`linux-sm8750-erhai`,
checked out at `kernel/linux` in the workspace); see `kernel/source.json`
for the exact baseline, branch and commit.

## Status (device-verified)

| Area | State | Notes |
|---|---|---|
| Boot | `fastboot boot` with ABL-rebuilt DTB | watchdog-bounded RAM sessions, auto-recovery to Android |
| Display | DSI panel 3392x2400@120 native KMS, DPU-side verified pixel-exact | **visual confirmation pending** (kernel chain green; ktz8868 bias + DSC PPS fixes staged) |
| Touch (NT36536) | firmware app runs, resume green | cascade second-header download fix; finger acceptance pending |
| UFS | read-only evidence + GPT layout | no persistent writes anywhere |
| ADSP | DSP `running`, stock glink channels up | stock modem_a firmware, 80.5M carveout |
| Type-C | pmic-glink + UCSI port, role follows plug | device/sink on a PC link, host for gadgets |
| GPU (A830) | kernel-side up: GMU v5.1.25, render node answers, no zap needed on this retail unit | Mesa in Ubuntu 26.04 lacks the A830 chipid -> GNOME stays llvmpipe |
| Wi-Fi (WCN7860) | PCIe Gen3 x2 up, firmware loads, `wlp1s0` managed by NetworkManager | needs AP credentials for an actual connection |
| Desktop | Ubuntu 26.04 systemd as PID1, GNOME Shell session runs | RAM-delivered squashfs, llvmpipe; NM/ssh tooling in s5 |

Not yet: panel visual confirmation, GPU-accelerated desktop (Mesa), Bluetooth
(HCI transport unidentified on this unit), audio, persistent installation.

## Repository layout

```
tools/       build & packaging entry points (see below)
initramfs/   RAM userspace profiles (USB ACM console / NCM evidence channel)
kernel/      source.json pinning the kernel repo identity and tool inputs
```

Tools resolve their workspace automatically when this repo is checked out at
`<workspace>/public/onepluspad-2pro-mainline`; standalone checkouts work too
(`ERHAI_WORKSPACE` overrides). Build outputs always land in `out/` and are
never inputs to the next build.

## Inputs you must provide

- A cross toolchain (`aarch64-linux-gnu-gcc`) and the kernel checkout
  (`kernel/source.json`).
- Static ARM64 busybox, pinned sha256 (see `kernel/source.json`), at
  `cache/busybox-arm64`.
- AOSP `mkbootimg.py` at `cache/tools/mkbootimg.py` (pinned sha256).
- The stock `dtbo.img` and base DTB tables of *your* unit (payload.dumper from
  the stock OTA package) at `cache/stock-c34/` — ABL requires the boot DTB to
  carry the stock overlay symbols and root identity.
- Device firmware blobs extracted read-only from your own unit: the NT36536
  touch firmware (`tools/extract-nt36536-fw.py` from the vendor headfile or
  dtbo blob) and the ADSP `adsp.m*` + `adsp_dtb.*` set from `modem_a`.
- Ubuntu Base 26.04 ARM64 tarball (pinned sha256) for the desktop demo.

## Quickstart

```sh
tools/build-kernel.sh                  # Image + sm8750-erhai.dtb (incremental, ccache)
PROFILE=ncm tools/build-initramfs.sh   # RAM userspace with the NCM evidence channel
tools/build-erhai-abl-symbols.py       # packaging DTB ABL will accept
tools/build-mainline-boot.py --output out/mainline-boot            # minimal session
# add `--profile desktop` for the pinned RAM Ubuntu desktop cmdline
fastboot boot out/mainline-boot/boot-mainline.img
```

The session comes up with a USB NCM link (device `192.168.77.2`, telnet 2323,
HTTP evidence on 8080) and reboots to Android on its own when the watchdog
expires. Optional kernel cmdline flags: `erhai.watchdog=NN` (session length),
`erhai.rootfs=<url>` (fetch+overlay-mount an Ubuntu squashfs over NCM),
`erhai.switchroot=1` (hand PID1 to systemd with a matching expiry timer),
`erhai.weston=1` (autostart the pixman weston desktop).

## Safety

RAM sessions write nothing to flash. Anything beyond that — partitioning,
flashing, persistent installs — is out of scope for this tree and requires
explicit separate steps and authorization.

The RAM session's debug channel is an **unauthenticated root telnet** on the
USB NCM link by design (it is the only bring-up channel on this device). It
lives only inside the bounded RAM session with a watchdog that reboots back
to Android; never carry it into a persistent install or a shipped image.

## License

GPL-2.0-only (see LICENSE), matching the integration scripts' SPDX headers.
Kernel and third-party inputs keep their own licenses and authors.
