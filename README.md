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
| Display | DSI panel 3392x2400@120 native KMS; display and backlight-only wake visually verified | Full display-link shutdown/recovery remains broken; blanking keeps KMS running and switches both backlights. |
| Power button | Physical blank/wake and the restored main UI verified by the user on 0.1.18 | GNOME retains authentication. Screen-off power is higher because the display pipeline stays active. |
| Platform identity | System and desktop identify a physical tablet | Corrected before PID1 starts; VM/container/confidential-VM detection and systemd conditions verified on hardware. |
| Touch (NT36536) | Finger input and login interaction verified by the user | The backlight-only blanking workaround leaves touch firmware running; deep-suspend recovery is not covered. |
| UFS | read-only evidence + GPT layout | no persistent writes anywhere |
| ADSP | DSP `running`, stock glink channels up | stock modem_a firmware, 80.5M carveout |
| Type-C | pmic-glink + UCSI port, role follows plug | device/sink on a PC link, host for gadgets |
| GPU (A830) | kernel-side up: GMU v5.1.25, render node answers, no zap needed on this retail unit | Mesa in Ubuntu 26.04 lacks the A830 chipid -> GNOME stays llvmpipe |
| Wi-Fi (WCN7860) | PCIe Gen3 x2 up, firmware loads, `wlp1s0` managed by NetworkManager | needs AP credentials for an actual connection |
| Desktop | Ubuntu 26.04 systemd as PID1, GNOME Shell session runs | RAM-delivered squashfs, llvmpipe; NM/ssh tooling in s5 |

The current blanking workaround switches both backlights while keeping KMS
running. The failed touch/DSI retention diagnostics have been reverted.
`erhai-display-power` adapts only the GNOME Settings Daemon 50 display-power
setter; the original daemon continues to manage battery policy and inhibitors.
The adapter is loaded through a service drop-in, without overwriting Ubuntu
files. It is scoped to the supported GNOME major version; a desktop major
upgrade requires checking that generated setter ABI and updating the package.
Physical wake, the main UI, touch and login were confirmed on 0.1.18.
Keeping the display pipeline running increases screen-off power consumption.
Automatic blanking and automatic suspend remain disabled by default; retaining
MDSS at runtime does not establish working display recovery from system suspend.

The button handler requests a GNOME lock before blanking a user session; at
the login screen it only blanks. A subsequent press requests display wake,
while authentication stays with GNOME. The on-screen keyboard is enabled by
default. A separate logged-in password-reentry test has not been recorded.

The firmware's Gunyah HLOS description triggers a generic VM heuristic on this
board. The initramfs covers that unused userspace export before PID1 starts;
the kernel device tree and raw FDT remain intact. The policy is restricted to
this tablet's model, HLOS VMID and unbound nodes, with a boot-time consistency
check. Setting only the chassis name is insufficient because PID1 caches its
own virtualization result.

Not yet: full display-link shutdown/recovery, GPU-accelerated desktop (Mesa), Bluetooth
(HCI transport unidentified on this unit), audio, persistent installation.

## Repository layout

```
tools/       build & packaging entry points (see below)
initramfs/   RAM userspace profiles (USB ACM console / NCM evidence channel)
switch/      dual-boot switcher and its KernelSU module (see switch/README.md)
packaging/   debian metadata for the device .deb set (see tools/build-debs.py),
             and firmware/ -- the device firmware closure it packs
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
- Nothing for firmware: `packaging/firmware/` already carries the closure this
  unit needs, and `packaging/firmware/README.md` says where every file came
  from. Only moving to a later stock ROM needs the ROM itself, through
  `tools/build-debs.py --refresh-from-rom`.
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

For a temporary kernel using an already installed root, use the persistent
profile with an explicit `erhai.session=90` (valid range 60–3600 seconds).
The initramfs places an expiry service only in the new root's `/run`; once
userspace starts, it returns the tablet to the bootloader after that bound.
Normal persistent boots omit this parameter and do not expire. The runtime
marker `/run/erhai-test-session.started` distinguishes a running userspace
watchdog from a boot that never reached the service.

## Dual boot

`switch/` holds the persistent-install half: Android and Ubuntu take turns in
the **active** A/B slot, because this unit's B slot carries an older firmware
chain that can never boot and its ABL will not run a kernel out of `recovery`.
Every image written into `boot`/`init_boot`/`vendor_boot` must carry an AVB
hash footer (`tools/sign-boot-triplet.py`), self-signed included — `vbmeta`
lists `boot` as a chain partition, so a missing footer is malformed metadata
that even an unlocked bootloader refuses. See `switch/README.md`.

## Device packages

The installed system is Canonical's Ubuntu, unpacked as it ships and free to
follow upstream through apt. Everything this tablet needs on top of it is a
package, and each package owns exactly what it installs:

```sh
tools/build-debs.py --avb-key <key>.pem --avbtool <aosp avbtool.py>
```

| Package | Owns |
|---|---|
| `erhai-device-support` | `/usr/sbin/erhai-switch{,-install-ubuntu-images}`, the store directory and its logrotate snippet, the "Switch to Android" desktop entry and its polkit action, the power settings this port needs until suspend/resume works, and the two programs that give this unit its own Bluetooth and Wi-Fi addresses (`erhai-bt-address` with its units, `erhai-wifi-address` with its udev rule and NetworkManager drop-in). The addresses themselves live in `/var/lib/erhai/` and are in **no** package: they are machine-specific data, written on the tablet at first boot |
| `erhai-kernel` | the signed boot triplet under `/usr/lib/erhai/boot/<release>/`; its postinst hands the set to the switcher's installer, so **a kernel update is an apt upgrade** |
| `erhai-firmware` | the firmware closure the mainline drivers ask for and the distribution does not ship under those names |
| `erhai-device` | a metapackage depending on the three |

The build needs no root (`dpkg-deb --root-owner-group` on a staged tree) and
takes its firmware from `packaging/firmware/`, checking every file against the
sha256 and size recorded in `packaging/firmware-manifest.json` before packing
it — so `erhai-firmware` builds out of this checkout alone, with no ROM cache
and no network. `--refresh-from-rom` runs the other direction: it extracts the
closure from the pinned stock ROM images and upstream archives again and diffs
that against the tree, which is how a later ROM version gets in. Neither the
AVB signing key nor avbtool ever enters a package.

Two builds of the same inputs produce the same bytes: the version carries a
build id derived from the packaged content (`0.1.0+b<8 hex>`), the AVB footers
use a salt derived from the image instead of avbtool's random default, and the
archive timestamps are pinned to the kernel commit.

`--debug` builds the triplet with the RAM session's debug channel enabled and
marks the version `+dbg`. The default is off: see Safety.

## Safety

RAM sessions write nothing to flash. Anything beyond that — partitioning,
flashing, persistent installs — is out of scope for this tree and requires
explicit separate steps and authorization. The switcher in `switch/` is the
one exception, and it writes only the three boot partitions of the slot that
is already active.

The RAM session's debug channel is an **unauthenticated root telnet** on the
USB NCM link by design (it is the only bring-up channel on this device). It
lives only inside the bounded RAM session with a watchdog that reboots back
to Android; never carry it into a persistent install or a shipped image.
`tools/build-debs.py` therefore leaves it out of `erhai-kernel` unless it is
asked for explicitly with `--debug`, which also marks the version `+dbg` so an
installed debug build is visible in `dpkg -l`.

## License

GPL-2.0-only (see LICENSE), matching the integration scripts' SPDX headers.
Kernel and third-party inputs keep their own licenses and authors.

`packaging/firmware/` is the exception worth naming out loud: 72 proprietary
Qualcomm and OnePlus binaries, redistributed here exactly as they came so that
the port builds from one tree. The project claims no copyright and grants no
license over them, and GPL-2.0-only does not reach them. 59 of them were
extracted from this unit's stock OnePlus OTA, for which no redistribution
permission from OnePlus or Qualcomm has been established. Per-file provenance
is in `packaging/firmware-manifest.json` and the terms are spelled out in
[`packaging/firmware/README.md`](packaging/firmware/README.md).
