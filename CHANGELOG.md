# Changelog

## v0.2.0

Device and sensor packages are numbered 0.2.0 and install over v0.1.0 with APT;
see "Upgrading an existing installation" in [FLASHING](docs/FLASHING.md).

- System suspend defaults to s2idle. On the installed tablet, 300-second
  RTC-timed suspends in both display modes resume the display, touch, Wi-Fi and
  sensors ([#2](https://github.com/yzddmr6/onepluspad-2pro-mainline/pull/2)).
- Opt-in power-key suspend through `/etc/erhai/power-key-action`; the default
  is still lock and blank
  ([#3](https://github.com/yzddmr6/onepluspad-2pro-mainline/pull/3)).
- Compass and gyroscope readings through iio-sensor-proxy
  ([#1](https://github.com/yzddmr6/onepluspad-2pro-mainline/pull/1)).
- GNOME idle dimming is off, because the panel is never blanked automatically
  ([#4](https://github.com/yzddmr6/onepluspad-2pro-mainline/pull/4)).
- Notes on the panel brightness paths
  ([#6](https://github.com/yzddmr6/onepluspad-2pro-mainline/pull/6)).
- Kernel `erhai-v0.2.0`: the IPCC and GLINK drivers return to Linux v7.2 after
  the default-off suspend wake diagnostics are removed.
- H.264 hardware decoding is verified on the tablet. Known issue: Showtime aborts
  on a Mesa freedreno assertion when it draws video frames.

Thanks to @Pidbid for #1–#4 and #6.

## v0.1.0

Developer source preview for the OnePlus Pad 2 Pro (OPD2413).

- Separate integration and device-kernel repositories, with pinned source inputs.
- Component packages for the kernel, firmware and Ubuntu device integration.
- Included device firmware, stock boot build inputs and small upstream tool
  sources, with one command to prepare inputs and optional Ubuntu ISO extraction.
- Root filesystem assembly from official Ubuntu Desktop ARM64 inputs.
- Clean Linux reinstallation on the tested existing slot-A layout, with host
  backups and full boot-partition readback.
- First-time partition preparation for the 512 GB model using the distribution
  partitioning tool; partition creation, Android data reset, Linux first boot and
  dual-boot switching tested on hardware.
- KernelSU module packaging and shared switch/update locking; failed writes stop
  without automatic rollback and cannot replace the Android backup.
- Dual-boot switching for the documented installation layout and optional USB diagnostics.

Tested hardware support and known limitations are maintained in the
[README](README.md#hardware-support). Build and recovery instructions are in
[BUILD](docs/BUILD.md) and [FLASHING](docs/FLASHING.md).
