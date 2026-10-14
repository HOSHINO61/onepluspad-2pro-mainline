#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Mark that a system suspend cycle is under way.
#
# erhai-power-key reads this to tell the press that resumes the tablet apart
# from a press that means "sleep now". Two things make the pre phase the right
# place for it:
#
#   * it runs before the tablet suspends, so the flag is already on disk when
#     the press that resumes it is delivered — no race. A marker written by the
#     post phase is racy, because userspace is thawed before that hook runs, and
#     the service can read the resuming press first and suspend again.
#   * the service cannot measure the suspend itself: CLOCK_MONOTONIC keeps
#     running across s2idle on this board, so an elapsed-time test sees a gap of
#     zero.
#
# The service deletes the flag as it consumes it, so a later press is handled
# normally. The post timestamp lets it discard flags left by another wake
# source or a failed suspend once the resume-press window has elapsed.
case "$1" in
    pre)
        : > /run/erhai-suspend-cycle
        rm -f /run/erhai-suspend-resumed
        ;;
    post)
        : > /run/erhai-suspend-resumed
        ;;
    *)
        exit 0
        ;;
esac
exit 0
