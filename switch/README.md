# Dual boot: rotating the boot triplet through the active slot

Android and mainline Ubuntu take turns in the **active** A/B slot. Whichever
system is not installed lives as three files on the Linux root filesystem.

This is not the obvious design, and the obvious ones do not work on this
tablet:

* **Boot the other slot.** The B slot carries a whole older firmware chain
  (xbl/tz/abl from an earlier ColorOS). It never completes a boot, and making
  it bootable means writing 30+ partitions including anti-rollback-sensitive
  ones.
* **Put Linux in `recovery`.** This ABL treats the recovery partition as a
  pure ramdisk: with a kernel in it the tablet drops to fastboot, and the
  kernel always comes from `boot`. The stock kernel is built without
  `CONFIG_KEXEC`, so there is no second hop either.

What is left is one slot, two systems, and a switch that swaps the three boot
partitions as a set.

## Hard requirement: AVB footers

`vbmeta` on this device describes `boot` as an AVB **chain partition**, which
means the bootloader reads a vbmeta structure out of the tail of the boot
partition on every cold boot. An image without that footer is not a failed
signature check but malformed metadata, and an *unlocked* bootloader still
refuses it — it drops to fastboot, for an ordinary Android boot as much as for
ours. An unknown key is fine (`verifiedbootstate=orange` tolerates it); a
missing structure is not.

So every image that goes into `boot` / `init_boot` / `vendor_boot` is signed:

```sh
../tools/sign-boot-triplet.py --triplet out/mainline-gki-mNNN \
    --stock cache/stock-c34/images \
    --key <your test key>.pem --output out/mainline-gki-mNNN-avb
```

Partition sizes and rollback indices come from the stock images of the
firmware the device is actually running, so they are matched rather than
guessed. The footer sits in the last pages of the *partition*, which is why
the switcher always writes whole partitions.

## Files

```
erhai-switch                        the switcher; runs on both systems
erhai-switch-install-ubuntu-images   populate the store from a signed triplet
ksu-module/                          KernelSU module: the script + one button
tests/switch-selftest.sh             decision-logic self-test (files, not a device)
```

## Store layout

On the Linux root filesystem, so both systems see the same archive. Android
mounts it for the duration of a switch and unmounts it afterwards.

```
/var/lib/erhai/switch/
  ubuntu/       boot.img init_boot.img vendor_boot.img SHA256SUMS meta.json
  ubuntu.prev/  the previous Ubuntu triplet, for a rollback without a host
  android/      refreshed from the live slot before every switch to Ubuntu
  state.json    what is in the slot, which slot, when, which hashes
  switch.log
```

`android/` is never shipped and never hand-maintained: it is re-read from the
slot each time, so an Android OTA or a KernelSU change needs no manual sync.

## Use

```sh
erhai-switch status          # what is in the slot and in the store
erhai-switch verify          # re-hash everything; exit non-zero if unusable
erhai-switch stash-android   # archive the live slot (refuses a Ubuntu slot)
erhai-switch to-ubuntu       # archive Android, install Ubuntu, reboot
erhai-switch to-android      # install the archive, reboot
```

Root: `sudo`/`pkexec` on Ubuntu, a KernelSU root shell on Android.
`--no-reboot` stops before the reboot, `--dry-run` writes nothing at all.

Safety rules the script enforces, in this order: a set with a missing or
non-matching `SHA256SUMS` is refused before any write; every partition is
written whole, synced, read back and compared; a read-back that does not match
rewrites the slot from the other set and exits non-zero **without rebooting**;
and a slot whose boot image already announces itself as ours is never archived
as the Android set.

Nothing else is touched: not `recovery`, not `misc`, not `vbmeta`, not the
slot attributes, not the B slot, not xbl/tz. The slot suffix is read, never
written.

## Finding the active slot

Android 15 puts `androidboot.slot_suffix` in bootconfig. **A mainline kernel
on this ABL gets no slot suffix at all** — not on the command line, and
`/proc/bootconfig` comes up empty (the bootloader appends its own
`oplusboot.*` arguments instead). So on Linux the switcher falls back to the
GPT attribute the bootloader itself uses to choose a slot: bit 50, "active",
the same bit `fastboot --set-active` writes. `--slot _a` overrides everything.

## Known costs

* An Android OTA rewrites `recovery` and, when it updates the other slot, the
  images there. It does not touch the Linux root or the store.
* A factory reset or a large ColorOS upgrade may rebuild the GPT to the stock
  layout and take the Linux partitions with it. Keep backups.
* While Ubuntu is in the slot, recovery mode runs the mainline kernel against
  the stock recovery ramdisk and panics back into Ubuntu. Switch to Android
  before using stock recovery.
* An interrupted write needs a host with fastboot. The script narrows the
  window (verify, then write, then read back) but cannot remove it.

## Testing

`tests/switch-selftest.sh` runs the switcher against ordinary files with
`--dev-dir`, covering set validation, the archive/install/read-back cycle, the
refusal paths and dry-run. It re-execs itself under `unshare -r`, so it needs
no privileges.

It says nothing about the device: not about UFS, not about AVB, not about
whether the tablet boots afterwards. Those are device experiments, and the
cold-boot validation of a signed triplet in the active slot is recorded with
the project's device evidence.
