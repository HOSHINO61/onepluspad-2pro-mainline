# Changelog

## v0.1.0

Developer source preview for the OnePlus Pad 2 Pro (OPD2413).

- Separate integration and device-kernel repositories, with pinned source inputs.
- Component packages for the kernel, firmware and Ubuntu device integration.
- Included device firmware, stock boot build inputs and small upstream tool
  sources, with one command to prepare inputs and optional Ubuntu ISO extraction.
- Root filesystem assembly from official Ubuntu Desktop ARM64 inputs.
- Dual-boot switching for the documented installation layout and optional USB diagnostics.

Tested hardware support and known limitations are maintained in the
[README](README.md#hardware-support). Build and recovery instructions are in
[BUILD](docs/BUILD.md) and [FLASHING](docs/FLASHING.md).
