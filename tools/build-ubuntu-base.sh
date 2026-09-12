#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
# Workspace layout: when this repo is checked out at <workspace>/public/<name>,
# shared inputs and build outputs live in the workspace root; standalone
# checkouts keep everything inside the repo. ERHAI_WORKSPACE overrides both.
if [[ -f $repo/../../AGENTS.md && -d $repo/../../kernel/linux ]]; then
	ws=${ERHAI_WORKSPACE:-$(cd -- "$repo/../.." && pwd)}
else
	ws=${ERHAI_WORKSPACE:-$repo}
fi
base=${UBUNTU_BASE:-"$ws/cache/ubuntu-base-26.04-base-arm64.tar.gz"}
out=${OUT_DIR:-"$ws/out/ubuntu-base"}
expected=b2b46a37324ea1954e93f293fe6d7c2241daf2fc298c4022e6e4caceeed74cab
[[ $(sha256sum "$base" | cut -d' ' -f1) == "$expected" ]] || {
	echo 'Ubuntu Base archive does not match the recorded input.' >&2; exit 1;
}
mkdir -p "$out"
out=$(realpath "$out")
exec 9>"$out/.build.lock"
flock -n 9 || { echo 'Rootfs output is already in use.' >&2; exit 1; }
# Preserve tar ownership/modes without a privileged intermediate extraction.
gzip -dc "$base" | env -u SOURCE_DATE_EPOCH sqfstar \
	-comp zstd -processors "${JOBS:-2}" -no-progress \
	-mkfs-time 0 -all-time 0 -root-time 0 \
	-root-mode 0755 -root-uid 0 -root-gid 0 \
	-default-mode 0755 -default-uid 0 -default-gid 0 \
	"$out/base.squashfs.new" >"$out/build.log" 2>&1
mv "$out/base.squashfs.new" "$out/base.squashfs"
sha256sum "$out/base.squashfs" >"$out/base.sha256"
echo "Built $out/base.squashfs (unconfigured Ubuntu Base, not a desktop image)"
