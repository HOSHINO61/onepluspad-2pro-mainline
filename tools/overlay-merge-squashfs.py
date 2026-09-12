#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Merge the Ubuntu base tarball with an overlayfs upper-dir tar into a new
zstd squashfs, entirely unprivileged: ownership and modes travel inside the
tar streams, and later (upper) entries replace earlier (base) ones by path.

Usage: overlay-merge-squashfs.py BASE.tar.gz UPPER.tar OUT.squashfs
"""
import subprocess
import sys
import tarfile


def stream_upper_into_base(base_tgz, upper_tar, out_tar):
    # Materialize the upper's path set so base entries it overrides can be
    # dropped from the stream. Deletions do not occur (no whiteouts: the
    # upper comes from an apt-install session which only adds/replaces).
    with tarfile.open(upper_tar) as up:
        upper_names = {m.name.lstrip("./") for m in up.getmembers()}
    with open(base_tgz, "rb") as probe:
        gz = probe.read(2) == b"\x1f\x8b"
    base = subprocess.Popen((["gzip", "-dc", base_tgz] if gz else ["cat", base_tgz]),
                            stdout=subprocess.PIPE)
    with tarfile.open(fileobj=base.stdout, mode="r|") as tin, \
            tarfile.open(out_tar, "w") as tout:
        for member in tin:
            name = member.name.lstrip("./")
            if name and name in upper_names:
                continue  # upper wins
            tout.addfile(member, tin.extractfile(member) if member.isreg() else None)
        with tarfile.open(upper_tar) as up:
            for member in up.getmembers():
                if member.isdir():
                    tout.addfile(member)
                elif member.isreg() or member.issym() or member.islnk():
                    tout.addfile(member, up.extractfile(member) if member.isreg() else None)
                # whiteouts/char-dev placeholders are skipped by design
    return base.wait()


def main():
    base_sqfs, upper_tar, out_sqfs = sys.argv[1], sys.argv[2], sys.argv[3]
    merged = out_sqfs + ".merged.tar"
    rc = stream_upper_into_base(base_sqfs, upper_tar, merged)
    if rc != 0:
        sys.exit(f"sqfs2tar failed: {rc}")
    with open(merged, "rb") as tar_in:
        proc = subprocess.run(
            ["sqfstar", "-comp", "zstd", "-no-progress", "-mkfs-time", "0",
             "-all-time", "0", "-root-time", "0", out_sqfs + ".new"],
            stdin=tar_in)
    if proc.returncode != 0:
        sys.exit(f"sqfstar failed: {proc.returncode}")
    subprocess.run(["mv", out_sqfs + ".new", out_sqfs], check=True)
    print(f"Built {out_sqfs} (merged tar kept at {merged})")


if __name__ == "__main__":
    main()
