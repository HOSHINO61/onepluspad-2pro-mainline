# Testing, Installation and Recovery

[中文](FLASHING.zh-CN.md) · [Project overview](../README.md)

This guide covers Linux reinstallation, system switching and Android recovery
on an existing dual-boot layout. Stock devices without Linux partitions are
outside its scope; the project does not provide a general repartitioning tool.

## Device scope

Testing uses a bootloader-unlocked OnePlus Pad 2 Pro (OPD2413 / erhai), with
16 GB RAM and 512 GB storage. Its existing installation has a separate Linux root
partition and rotates Android/Ubuntu `boot`, `init_boot` and `vendor_boot` images
through the active slot. Other capacities, firmware, layouts and Pad 3 are untested.

## RAM testing

A temporary RAM boot does not replace boot partitions. A temporary kernel using
an installed root can still write files and journals: this differs from a session
whose root filesystem is entirely in RAM.

The development RAM desktop has passed boot, graphics-driver and bounded
recovery checks. There is no one-command trial for new users. Developer testing requires matching
boot images, a root filesystem and checksums, with recovery after the session
timeout established in advance. Do not combine artifacts from unrelated builds.

Development sessions need explicit device selection, bounded timeouts and
userspace recovery. Panic/userspace timers cannot recover every hardware lockup.
Unauthenticated USB diagnostics are for trusted direct connections only.

## Return to Android on an existing installation

These steps require the established project layout and complete switcher storage.

- In Ubuntu, use **Switch to Android**, enter the administrator password and wait
  for the automatic reboot.
- In Android, use the installed KernelSU switching module; see the
  [switcher reference](../switch/README.md) for its installation and path conventions.
- If battery charge falls in Linux or Fastboot, return to Android to charge and
  confirm that capacity has recovered before continuing.

Both switching directions have been tested on the existing layout. Switching
writes three boot partitions; it does not apply to a fresh tablet, missing
rollback images or a different layout.

Automatic recovery from an interrupted write is incomplete. Do not rely on
repeating a switch to repair a mixed boot set. Keep the complete Android triplet
backup on the host and use the Fastboot recovery procedure below after an interruption.

## Clean installation on an existing Linux layout

The installer targets OPD2413 devices that already have `linux_rootfs` and
`linux_data` partitions and **active slot A**. Clean reinstallation, live boot
partition readback, normal reboot and both switching directions have been tested
on this layout. It retains
Android data and the GPT, replaces both Linux filesystems, and uses the existing
switcher to activate the Ubuntu boot triplet. Stock devices without Linux
partitions are outside this procedure.

The host needs amd64 Linux, rootful Docker, Android platform-tools, ARM64 binfmt, a native C compiler and `dpkg-deb`. Start with Android
running, battery at least 50%, USB debugging, working KernelSU root and this
project's switch module installed. Firmware must match the [tested combination](../packaging/installation.json); another OTA on the same model is not automatically accepted. Use the build guide's `rootfs.squashfs` and
its adjacent `manifest.json`. Allow space for the private installation images.
The installer builds the pinned AOSP `ext2simg` tool, which uses the ext4 allocation
bitmap and preserves zero metadata needed when replacing an older filesystem.

`backup` saves Android boot images, partition tables and device data; it does
not back up Linux user files. Export any Linux files you want to keep before
proceeding: this backup cannot restore them.

From the project directory, use the tablet's serial from `adb devices`:

```sh
device_serial=DEVICE_SERIAL
install_work="$PWD/out/install-device"
python3 tools/install.py --serial "$device_serial" --work "$install_work" --phase backup
python3 tools/install.py --serial "$device_serial" --work "$install_work" --phase prepare \
  --rootfs out/desktop-root/rootfs.squashfs
python3 tools/install.py --serial "$device_serial" --work "$install_work" --phase install --erase-linux
```

The first two phases back up the tablet's boot set and calibration and prepare
images on the host. `--erase-linux` explicitly permits deleting the Linux system
and user files. The installer checks device, partition and input identities,
erases and flashes the two Linux partitions, returns to Android, then invokes
the switcher. It reads back all three boot partitions before rebooting Ubuntu.
Complete first-run account setup on the tablet.

Keep `install_work` private: it contains this tablet's backups and calibration,
not public release assets. A completed write still requires first-boot, touch,
desktop and dual-boot checks.

If Ubuntu fails to start, enter Fastboot and restore the verified Android set:

```sh
python3 tools/install.py --serial "$device_serial" --work "$install_work" --phase restore-android
```

This restores and verifies the Android boot triplet. The Linux partitions retain
the newly installed contents.

## Failure and full stock recovery

If the tablet stops responding, hold **Power + Volume Up for about 15 seconds**.
Release when the screen turns off or the OnePlus logo appears. If it stays off,
press Power to start it. This combination has been used to recover the OPD2413.

Preserve errors, image versions and backups after a failed boot. Establish the
current system and completed writes before proceeding. Do not repeatedly rerun
installation or mix versions of the boot triplet; check all three partitions together.

Returning to the existing Android system does not restore a factory partition
layout. Full stock recovery also depends on matching firmware, layout and user
data. A general recovery procedure has not been independently hardware-validated
by this project.

Keep this tablet's boot-image and calibration backups. Never restore another
device's calibration, addresses or persist partition. Keep the bootloader unlocked
while non-stock images remain installed.
