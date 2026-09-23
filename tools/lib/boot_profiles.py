# SPDX-License-Identifier: GPL-2.0-only
"""Shared boot policy for temporary images and installed GKI triplets."""

CMDLINE = 'rdinit=/init panic=15 erhai.boot=mainline-dev'

# Both profiles use the retained-panel kernel workaround. Its shared touch
# controller must retain firmware too; remove both workarounds together.
DISPLAY_EXTRA = 'nt36536_ts.retain_on_blank=1 msm.retain_dsi_link=1'
PROFILE_EXTRA = {
    'desktop': (
        'erhai.watchdog=900 erhai.session=5400 '
        'erhai.rootfs=http://192.168.77.10:8000/rootfs-s5.squashfs '
        'erhai.switchroot=1 ' + DISPLAY_EXTRA
    ),
    # The watchdog bounds initramfs. Persistent sessions do not expire.
    'persistent': (
        'erhai.watchdog=600 erhai.root=PARTLABEL=linux_rootfs loglevel=4 '
        + DISPLAY_EXTRA
    ),
}
