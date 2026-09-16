// SPDX-License-Identifier: GPL-2.0-only
/*
 * wb-capture - capture the pixels a DRM/KMS pipeline is actually scanning
 * out, via the driver's writeback connector, without disturbing the running
 * modeset. Built to draw the line on "kernel says the display works but the
 * panel stays black": if the writeback frame holds the expected content,
 * everything up to the DSI encoder input is correct and the loss is on the
 * panel side (link, DSC decode, bias/backlight).
 *
 * No libdrm, no libc-DRM helpers: raw UAPI ioctls so the binary can be a
 * single static file in a bare initramfs. Output is one raw frame file per
 * capture plus a text report on stdout.
 *
 * Usage: wb-capture [--dev /dev/dri/card0] [--fb0-pattern [/dev/fb0]]
 *                   [--prefix /run/evidence/wb]
 *
 * Frame 0 is whatever the CRTC scans when the tool starts (e.g. fbcon text).
 * With --fb0-pattern the tool then paints color bars + edge stress rows into
 * the fbdev scanout buffer and captures frame 1. Raw layout (geometry,
 * fourcc, pitch) goes to <prefix>-info via stdout.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

/* Raw kernel-tree uapi headers carry __user annotations that a headers_install
 * pass would strip; define it away for this self-contained build. */
#ifndef __user
#define __user
#endif
#include <drm/drm.h>
#include <drm/drm_mode.h>
#include <drm/drm_fourcc.h>
#include <linux/fb.h>

#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))

static void die(const char *what)
{
	fprintf(stderr, "wb-capture: %s: %s\n", what, strerror(errno));
	exit(1);
}

static int xioctl(int fd, unsigned long req, void *arg, const char *what)
{
	int ret;
	do {
		ret = ioctl(fd, req, arg);
	} while (ret < 0 && errno == EINTR);
	if (ret < 0)
		die(what);
	return ret;
}

/* ---------- property helpers ---------- */

static uint32_t find_prop(int fd, uint32_t obj_id, uint32_t obj_type,
			  const char *name, uint64_t *value_out)
{
	struct drm_mode_obj_get_properties props = { .obj_id = obj_id, .obj_type = obj_type };
	uint32_t ids[64];
	uint64_t values[64];
	uint32_t found = 0;

	xioctl(fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &props, "OBJ_GETPROPERTIES(count)");
	if (props.count_props > ARRAY_SIZE(ids)) {
		fprintf(stderr, "wb-capture: %u props on object %u, need buffer\n",
			props.count_props, obj_id);
		exit(1);
	}
	props.props_ptr = (uintptr_t)ids;
	props.prop_values_ptr = (uintptr_t)values;
	xioctl(fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &props, "OBJ_GETPROPERTIES(list)");

	for (uint32_t i = 0; i < props.count_props; i++) {
		struct drm_mode_get_property p = { .prop_id = ids[i] };
		xioctl(fd, DRM_IOCTL_MODE_GETPROPERTY, &p, "GETPROPERTY");
		if (!strncmp(p.name, name, DRM_PROP_NAME_LEN)) {
			found = ids[i];
			if (value_out)
				*value_out = values[i];
			break;
		}
	}
	return found;
}

static void read_format_blob(int fd, uint64_t blob_id, uint32_t *fmts, uint32_t *count)
{
	struct drm_mode_get_blob blob = { .blob_id = (uint32_t)blob_id };

	*count = 0;
	if (!blob_id)
		return;
	xioctl(fd, DRM_IOCTL_MODE_GETPROPBLOB, &blob, "GETPROPBLOB(count)");
	uint32_t n = blob.length / 4;
	if (n > 32)
		n = 32;
	blob.length = n * 4;
	blob.data = (uintptr_t)fmts;
	xioctl(fd, DRM_IOCTL_MODE_GETPROPBLOB, &blob, "GETPROPBLOB(data)");
	*count = n;
}

static const char *fourcc_str(uint32_t f)
{
	static char buf[5];
	buf[0] = f & 0x7f; buf[1] = (f >> 8) & 0x7f;
	buf[2] = (f >> 16) & 0x7f; buf[3] = (f >> 24) & 0x7f; buf[4] = 0;
	return buf;
}

/* ---------- fbdev pattern ---------- */

static void paint_fb0_pattern(const char *fbdev)
{
	int fb = open(fbdev, O_RDWR);
	struct fb_var_screeninfo var;
	struct fb_fix_screeninfo fix;

	if (fb < 0) {
		printf("fb0-pattern: open %s failed: %s (skipping)\n", fbdev, strerror(errno));
		return;
	}
	if (ioctl(fb, FBIOGET_VSCREENINFO, &var) || ioctl(fb, FBIOGET_FSCREENINFO, &fix)) {
		printf("fb0-pattern: geometry query failed: %s (skipping)\n", strerror(errno));
		close(fb);
		return;
	}
	printf("fb0-pattern: %ux%u bpp=%u line=%u\n", var.xres, var.yres,
	       var.bits_per_pixel, fix.line_length);
	if (var.bits_per_pixel != 32) {
		printf("fb0-pattern: bpp %u unsupported (skipping)\n", var.bits_per_pixel);
		close(fb);
		return;
	}
	size_t len = (size_t)fix.line_length * var.yres;
	uint8_t *map = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_SHARED, fb, 0);
	if (map == MAP_FAILED) {
		printf("fb0-pattern: mmap failed: %s (skipping)\n", strerror(errno));
		close(fb);
		return;
	}
	/* Eight vertical bars: white, yellow, cyan, green, magenta, red, blue,
	 * black. A channel swap or a dead half-link is immediately visible. */
	static const uint32_t bars[8] = {
		0x00ffffff, 0x00ffff00, 0x0000ffff, 0x0000ff00,
		0x00ff00ff, 0x00ff0000, 0x000000ff, 0x00000000,
	};
	for (uint32_t y = 0; y < var.yres; y++) {
		uint32_t *row = (uint32_t *)(map + (size_t)y * fix.line_length);
		for (uint32_t x = 0; x < var.xres; x++) {
			uint32_t px = bars[x * 8 / var.xres];
			/* Top 48 rows: alternating single-pixel B/W columns to
			 * stress DSC slice packing. Next 48: 8-pixel checker. */
			if (y < 48)
				px = (x & 1) ? 0x00ffffff : 0x00000000;
			else if (y < 96)
				px = ((x / 8 + y / 8) & 1) ? 0x00ffffff : 0x00000000;
			/* Bottom 96 rows: horizontal 1px and 4px stripes. */
			else if (y >= var.yres - 96 && y >= var.yres - 48)
				px = (y & 1) ? 0x00ffffff : 0x00000000;
			else if (y >= var.yres - 48)
				px = (y & 4) ? 0x00ffffff : 0x00000000;
			row[x] = px;
		}
	}
	munmap(map, len);
	close(fb);
	printf("fb0-pattern: painted into %s\n", fbdev);
}

/* ---------- main capture ---------- */

int main(int argc, char **argv)
{
	const char *card = "/dev/dri/card0";
	const char *fbdev = NULL;
	const char *prefix = "/run/evidence/wb";

	alarm(20); /* a stuck capture must never wedge the boot session */

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--dev") && i + 1 < argc)
			card = argv[++i];
		else if (!strcmp(argv[i], "--fb0-pattern")) {
			fbdev = "/dev/fb0";
			if (i + 1 < argc && argv[i + 1][0] != '-')
				fbdev = argv[++i];
		} else if (!strcmp(argv[i], "--prefix") && i + 1 < argc)
			prefix = argv[++i];
		else {
			fprintf(stderr, "usage: wb-capture [--dev CARD] [--fb0-pattern [FB]] [--prefix P]\n");
			return 2;
		}
	}

	int fd = open(card, O_RDWR | O_CLOEXEC);
	if (fd < 0)
		die(card);

	struct drm_set_client_cap cap = { 0 };
	cap.capability = DRM_CLIENT_CAP_UNIVERSAL_PLANES; cap.value = 1;
	xioctl(fd, DRM_IOCTL_SET_CLIENT_CAP, &cap, "cap universal");
	cap.capability = DRM_CLIENT_CAP_ATOMIC; cap.value = 1;
	xioctl(fd, DRM_IOCTL_SET_CLIENT_CAP, &cap, "cap atomic");
	cap.capability = DRM_CLIENT_CAP_WRITEBACK_CONNECTORS; cap.value = 1;
	xioctl(fd, DRM_IOCTL_SET_CLIENT_CAP, &cap, "cap writeback");

	struct drm_mode_card_res res = { 0 };
	xioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res, "GETRESOURCES(count)");
	uint32_t crtcs[16], conns[32], encs[32];
	if (res.count_crtcs > ARRAY_SIZE(crtcs) || res.count_connectors > ARRAY_SIZE(conns) ||
	    res.count_encoders > ARRAY_SIZE(encs)) {
		fprintf(stderr, "wb-capture: resource counts too large\n");
		return 1;
	}
	res.crtc_id_ptr = (uintptr_t)crtcs;
	res.connector_id_ptr = (uintptr_t)conns;
	res.encoder_id_ptr = (uintptr_t)encs;
	xioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res, "GETRESOURCES(list)");
	printf("card %s: crtcs=%u connectors=%u encoders=%u\n", card,
	       res.count_crtcs, res.count_connectors, res.count_encoders);

	uint32_t wb_conn = 0, src_conn = 0, src_crtc = 0;
	struct drm_mode_modeinfo mode = { 0 };

	for (uint32_t i = 0; i < res.count_connectors; i++) {
		/* We only need status/encoder_id, which a count-only call fills.
		 * A second pass with counts set but NULL array pointers would make
		 * the kernel copy_to_user(NULL) -> -EFAULT, so keep every count at
		 * zero here. */
		struct drm_mode_get_connector c = { .connector_id = conns[i] };
		xioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &c, "GETCONNECTOR");
		printf("connector %u type=%u-%u connection=%u encoder=%u\n",
		       c.connector_id, c.connector_type, c.connector_type_id,
		       c.connection, c.encoder_id);
		if (c.connector_type == DRM_MODE_CONNECTOR_WRITEBACK && !wb_conn)
			wb_conn = c.connector_id;
		if (c.connection == 1 /* connector_status_connected */ && !src_conn && c.encoder_id) {
			struct drm_mode_get_encoder e = { .encoder_id = c.encoder_id };
			xioctl(fd, DRM_IOCTL_MODE_GETENCODER, &e, "GETENCODER");
			if (e.crtc_id) {
				src_conn = c.connector_id;
				src_crtc = e.crtc_id;
			}
		}
	}
	if (!wb_conn) {
		printf("no writeback connector on %s; nothing to capture\n", card);
		return 3;
	}
	if (!src_crtc) {
		printf("no active CRTC behind a connected connector; nothing to capture\n");
		return 4;
	}

	struct drm_mode_crtc crtc = { .crtc_id = src_crtc };
	xioctl(fd, DRM_IOCTL_MODE_GETCRTC, &crtc, "GETCRTC");
	if (!crtc.mode_valid) {
		printf("CRTC %u has no valid mode; nothing to capture\n", src_crtc);
		return 4;
	}
	mode = crtc.mode;
	printf("source: connector %u crtc %u mode %ux%u clock=%ukHz\n",
	       src_conn, src_crtc, mode.hdisplay, mode.vdisplay, mode.clock);

	uint64_t fmt_blob = 0, cur_crtc = 0;
	uint32_t p_crtc = find_prop(fd, wb_conn, DRM_MODE_OBJECT_CONNECTOR, "CRTC_ID", &cur_crtc);
	uint32_t p_fb = find_prop(fd, wb_conn, DRM_MODE_OBJECT_CONNECTOR, "WRITEBACK_FB_ID", NULL);
	uint32_t p_fence = find_prop(fd, wb_conn, DRM_MODE_OBJECT_CONNECTOR, "OUT_FENCE_PTR", NULL);
	uint32_t p_fmts = find_prop(fd, wb_conn, DRM_MODE_OBJECT_CONNECTOR,
				    "WRITEBACK_PIXEL_FORMATS", &fmt_blob);
	if (!p_crtc || !p_fb) {
		printf("writeback connector %u lacks CRTC_ID/WRITEBACK_FB_ID props\n", wb_conn);
		return 3;
	}
	uint32_t fmts[32]; uint32_t nfmts = 0;
	if (p_fmts && fmt_blob) {
		read_format_blob(fd, fmt_blob, fmts, &nfmts);
		printf("writeback formats:");
		for (uint32_t i = 0; i < nfmts; i++)
			printf(" %s", fourcc_str(fmts[i]));
		printf("\n");
	}

	static const struct { uint32_t fourcc; uint8_t bpp; } prefs[] = {
		{ DRM_FORMAT_XRGB8888, 32 }, { DRM_FORMAT_ARGB8888, 32 },
		{ DRM_FORMAT_RGB888, 24 }, { DRM_FORMAT_RGB565, 16 },
	};
	uint32_t fourcc = 0; uint8_t bpp = 0;
	for (uint32_t i = 0; i < ARRAY_SIZE(prefs) && !fourcc; i++)
		for (uint32_t j = 0; j < (nfmts ? nfmts : ARRAY_SIZE(prefs)); j++) {
			if (nfmts && fmts[j] != prefs[i].fourcc)
				continue;
			fourcc = prefs[i].fourcc; bpp = prefs[i].bpp;
			break;
		}
	if (!fourcc) {
		printf("no usable writeback format\n");
		return 3;
	}
	printf("capturing %ux%u as %s (%u bpp)\n", mode.hdisplay, mode.vdisplay,
	       fourcc_str(fourcc), bpp);

	struct drm_mode_create_dumb create = { 0 };
	create.width = mode.hdisplay;
	create.height = mode.vdisplay;
	create.bpp = bpp;
	xioctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &create, "CREATE_DUMB");
	struct drm_mode_fb_cmd2 fb = { 0 };
	fb.width = create.width; fb.height = create.height;
	fb.pixel_format = fourcc;
	fb.handles[0] = create.handle;
	fb.pitches[0] = create.pitch;
	xioctl(fd, DRM_IOCTL_MODE_ADDFB2, &fb, "ADDFB2");
	struct drm_mode_map_dumb mapq = { .handle = create.handle };
	xioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &mapq, "MAP_DUMB");
	uint8_t *map = mmap(NULL, create.size, PROT_READ, MAP_SHARED, fd, mapq.offset);
	if (map == MAP_FAILED)
		die("mmap dumb");
	printf("wb fb %u: %ux%u pitch=%u size=%llu\n", fb.fb_id, fb.width, fb.height,
	       fb.pitches[0], (unsigned long long)create.size);

	int frames = fbdev ? 2 : 1;
	for (int f = 0; f < frames; f++) {
		if (f == 1) {
			paint_fb0_pattern(fbdev);
			usleep(100000); /* a few vblanks so the scanout shows it */
		}
		int32_t fence_fd = -1;
		struct drm_mode_atomic atomic = { 0 };
		uint32_t objs[1] = { wb_conn };
		uint32_t counts[1];
		uint32_t props[3];
		uint64_t values[3];
		uint32_t nprops = 0;
		props[nprops] = p_crtc; values[nprops++] = src_crtc;
		props[nprops] = p_fb; values[nprops++] = fb.fb_id;
		if (p_fence) {
			props[nprops] = p_fence;
			values[nprops++] = (uint64_t)(uintptr_t)&fence_fd;
		}
		counts[0] = nprops;
		atomic.flags = DRM_MODE_ATOMIC_ALLOW_MODESET;
		atomic.count_objs = 1;
		atomic.objs_ptr = (uintptr_t)objs;
		atomic.count_props_ptr = (uintptr_t)counts;
		atomic.props_ptr = (uintptr_t)props;
		atomic.prop_values_ptr = (uintptr_t)values;
		if (ioctl(fd, DRM_IOCTL_MODE_ATOMIC, &atomic) < 0) {
			printf("frame %d: ATOMIC commit failed: %s\n", f, strerror(errno));
			continue;
		}
		if (fence_fd >= 0) {
			struct pollfd pfd = { .fd = fence_fd, .events = POLLIN };
			int pr = poll(&pfd, 1, 2000);
			printf("frame %d: out-fence poll=%d (%s)\n", f, pr,
			       pr > 0 ? "signalled" : pr == 0 ? "timeout" : strerror(errno));
			close(fence_fd);
		} else {
			usleep(200000);
		}
		usleep(50000); /* settle past the writeback vblank in any case */
		char path[256];
		snprintf(path, sizeof(path), "%s-%d-%s.raw", prefix, f,
			 f == 0 ? "before" : "pattern");
		int out = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
		if (out < 0) {
			printf("frame %d: open %s failed: %s\n", f, path, strerror(errno));
			continue;
		}
		uint32_t row_bytes = fb.width * (bpp / 8);
		uint64_t nonblack = 0;
		for (uint32_t y = 0; y < fb.height; y++) {
			const uint8_t *row = map + (size_t)y * fb.pitches[0];
			if (write(out, row, row_bytes) != (ssize_t)row_bytes) {
				printf("frame %d: short write: %s\n", f, strerror(errno));
				break;
			}
			for (uint32_t x = 0; x < row_bytes; x++)
				if (row[x])
					nonblack++;
		}
		close(out);
		printf("frame %d: wrote %s (%ux%u %s, nonblack-bytes=%llu)\n",
		       f, path, fb.width, fb.height, fourcc_str(fourcc),
		       (unsigned long long)nonblack);
	}

	/* Leave the source pipeline as found: only detach the writeback tap. */
	struct drm_mode_atomic atomic = { 0 };
	uint32_t objs[1] = { wb_conn };
	uint32_t counts[1];
	uint32_t props[2];
	uint64_t values[2];
	props[0] = p_crtc; values[0] = 0;
	props[1] = p_fb; values[1] = 0;
	counts[0] = 2;
	atomic.flags = DRM_MODE_ATOMIC_ALLOW_MODESET;
	atomic.count_objs = 1;
	atomic.objs_ptr = (uintptr_t)objs;
	atomic.count_props_ptr = (uintptr_t)counts;
	atomic.props_ptr = (uintptr_t)props;
	atomic.prop_values_ptr = (uintptr_t)values;
	if (ioctl(fd, DRM_IOCTL_MODE_ATOMIC, &atomic) < 0)
		printf("writeback detach failed (harmless at session end): %s\n",
		       strerror(errno));

	munmap(map, create.size);
	uint32_t rmfb = fb.fb_id;
	ioctl(fd, DRM_IOCTL_MODE_RMFB, &rmfb);
	struct drm_mode_destroy_dumb destroy = { .handle = create.handle };
	ioctl(fd, DRM_IOCTL_MODE_DESTROY_DUMB, &destroy);
	close(fd);
	printf("done\n");
	return 0;
}
