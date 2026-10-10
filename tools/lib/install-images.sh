#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Private per-device installation staging inside the pinned native container.
set -euo pipefail
root_bytes=$1
home_bytes=$2
owner=$3
test_recovery=$4
root=/work/install-root
test ! -e "$root"
test ! -e /work/images
dpkg -i /work/native/*.deb
unsquashfs -no-progress -processors 4 -d "$root" /input/rootfs.squashfs
mkdir -p /work/images

cat >"$root/etc/fstab" <<'EOF'
PARTLABEL=linux_rootfs / ext4 defaults,noatime 0 1
PARTLABEL=linux_data /home ext4 defaults,noatime 0 2
EOF
printf 'erhai\n' >"$root/etc/hostname"
printf '127.0.0.1 localhost\n127.0.1.1 erhai\n::1 localhost ip6-localhost ip6-loopback\n' >"$root/etc/hosts"
mkdir -p "$root/var/lib/erhai/install"
cp /work/installation.json "$root/var/lib/erhai/install/installation.json"

# Only the original Android boot set and this tablet's calibration are injected.
# Ubuntu's boot set was populated by the kernel package during root assembly.
store=$root/var/lib/erhai/switch
test -f "$store/ubuntu/SHA256SUMS"
test ! -e "$store/android"
mkdir -p "$store/android"
cp /work/android/*.img /work/android/SHA256SUMS "$store/android/"
(cd "$store/android" && sha256sum -c SHA256SUMS)
(cd "$store/ubuntu" && sha256sum -c SHA256SUMS)
cp "$store/ubuntu/SHA256SUMS" /work/ubuntu-SHA256SUMS

mkdir -p "$root/run/erhai-install-inputs"
tar --no-same-owner -xf /work/sensors.tar -C "$root/run/erhai-install-inputs"
cp -a /work/soc0 "$root/run/erhai-install-inputs/"
chroot "$root" /usr/sbin/erhai-sensors-import-registry \
    /run/erhai-install-inputs/sensors --socinfo /run/erhai-install-inputs/soc0
rm -rf "$root/run/erhai-install-inputs"

if [ "$test_recovery" -gt 0 ]; then
    mkdir -p "$root/var/lib/erhai/install-check" "$root/etc/systemd/system/sysinit.target.wants"
    touch "$root/var/lib/erhai/install-check/armed"
    cat >"$root/etc/systemd/system/erhai-install-check.service" <<EOF
[Unit]
Description=Bound the first installed-candidate boot
ConditionPathExists=/var/lib/erhai/install-check/armed
DefaultDependencies=no
After=local-fs.target
Before=basic.target
[Service]
Type=simple
ExecStart=/bin/sh -c 'rm /var/lib/erhai/install-check/armed; cat /proc/sys/kernel/random/boot_id > /var/lib/erhai/install-check/started; sleep $test_recovery; echo expired > /var/lib/erhai/install-check/expired; timeout -k 1 5 sync; /sbin/reboot -f -n bootloader'
TimeoutStopSec=5
EOF
    ln -s ../erhai-install-check.service "$root/etc/systemd/system/sysinit.target.wants/erhai-install-check.service"
fi

# mke2fs copies ownership, hardlinks and extended attributes from the fresh tree.
# These are sparse host files, not block devices; no host filesystem is mounted.
truncate -s "$root_bytes" /work/images/linux_rootfs.raw
truncate -s "$home_bytes" /work/images/linux_data.raw
mke2fs -q -t ext4 -F -b 4096 -m 0 -L ERHAI_ROOT \
    -E lazy_itable_init=0,lazy_journal_init=0 -d "$root" /work/images/linux_rootfs.raw
mke2fs -q -t ext4 -F -b 4096 -m 0 -L ERHAI_HOME \
    -E lazy_itable_init=0,lazy_journal_init=0 /work/images/linux_data.raw
e2fsck -fn /work/images/linux_rootfs.raw
e2fsck -fn /work/images/linux_data.raw
mke2fs -V 2>/work/mke2fs-version.txt
sha256sum /usr/sbin/mke2fs /usr/sbin/e2fsck > /work/filesystem-tools.sha256
chown -R "$owner" /work/images /work/ubuntu-SHA256SUMS
rm -rf "$root"
