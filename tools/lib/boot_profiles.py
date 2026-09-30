# SPDX-License-Identifier: GPL-2.0-only
"""Shared boot policy for temporary images and installed GKI triplets."""

CMDLINE = 'rdinit=/init panic=15 erhai.boot=mainline-dev'

# Display blanking is backlight-only in the device package. No experimental
# touch or DSI retention kernel parameters are needed.
PROFILE_EXTRA = {
    'desktop': (
        'erhai.watchdog=900 erhai.session=5400 '
        'erhai.switchroot=1'
    ),
    # The watchdog bounds initramfs. Persistent sessions do not expire.
    'persistent': (
        'erhai.watchdog=600 erhai.root=PARTLABEL=linux_rootfs loglevel=4'
    ),
}
