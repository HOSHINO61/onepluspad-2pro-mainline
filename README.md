# onepluspad-2pro-mainline

Mainline Linux and Ubuntu on the OnePlus Pad 2 Pro (OPD2413, Qualcomm SM8750P,
board codename `erhai`), with bounded fastboot RAM-boot sessions and an
installed Ubuntu/Android switching path for the established device layout.

This repository is the **integration tooling**: kernel build, initramfs
profiles, ABL-compatible image packaging and the RAM-rooted Ubuntu desktop
delivery. The kernel itself lives in a separate Git (`linux-sm8750-erhai`,
checked out at `kernel/linux` in the workspace); see `kernel/source.json`
for the exact baseline, branch and commit.

## Status and validation boundaries

The installed audio baseline is 0.1.31. This development candidate adds a native
eight-channel speaker graph and its kernel prerequisites; those additions have
offline validation only. Speaker supplies, board links, stereo routing and
physical playback remain incomplete. The microphone UCM remains the only enabled
audio profile.

| Area | State | Notes |
|---|---|---|
| Boot | Temporary RAM boot and installed GKI triplet verified | Installed Ubuntu and Android switch through the established active-slot layout; temporary installed-root tests use an explicit expiry. |
| Display | DSI panel 3392x2400@120 native KMS; display and backlight-only wake visually verified | Full display-link shutdown/recovery remains broken; blanking keeps KMS running and switches both backlights. |
| Power button | Physical blank/wake and the restored main UI verified by the user on 0.1.18 | GNOME retains authentication. Screen-off power is higher because the display pipeline stays active. |
| Platform identity | System and desktop identify a physical tablet | Corrected before PID1 starts; VM/container/confidential-VM detection and systemd conditions verified on hardware. |
| Touch (NT36536) | Finger input and login interaction verified by the user | The backlight-only blanking workaround leaves touch firmware running; deep-suspend recovery is not covered. |
| UFS | Installed Ubuntu root and active-slot boot-image updates verified | Boot, init_boot and vendor_boot are checked together; destructive layout changes require separate approval. |
| Battery | Charge level/status and full-charge capacity available | The protocol-unit fix restores UPower energy and runtime estimates; net charging performance and control thresholds need separate validation. |
| CPU frequency | SCMI policies and short per-cluster frequency transitions verified | Matching CPUCP mailbox modules are required. Governors and firmware OPPs are unchanged; sustained-load thermal control remains unverified. |
| Board temperature | Two PMIC die and three thermistor channels verified through native IIO reads | Uses the upstream ADC5 Gen3 driver. These measurements do not reproduce the OEM's estimated enclosure temperatures or establish a complete thermal policy. |
| Bluetooth | HCI, firmware loading, discovery and per-device address verified | Pairing and target data/audio use remain separate acceptance work. |
| ADSP | DSP `running`, stock glink channels up | stock modem_a firmware, 80.5M carveout |
| Microphones | Two-channel ALSA/UCM capture and repeated PipeWire recording verified | Speech quality, gain and acoustic noise still need physical acceptance. |
| Speakers | Not enabled | Original legacy TDM parameters and per-amplifier slots are identified. The native eight-channel graph and backend support are prepared; supplies, board links, stereo routing and physical playback remain incomplete. |
| Type-C | pmic-glink + UCSI port, role follows plug | device/sink on a PC link, host for gadgets |
| GPU (A830) | Private Mesa 26.2.3 device package: GLES pixel tests and physical GDM hardware renderer verified | Includes the upstream A830v1 entry missing from Ubuntu Mesa 26.0.3. Vulkan, sustained load and lifecycle validation remain incomplete; the kernel still bypasses rejected zap loading. |
| Wi-Fi (WCN7860) | Association, reconnect and per-device MAC verified | Throughput, roaming and power behavior need further validation. |
| Desktop | Official Ubuntu Desktop 26.04 with device packages, GNOME login and input verified | The optional erhai-mesa package enables hardware rendering for GNOME; application coverage and physical interaction acceptance are tracked separately. |

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

Not yet: full display-link shutdown/recovery and deep-suspend display recovery,
complete graphics/application validation, audio, pogo keyboard, automatic rotation and USB-host
peripheral acceptance.

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
fastboot -s <serial> boot out/mainline-boot/boot-mainline.img
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

## Mesa build and device package

`packaging/mesa/source.json` pins the original Mesa archive and one unmodified
upstream A830v1 device-table patch. `tools/build-mesa.py` checks both hashes and
builds natively on ARM64. It installs only into an output staging tree; it does
not replace the host's graphics libraries. `tools/package-mesa.py` turns a verified
desktop build into the separately removable `erhai-mesa` package.
The patch retains its original author and the affected file's MIT license;
Mesa's own `docs/license.rst` and per-file notices govern the source archive.
This repository's GPL license applies to its build tooling, not to Mesa.

On an Ubuntu ARM64 development system, the build dependencies are:

```sh
apt install build-essential meson ninja-build pkg-config libdrm-dev \
  libexpat1-dev python3-mako python3-ply python3-yaml bison flex \
  zlib1g-dev libzstd-dev libelf-dev libwayland-dev libwayland-egl-backend-dev \
  wayland-protocols libx11-dev libx11-xcb-dev libxcb-dri2-0-dev \
  libxcb-dri3-dev libxcb-present-dev libxcb-randr0-dev libxcb-sync-dev \
  libxcb-xfixes0-dev libxcb-glx0-dev libxcb-shm0-dev libxshmfence-dev \
  libxxf86vm-dev libxrandr-dev libglvnd-dev
tools/build-mesa.py --source-archive mesa-26.2.3.tar.xz \
  --profile desktop --output out/mesa-desktop --jobs 2
tools/package-mesa.py --build-output out/mesa-desktop --output out/mesa-debs
```

The package owns libraries under `/usr/lib/erhai/mesa`, an `environment.d` file
for systemd user applications and a GNOME Shell service drop-in (including GDM).
It changes no Ubuntu-owned library or vendor configuration file. Dependencies
are derived with the native distribution's `dpkg-shlibdeps`; source/build hashes,
package checksums and the input recipe are recorded in its manifest. Increment
`packaging/erhai-mesa/VERSION` for each new installable revision.

Install the resulting deb with `apt install ./erhai-mesa_*.deb`, then cold boot:
restarting the running compositor is unsafe while display-link recovery remains
unfixed. Removal with `apt remove erhai-mesa` restores the distribution selection
after the next cold boot. Ubuntu Mesa currently lacks this chip entry, so removal
restores software rendering. Sandboxed applications with their own graphics
runtimes need separate validation; this package does not replace their runtimes.

The `probe` profile supplies minimal GBM/EGL/GLES; `desktop` also builds the
Wayland, X11 and GLVND interfaces. Both build Freedreno only, without Vulkan or
a software renderer. These are development profiles, not a complete supported
desktop package. The manifest records build inputs, native package versions,
staged file hashes and symlinks. Compatible outputs are incremental and locked
against concurrent writers; changed inputs require a fresh output directory.
Keep the distribution's working desktop available while validating the staged
driver. Hardware drawing, compositor correctness and physical display output
are separate checks.

## Dual boot

`switch/` holds the persistent-install half: Android and Ubuntu take turns in
the **active** A/B slot, because this unit's B slot carries an older firmware
chain that can never boot and its ABL will not run a kernel out of `recovery`.
Every image written into `boot`/`init_boot`/`vendor_boot` must carry an AVB
hash footer (`tools/sign-boot-triplet.py`), self-signed included — `vbmeta`
lists `boot` as a chain partition, so a missing footer is malformed metadata
that even an unlocked bootloader refuses. See `switch/README.md`.

## Device packages

The installed system is Canonical's Ubuntu, unpacked as it ships. The
functional device layer is packaged separately. The GNOME adapter's major
version constraint is noted above; diagnostics are a separate optional package.

```sh
tools/build-debs.py --avb-key <key>.pem --avbtool <aosp avbtool.py>
```

| Package | Owns |
|---|---|
| `erhai-device-support` | `/usr/sbin/erhai-switch{,-install-ubuntu-images}`, the store directory and its logrotate snippet, the "Switch to Android" desktop entry and its polkit action, the power settings this port needs until suspend/resume works, and the two programs that give this unit its own Bluetooth and Wi-Fi addresses (`erhai-bt-address` with its units, `erhai-wifi-address` with its udev rule and NetworkManager drop-in). The addresses themselves live in `/var/lib/erhai/` and are in **no** package: they are machine-specific data, written on the tablet at first boot |
| `erhai-kernel` | selects a versioned kernel payload; configuration activates its triplet through the switcher without rebooting |
| `erhai-kernel-image-<release>` | matching signed boot images and configured modules; installation only populates files and runs `depmod`, allowing RAM validation before selection |
| `erhai-firmware` | the firmware closure the mainline drivers ask for and the distribution does not ship under those names |
| `erhai-audio` | the board AudioReach topology, including an inactive native speaker graph, and UCM for the two internal microphones; speaker playback is not enabled |
| `erhai-display-power` | the dual-backlight service, its socket and the GNOME 50 display-power adapter |
| `erhai-debug` (optional) | USB diagnostic DHCP, HTTP and root-shell units, using Ubuntu's `busybox-static`; all units require `erhai.debug=1` |
| `erhai-device` | a metapackage depending on the required device packages |

The kernel build includes all configured modules and records their hashes.
Its release suffix identifies the source, configuration and compiler so that
different builds use different module directories. Runtime modules are staged
with Kbuild's `modules_install`; the target's kmod generates dependency indices.
Build/source symlinks into a developer workspace are excluded.

Versioned payload packages coexist. The selector protects the running kernel
and the switcher's current/previous selections from automatic package removal;
unreferenced kernels can be removed normally. Immutable kernel identity is kept
in the store's `kernel.json`, separate from deployment information in `meta.json`.
Module autoload, SCMI CPU frequency, installed upgrade and booting the previous
unversioned kernel have been verified on hardware. Booting and returning between
two versioned module ABIs has also been verified. The actual installer and APT
parser pass isolated store-rotation tests; removal of unreferenced old payloads
remains separate acceptance work.

When installing a complete local deb set explicitly, mark the versioned payload
as an automatic dependency after verifying the selector. The selector's exact
dependency and the generated retention rules then retain selected kernels
without making every historical payload a permanent manual installation.

The build needs no root (`dpkg-deb --root-owner-group` on a staged tree) and
takes its firmware from `packaging/firmware/`, checking every file against the
sha256 and size recorded in `packaging/firmware-manifest.json` before packing
it — so `erhai-firmware` builds out of this checkout alone, with no ROM cache
and no network. `--refresh-from-rom` runs the other direction: it extracts the
closure from the pinned stock ROM images and upstream archives again and diffs
that against the tree, which is how a later ROM version gets in. Neither the
AVB signing key nor avbtool ever enters a package.

Building `erhai-audio` also requires GNU m4, `alsatplg` from alsa-utils, and the
original archive pinned in `packaging/audio/source.json`. Pass its path with
`--audio-source`; the default is `cache/audioreach-topology-993a17dc.tar.gz` in
the workspace. The builder verifies the archive, compiles the board source and
decodes the result as a format check. Local topology helpers under `packaging/audio/`
are tracked with the board recipe. Tool versions, hashes, source identity
and the upstream BSD license are included in the audio package. No prebuilt
reference-board topology is renamed or used as a build input.

Two builds of the same inputs produce the same bytes: the version carries a
build id derived from payload and package metadata (`<release>[~dbg]+g<kernel>.b<id>`), the AVB footers
use a salt derived from the image instead of avbtool's random default, and the
archive timestamps are pinned to the kernel commit.

`--debug` includes `erhai.debug=1` in the triplet, builds `erhai-debug` alongside
the device set and marks the version `~dbg`. The normal build omits the optional
package and the flag. The metapackage does not require diagnostics. A root used
for an explicit debug handoff must already contain `erhai-debug`; initramfs no
longer copies binaries or creates persistent diagnostic units in that root.

`erhai-device-support` retires recognized, unowned files generated by earlier
initramfs versions on both normal and debug upgrades. Originals remain under
`/var/lib/erhai/debug/legacy/`; package removal does not reactivate them. An
already enabled diagnostic channel keeps its enabled link during migration.
Unknown edited files are preserved and cause the migration to stop for review.
The revised migration is still awaiting final installed-device validation.

## Safety

`fastboot boot` does not replace boot partitions. A temporary kernel using an
installed root still permits normal filesystem/journal writes there. The
switcher and kernel-package installer write the established active slot's
three boot partitions. Formatting, repartitioning and layout changes require
separate, explicit authorization.

The debug channel is an **unauthenticated root telnet** and filesystem HTTP
server on USB NCM, intended for explicitly enabled local development. Ordinary
installed boots skip the initramfs NCM channel, and the packaged services each
check the kernel flag. Removing `erhai-debug` removes its activation and payload;
the distribution's BusyBox dependency can continue to receive normal updates.
Rootless rescue initramfs sessions still expose their bounded diagnostic channel.
These development tools and images are not a finished production release.

## License

GPL-2.0-only (see LICENSE), matching the integration scripts' SPDX headers.
Kernel and third-party inputs keep their own licenses and authors.

`packaging/firmware/` contains 73 proprietary
Qualcomm, OnePlus and Awinic binaries, redistributed here exactly as they came so that
the port builds from one tree. The project claims no copyright and grants no
license over them, and GPL-2.0-only does not reach them. 60 of them were
extracted from this unit's stock OnePlus OTA, for which no redistribution
permission from OnePlus or Qualcomm has been established. Per-file provenance
is in `packaging/firmware-manifest.json` and the terms are spelled out in
[`packaging/firmware/README.md`](packaging/firmware/README.md).
