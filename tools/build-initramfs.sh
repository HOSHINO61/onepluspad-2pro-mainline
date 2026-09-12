#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
umask 022
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
# Workspace layout: when this repo is checked out at <workspace>/public/<name>,
# shared inputs and build outputs live in the workspace root; standalone
# checkouts keep everything inside the repo. ERHAI_WORKSPACE overrides both.
if [[ -f $repo/../../AGENTS.md && -d $repo/../../kernel/linux ]]; then
	ws=${ERHAI_WORKSPACE:-$(cd -- "$repo/../.." && pwd)}
else
	ws=${ERHAI_WORKSPACE:-$repo}
fi
busybox=${BUSYBOX:-"$ws/cache/busybox-arm64"}
out=${OUT_DIR:-"$ws/out/initramfs-dev"}
gen_init_cpio=${GEN_INIT_CPIO:-"$ws/out/kernel-firstboot/usr/gen_init_cpio"}
expected=52151e7f322f926b64049cdaa1410dc3ea6485525e0624b05813791c219ae933
[[ $(sha256sum "$busybox" | cut -d' ' -f1) == "$expected" ]] || {
	echo 'Expected the pinned Ubuntu ARM64 static BusyBox; see README.md (inputs).' >&2
	exit 1
}
[[ -x $gen_init_cpio ]] || {
	echo "gen_init_cpio not found at $gen_init_cpio (plain cpio cannot create device nodes)." >&2
	exit 1
}
mkdir -p "$out"
out=$(realpath "$out")
profile=${PROFILE:-acm}
case "$profile" in
acm) init_src="$repo/initramfs/init"; usb_src="$repo/initramfs/usb-acm"
	apps='sh mount mkdir cat uname sleep setsid cttyhack getty ln ls dmesg poweroff reboot'
	image_name=initramfs.cpio.gz ;;
ncm) init_src="$repo/initramfs/init-ncm"; usb_src="$repo/initramfs/usb-ncm"
	apps='sh mount mkdir cat cp uname sleep ip ln touch udhcpd httpd telnetd dmesg reboot poweroff ls dd sha256sum sync tr date mv fdisk readlink'
	image_name=initramfs-ncm.cpio.gz
	# Novatek NT36536 TDDI loses its RAM firmware on every panel prepare; the
	# built-in touch driver requests it from the rootfs.
	fw_files="$ws/out/nt36536-fw/nt36536-xn242.bin"
	# ADSP PIL firmware: mdt container + sparsely numbered adsp.bNN segments,
	# resolved by the loader next to firmware-name qcom/sm8750/erhai/adsp.mdt.
	adsp_src="$ws/out/adsp-fw/modem-image"
	adsp_dst=/lib/firmware/qcom/sm8750/erhai ;;
*) echo "Unknown PROFILE '$profile' (acm|ncm)." >&2; exit 1 ;;
esac
exec 9>"$out/.build.lock"
flock -n 9 || { echo 'Initramfs output is already in use.' >&2; exit 1; }
stage=$(mktemp -d "$out/stage.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
{
	sha256sum "$init_src" "$usb_src" | cut -d' ' -f1
	printf '%s\n' "$expected"
} | sha256sum | cut -d' ' -f1 >"$stage/build-id"
{
	for d in / /bin /dev /proc /sys /run /etc; do
		printf 'dir %s 0755 0 0\n' "$d"
	done
	# /dev must not be empty at PID1: devtmpfs automount timing is not a contract.
	printf 'nod /dev/console 0600 0 0 c 5 1\n'
	printf 'nod /dev/null 0666 0 0 c 1 3\n'
	printf 'file /init %s 0755 0 0\n' "$init_src"
	printf 'file /bin/%s %s 0755 0 0\n' "$(basename -- "$usb_src")" "$usb_src"
	printf 'file /bin/busybox %s 0755 0 0\n' "$busybox"
	printf 'file /etc/build-id %s 0644 0 0\n' "$stage/build-id"
	if [[ -n ${fw_files:-} ]]; then
		printf 'dir /lib 0755 0 0\n'
		printf 'dir /lib/firmware 0755 0 0\n'
		printf 'dir /lib/firmware/novatek 0755 0 0\n'
	fi
	for fw in ${fw_files:-}; do
		[[ -f $fw ]] || { echo "Firmware blob not found: $fw" >&2; exit 1; }
		printf 'file /lib/firmware/novatek/%s %s 0644 0 0\n' "$(basename -- "$fw")" "$fw"
	done
	if [[ -n ${adsp_src:-} ]]; then
		[[ -f $adsp_src/adsp.mdt ]] || { echo "ADSP mdt not found: $adsp_src/adsp.mdt" >&2; exit 1; }
		for d in /lib/firmware/qcom /lib/firmware/qcom/sm8750 "$adsp_dst"; do
			printf 'dir %s 0755 0 0\n' "$d"
		done
		for seg in "$adsp_src"/adsp.mdt "$adsp_src"/adsp.b* \
			"$adsp_src"/adsp_dtb.mdt "$adsp_src"/adsp_dtb.b*; do
			[[ -f $seg ]] || continue
			printf 'file %s/%s %s 0644 0 0\n' "$adsp_dst" "$(basename -- "$seg")" "$seg"
		done
	fi
	for app in $apps; do
		printf 'slink /bin/%s busybox 0777 0 0\n' "$app"
	done
} >"$stage/cpio.list"
"$gen_init_cpio" -t 0 "$stage/cpio.list" 2>"$out/cpio.log" | gzip -n >"$out/$image_name"
sha256sum "$out/$image_name" >"$out/$image_name.sha256"
echo "Built $out/$image_name (profile $profile, RAM userspace only, no boot image)"
