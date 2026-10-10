# Testing, Installation and Recovery

[中文](FLASHING.zh-CN.md) · [Project overview](../README.md)

There is no complete installation bundle for new devices yet. This document
describes the tested scope and recovery requirements, not a general partitioning
or first-install procedure. A compiled boot image is insufficient to install Ubuntu.

## Device scope

Testing uses a bootloader-unlocked OnePlus Pad 2 Pro (OPD2413 / erhai), with
16 GB RAM and 512 GB storage. Its existing installation has a separate Linux root
partition and rotates Android/Ubuntu `boot`, `init_boot` and `vendor_boot` images
through the active slot. Other capacities, firmware, layouts and Pad 3 are untested.

## RAM testing

A temporary RAM boot does not replace boot partitions. A temporary kernel using
an installed root can still write files and journals: this differs from a session
whose root filesystem is entirely in RAM.

The RAM desktop session has not completed end-to-end hardware validation;
there is no one-command trial for new users. Developer testing requires matching
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

## Failure and full stock recovery

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
