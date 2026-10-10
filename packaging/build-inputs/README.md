# Pinned build tools

This directory contains the original AOSP mkbootimg and AVB source archives
identified in [kernel/source.json](../../kernel/source.json). Their original
source and license notices remain inside each archive. `tools/prepare-inputs.py`
verifies and unpacks them into the build cache; it does not install host packages.

The small source archives are included so a build does not depend on regenerated
upstream tarballs retaining identical compression metadata. The tools are not
forked or patched here. AudioReach's original source archive is similarly kept
under `packaging/audio/`, with its own source manifest and BSD license.

BusyBox is downloaded from the pinned Ubuntu package URL. Large Ubuntu images,
kernel and Mesa sources remain upstream downloads or separate Git checkouts.
