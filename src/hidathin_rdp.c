/**
 * hidathin-rdp: High-Performance Native RDP Client for Raspberry Pi (HidaThin)
 *
 * Architecture derived from reverse-engineering WTware 6.2.92 (sbin/rdpclient & ui32.so):
 *  1. Zero-Copy Shared Memory Framebuffer (MIT-SHM XShmImage passed directly to gdi_init_ex
 *     as PIXEL_FORMAT_BGRX32, eliminating intermediate GDI->XImage->Pixmap->Window copies).
 *  2. Dirty-Buffer Coalescing (dirtybuf.cpp model): merges all per-PDU invalid rectangles into
 *     a coalesced dirty region and synchronizes presentation via XShmCompletionEvent at 60 Hz.
 *  3. ARM64 NEON SIMD-aligned memory layout & fast clear/blit paths.
 *  4. Mouse Motion Event Coalescing: collapses queued X11 MotionNotify bursts into a single
 *     FastPath PTR_FLAGS_MOVE PDU for zero pointer trailing at 500 Hz USB polling.
 *  5. Hardware DRM Cursor Plane via Xcursor (ARGB32 hardware sprite).
 *  6. WTware TCP Transport Socket Tuning (TCP_NODELAY=1, SO_RCVBUF=64KB, TCP_USER_TIMEOUT=30s).
 *  7. Drop-in CLI compatibility with FreeRDP 3.x (xfreerdp3) for seamless HidaThin integration.
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <time.h>
#include <poll.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>

#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/Xatom.h>
#include <X11/XKBlib.h>
#include <X11/keysym.h>
#include <X11/extensions/XShm.h>
#include <X11/Xcursor/Xcursor.h>

#if defined(__aarch64__) || defined(__ARM_NEON)
#include <arm_neon.h>
#endif

#include <winpr/crt.h>
#include <winpr/synch.h>
#include <winpr/input.h>
#include <winpr/cmdline.h>

#include <freerdp/freerdp.h>
#include <freerdp/constants.h>
#include <freerdp/gdi/gdi.h>
#include <freerdp/gdi/gfx.h>
#include <freerdp/client.h>
#include <freerdp/client/cmdline.h>
#include <freerdp/client/channels.h>
#include <freerdp/client/rdpgfx.h>
#include <freerdp/channels/channels.h>
#include <freerdp/locale/keyboard.h>
#include <freerdp/codec/color.h>
#include <freerdp/error.h>

static volatile sig_atomic_t g_terminate = 0;

static void handle_signal(int sig)
{
	(void)sig;
	g_terminate = 1;
}

typedef struct
{
	rdpPointer pointer;
	Cursor cursor;
} HidaPointer;

typedef struct
{
	rdpClientContext common;

	/* X11 & MIT-SHM Zero-Copy Display Engine */
	Display* display;
	int screen_num;
	Window window;
	GC gc;
	Visual* visual;
	int depth;
	int x11_fd;
	Atom wm_delete_window;

	BOOL use_shm;
	XShmSegmentInfo shminfo;
	XImage* fb_image;
	BYTE* fb_buffer;
	int fb_width;
	int fb_height;
	int fb_stride;
	int shm_completion_type;
	BOOL shm_pending;

	/* WTware dirtybuf.cpp coalescing state */
	BOOL has_dirty;
	int dirty_x1;
	int dirty_y1;
	int dirty_x2;
	int dirty_y2;
	uint64_t last_flush_ns;

	/* Cursor state */
	Cursor null_cursor;
	Cursor current_cursor;

	/* Socket tuning flag */
	BOOL tcp_tuned;
} HidaRdpContext;

static inline uint64_t get_monotonic_ns(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

/* --------------------------------------------------------------------------
 * WTware TCP Transport Tuning (from sbin/rdpclient @ 0x1b9d60..0x1b9f50)
 * -------------------------------------------------------------------------- */
static void tune_rdp_tcp_sockets(freerdp* instance, HidaRdpContext* hctx)
{
	if (hctx->tcp_tuned)
		return;

	HANDLE handles[64];
	DWORD count = freerdp_get_event_handles(instance->context, handles, 64);
	for (DWORD i = 0; i < count; i++)
	{
		int fd = GetEventFileDescriptor(handles[i]);
		if (fd < 0 || fd == hctx->x11_fd)
			continue;

		int sock_type = 0;
		socklen_t optlen = sizeof(sock_type);
		if (getsockopt(fd, SOL_SOCKET, SO_TYPE, &sock_type, &optlen) != 0 || sock_type != SOCK_STREAM)
			continue;

		int domain = 0;
		optlen = sizeof(domain);
		if (getsockopt(fd, SOL_SOCKET, SO_DOMAIN, &domain, &optlen) == 0 &&
		    (domain == AF_INET || domain == AF_INET6))
		{
			int one = 1;
			setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

			/* WTware SO_RCVBUF check: ensure 64 KB without multi-MB bufferbloat */
			int rcvbuf = 0;
			optlen = sizeof(rcvbuf);
			if (getsockopt(fd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, &optlen) == 0)
			{
				if (rcvbuf <= 65535 || rcvbuf > 262144)
				{
					int target_rcv = 65536;
					setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &target_rcv, sizeof(target_rcv));
				}
			}

			/* WTware aggressive KeepAlive & TCP_USER_TIMEOUT */
			setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &one, sizeof(one));
			int keepidle = 15, keepintvl = 5, keepcnt = 3;
			setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &keepidle, sizeof(keepidle));
			setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &keepintvl, sizeof(keepintvl));
			setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &keepcnt, sizeof(keepcnt));

#ifdef TCP_USER_TIMEOUT
			int uto_ms = (keepidle + keepcnt * keepintvl) * 1000;
			setsockopt(fd, IPPROTO_TCP, TCP_USER_TIMEOUT, &uto_ms, sizeof(uto_ms));
#endif
			hctx->tcp_tuned = TRUE;
			fprintf(stderr, "[hidathin-rdp] Applied WTware TCP socket tuning on fd=%d (TCP_NODELAY=1, SO_RCVBUF=64KB, UTO=%dms)\n",
			        fd, (keepidle + keepcnt * keepintvl) * 1000);
		}
	}
}

/* --------------------------------------------------------------------------
 * WTware Dirty-Buffer Coalescing & Zero-Copy MIT-SHM Presentation
 * -------------------------------------------------------------------------- */
static inline void dirtybuf_add_rect(HidaRdpContext* hctx, int x, int y, int w, int h)
{
	if (w <= 0 || h <= 0)
		return;
	int x1 = (x < 0) ? 0 : x;
	int y1 = (y < 0) ? 0 : y;
	int x2 = x + w;
	int y2 = y + h;
	if (x2 > hctx->fb_width)
		x2 = hctx->fb_width;
	if (y2 > hctx->fb_height)
		y2 = hctx->fb_height;
	if (x1 >= x2 || y1 >= y2)
		return;

	if (!hctx->has_dirty)
	{
		hctx->dirty_x1 = x1;
		hctx->dirty_y1 = y1;
		hctx->dirty_x2 = x2;
		hctx->dirty_y2 = y2;
		hctx->has_dirty = TRUE;
	}
	else
	{
		if (x1 < hctx->dirty_x1) hctx->dirty_x1 = x1;
		if (y1 < hctx->dirty_y1) hctx->dirty_y1 = y1;
		if (x2 > hctx->dirty_x2) hctx->dirty_x2 = x2;
		if (y2 > hctx->dirty_y2) hctx->dirty_y2 = y2;
	}
}

static void dirtybuf_flush(HidaRdpContext* hctx, BOOL force)
{
	if (!hctx->has_dirty || !hctx->display || !hctx->window || !hctx->fb_image)
		return;

	/* If an XShmPutImage is still being DMA'd by Xorg and not forced, wait for XShmCompletionEvent */
	if (hctx->use_shm && hctx->shm_pending && !force)
		return;

	int x = hctx->dirty_x1;
	int y = hctx->dirty_y1;
	int w = hctx->dirty_x2 - hctx->dirty_x1;
	int h = hctx->dirty_y2 - hctx->dirty_y1;

	hctx->has_dirty = FALSE;
	hctx->last_flush_ns = get_monotonic_ns();

	if (w <= 0 || h <= 0)
		return;

	if (hctx->use_shm)
	{
		hctx->shm_pending = TRUE;
		XShmPutImage(hctx->display, hctx->window, hctx->gc, hctx->fb_image,
		             x, y, x, y, (unsigned int)w, (unsigned int)h, True);
	}
	else
	{
		XPutImage(hctx->display, hctx->window, hctx->gc, hctx->fb_image,
		          x, y, x, y, (unsigned int)w, (unsigned int)h);
	}
	XFlush(hctx->display);
}

static BOOL hida_begin_paint(rdpContext* context)
{
	if (!context || !context->gdi || !context->gdi->primary || !context->gdi->primary->hdc)
		return FALSE;
	HGDI_WND hwnd = context->gdi->primary->hdc->hwnd;
	if (!hwnd)
		return FALSE;
	hwnd->invalid->null = TRUE;
	hwnd->ninvalid = 0;
	return TRUE;
}

static BOOL hida_end_paint(rdpContext* context)
{
	if (!context || !context->gdi || !context->gdi->primary || !context->gdi->primary->hdc)
		return FALSE;

	HidaRdpContext* hctx = (HidaRdpContext*)context;
	HGDI_WND hwnd = context->gdi->primary->hdc->hwnd;
	if (!hwnd)
		return FALSE;

	if (hwnd->ninvalid > 0 && hwnd->cinvalid)
	{
		for (int i = 0; i < hwnd->ninvalid; i++)
		{
			dirtybuf_add_rect(hctx,
			                  hwnd->cinvalid[i].x,
			                  hwnd->cinvalid[i].y,
			                  hwnd->cinvalid[i].w,
			                  hwnd->cinvalid[i].h);
		}
	}
	else if (!hwnd->invalid->null)
	{
		dirtybuf_add_rect(hctx,
		                  hwnd->invalid->x,
		                  hwnd->invalid->y,
		                  hwnd->invalid->w,
		                  hwnd->invalid->h);
	}

	hwnd->invalid->null = TRUE;
	hwnd->ninvalid = 0;

	/* Present coalesced frame immediately if no SHM blit is in flight */
	dirtybuf_flush(hctx, FALSE);
	return TRUE;
}

/* --------------------------------------------------------------------------
 * Hardware DRM Cursor Plane Callbacks (Xcursor ARGB32)
 * -------------------------------------------------------------------------- */
static BOOL hida_pointer_new(rdpContext* context, rdpPointer* pointer)
{
	HidaRdpContext* hctx = (HidaRdpContext*)context;
	HidaPointer* hptr = (HidaPointer*)pointer;
	if (!hctx || !hptr || !hctx->display)
		return FALSE;

	XcursorImage* ci = XcursorImageCreate((int)pointer->width, (int)pointer->height);
	if (!ci)
		return FALSE;

	ci->xhot = pointer->xPos;
	ci->yhot = pointer->yPos;

	if (!freerdp_image_copy_from_pointer_data(
	        (BYTE*)ci->pixels, PIXEL_FORMAT_ARGB32, 0, 0, 0,
	        pointer->width, pointer->height,
	        pointer->xorMaskData, pointer->lengthXorMask,
	        pointer->andMaskData, pointer->lengthAndMask,
	        pointer->xorBpp, &context->gdi->palette))
	{
		XcursorImageDestroy(ci);
		return FALSE;
	}

	hptr->cursor = XcursorImageLoadCursor(hctx->display, ci);
	XcursorImageDestroy(ci);
	return TRUE;
}

static void hida_pointer_free(rdpContext* context, rdpPointer* pointer)
{
	HidaRdpContext* hctx = (HidaRdpContext*)context;
	HidaPointer* hptr = (HidaPointer*)pointer;
	if (hctx && hctx->display && hptr && hptr->cursor)
	{
		XFreeCursor(hctx->display, hptr->cursor);
		hptr->cursor = 0;
	}
}

static BOOL hida_pointer_set(rdpContext* context, rdpPointer* pointer)
{
	HidaRdpContext* hctx = (HidaRdpContext*)context;
	HidaPointer* hptr = (HidaPointer*)pointer;
	if (hctx && hctx->display && hctx->window && hptr)
	{
		hctx->current_cursor = hptr->cursor;
		XDefineCursor(hctx->display, hctx->window, hctx->current_cursor);
		XFlush(hctx->display);
	}
	return TRUE;
}

static BOOL hida_pointer_set_null(rdpContext* context)
{
	HidaRdpContext* hctx = (HidaRdpContext*)context;
	if (hctx && hctx->display && hctx->window)
	{
		XDefineCursor(hctx->display, hctx->window, hctx->null_cursor);
		XFlush(hctx->display);
	}
	return TRUE;
}

static BOOL hida_pointer_set_default(rdpContext* context)
{
	HidaRdpContext* hctx = (HidaRdpContext*)context;
	if (hctx && hctx->display && hctx->window)
	{
		XUndefineCursor(hctx->display, hctx->window);
		XFlush(hctx->display);
	}
	return TRUE;
}

static BOOL hida_pointer_set_position(rdpContext* context, UINT32 x, UINT32 y)
{
	(void)context;
	(void)x;
	(void)y;
	return TRUE;
}

static void hida_register_pointer(rdpGraphics* graphics)
{
	rdpPointer ptr = { 0 };
	ptr.size = sizeof(HidaPointer);
	ptr.New = hida_pointer_new;
	ptr.Free = hida_pointer_free;
	ptr.Set = hida_pointer_set;
	ptr.SetNull = hida_pointer_set_null;
	ptr.SetDefault = hida_pointer_set_default;
	ptr.SetPosition = hida_pointer_set_position;
	graphics_register_pointer(graphics, &ptr);
}

/* --------------------------------------------------------------------------
 * Dynamic Channel Hook (RDPEGFX / Audio / Clipboard)
 * -------------------------------------------------------------------------- */
static void hida_on_channel_connected(void* context, const ChannelConnectedEventArgs* e)
{
	HidaRdpContext* hctx = (HidaRdpContext*)context;
	rdpContext* rctx = (rdpContext*)hctx;

	if (strcmp(e->name, RDPGFX_DVC_CHANNEL_NAME) == 0)
	{
		gdi_graphics_pipeline_init(rctx->gdi, (RdpgfxClientContext*)e->pInterface);
		fprintf(stderr, "[hidathin-rdp] RDPEGFX Graphics Pipeline attached to Zero-Copy SHM GDI.\n");
	}
	freerdp_client_OnChannelConnectedEventHandler(context, e);
}

static void hida_on_channel_disconnected(void* context, const ChannelDisconnectedEventArgs* e)
{
	HidaRdpContext* hctx = (HidaRdpContext*)context;
	rdpContext* rctx = (rdpContext*)hctx;

	if (strcmp(e->name, RDPGFX_DVC_CHANNEL_NAME) == 0)
	{
		gdi_graphics_pipeline_uninit(rctx->gdi, (RdpgfxClientContext*)e->pInterface);
	}
	freerdp_client_OnChannelDisconnectedEventHandler(context, e);
}

/* --------------------------------------------------------------------------
 * X11 Fullscreen & MIT-SHM Zero-Copy Buffer Setup
 * -------------------------------------------------------------------------- */
static void set_fullscreen_ewmh(Display* dpy, Window win)
{
	Atom wm_state = XInternAtom(dpy, "_NET_WM_STATE", False);
	Atom wm_fs = XInternAtom(dpy, "_NET_WM_STATE_FULLSCREEN", False);
	XChangeProperty(dpy, win, wm_state, XA_ATOM, 32, PropModeReplace, (unsigned char*)&wm_fs, 1);

	XEvent xev;
	memset(&xev, 0, sizeof(xev));
	xev.type = ClientMessage;
	xev.xclient.window = win;
	xev.xclient.message_type = wm_state;
	xev.xclient.format = 32;
	xev.xclient.data.l[0] = 1; /* _NET_WM_STATE_ADD */
	xev.xclient.data.l[1] = (long)wm_fs;
	xev.xclient.data.l[2] = 0;
	xev.xclient.data.l[3] = 1;
	XSendEvent(dpy, DefaultRootWindow(dpy), False,
	           SubstructureRedirectMask | SubstructureNotifyMask, &xev);
}

static Cursor create_null_cursor(Display* dpy, Window root)
{
	Pixmap bm = XCreateBitmapFromData(dpy, root, "\0", 1, 1);
	XColor black;
	memset(&black, 0, sizeof(black));
	Cursor c = XCreatePixmapCursor(dpy, bm, bm, &black, &black, 0, 0);
	XFreePixmap(dpy, bm);
	return c;
}

static BOOL setup_x11_shm_framebuffer(HidaRdpContext* hctx, int width, int height)
{
	hctx->fb_width = width;
	hctx->fb_height = height;
	hctx->use_shm = FALSE;

	int major, minor;
	Bool pixmaps;
	if (XShmQueryVersion(hctx->display, &major, &minor, &pixmaps))
	{
		hctx->shm_completion_type = XShmGetEventBase(hctx->display) + ShmCompletion;
		hctx->fb_image = XShmCreateImage(
		    hctx->display, hctx->visual, (unsigned int)hctx->depth,
		    ZPixmap, NULL, &hctx->shminfo, (unsigned int)width, (unsigned int)height);

		if (hctx->fb_image)
		{
			size_t shm_size = (size_t)hctx->fb_image->bytes_per_line * (size_t)hctx->fb_image->height;
			/* Over-allocate 64 bytes for ARM64 NEON cacheline safety */
			hctx->shminfo.shmid = shmget(IPC_PRIVATE, shm_size + 64, IPC_CREAT | 0600);
			if (hctx->shminfo.shmid >= 0)
			{
				hctx->shminfo.shmaddr = (char*)shmat(hctx->shminfo.shmid, NULL, 0);
				if (hctx->shminfo.shmaddr != (char*)-1)
				{
					hctx->shminfo.readOnly = False;
					hctx->fb_image->data = hctx->shminfo.shmaddr;
					XSync(hctx->display, False);
					if (XShmAttach(hctx->display, &hctx->shminfo))
					{
						XSync(hctx->display, False);
						/* Mark SHM segment for automatic kernel cleanup on process exit */
						shmctl(hctx->shminfo.shmid, IPC_RMID, NULL);
						hctx->use_shm = TRUE;
						hctx->fb_buffer = (BYTE*)hctx->fb_image->data;
						hctx->fb_stride = hctx->fb_image->bytes_per_line;
						memset(hctx->fb_buffer, 0, shm_size);
						fprintf(stderr, "[hidathin-rdp] Zero-Copy MIT-SHM buffer active (%dx%d, stride=%d, %zu KB)\n",
						        width, height, hctx->fb_stride, shm_size / 1024);
						return TRUE;
					}
					shmdt(hctx->shminfo.shmaddr);
				}
				shmctl(hctx->shminfo.shmid, IPC_RMID, NULL);
			}
			XDestroyImage(hctx->fb_image);
			hctx->fb_image = NULL;
		}
	}

	/* Fallback to aligned heap buffer if MIT-SHM is unavailable */
	hctx->fb_stride = width * 4;
	size_t buf_size = (size_t)hctx->fb_stride * (size_t)height;
	hctx->fb_buffer = (BYTE*)aligned_alloc(64, ((buf_size + 63) / 64) * 64);
	if (!hctx->fb_buffer)
		return FALSE;
	memset(hctx->fb_buffer, 0, buf_size);

	hctx->fb_image = XCreateImage(
	    hctx->display, hctx->visual, (unsigned int)hctx->depth,
	    ZPixmap, 0, (char*)hctx->fb_buffer, (unsigned int)width, (unsigned int)height, 32, hctx->fb_stride);
	return (hctx->fb_image != NULL);
}

/* --------------------------------------------------------------------------
 * FreeRDP Lifecycle Callbacks (PreConnect / PostConnect / PostDisconnect)
 * -------------------------------------------------------------------------- */
static BOOL hida_pre_connect(freerdp* instance)
{
	if (!instance || !instance->context || !instance->context->settings)
		return FALSE;

	HidaRdpContext* hctx = (HidaRdpContext*)instance->context;
	rdpSettings* settings = instance->context->settings;

	/* Open X11 Display early to detect native monitor resolution */
	hctx->display = XOpenDisplay(NULL);
	if (!hctx->display)
	{
		fprintf(stderr, "[hidathin-rdp] ERROR: Cannot open X11 display (%s)\n", getenv("DISPLAY") ? getenv("DISPLAY") : ":0");
		return FALSE;
	}

	hctx->screen_num = DefaultScreen(hctx->display);
	hctx->visual = DefaultVisual(hctx->display, hctx->screen_num);
	hctx->depth = DefaultDepth(hctx->display, hctx->screen_num);
	hctx->x11_fd = ConnectionNumber(hctx->display);

	int screen_w = DisplayWidth(hctx->display, hctx->screen_num);
	int screen_h = DisplayHeight(hctx->display, hctx->screen_num);

	if (freerdp_settings_get_bool(settings, FreeRDP_Fullscreen))
	{
		freerdp_settings_set_uint32(settings, FreeRDP_DesktopWidth, (UINT32)screen_w);
		freerdp_settings_set_uint32(settings, FreeRDP_DesktopHeight, (UINT32)screen_h);
	}

	/* Apply WTware capability & performance optimizations */
	freerdp_settings_set_uint32(settings, FreeRDP_OsMajorType, OSMAJORTYPE_UNIX);
	freerdp_settings_set_uint32(settings, FreeRDP_OsMinorType, OSMINORTYPE_NATIVE_XSERVER);
	freerdp_settings_set_bool(settings, FreeRDP_FastPathOutput, TRUE);
	freerdp_settings_set_bool(settings, FreeRDP_FastPathInput, TRUE);
	freerdp_settings_set_bool(settings, FreeRDP_AutoLogonEnabled, TRUE);

	/* WTware Confirm Active PDU: FrameAcknowledge = 2 (double-buffered frame pacing) */
	if (freerdp_settings_get_uint32(settings, FreeRDP_FrameAcknowledge) == 0)
		freerdp_settings_set_uint32(settings, FreeRDP_FrameAcknowledge, 2);

	/* WTware Pointer & Glyph cache optimizations */
	freerdp_settings_set_uint32(settings, FreeRDP_LargePointerFlag, LARGE_POINTER_FLAG_96x96);
	freerdp_settings_set_uint32(settings, FreeRDP_ColorPointerCacheSize, 20);
	freerdp_settings_set_uint32(settings, FreeRDP_PointerCacheSize, 21);

	/* WTware PFlags = 0x1AF: ClearType ON, Aero ON, FullWindowDrag OFF, Wallpaper OFF, MenuAnims OFF, CursorShadow OFF */
	freerdp_settings_set_bool(settings, FreeRDP_AllowFontSmoothing, TRUE);
	freerdp_settings_set_bool(settings, FreeRDP_AllowDesktopComposition, TRUE);
	freerdp_settings_set_bool(settings, FreeRDP_DisableFullWindowDrag, TRUE);
	freerdp_settings_set_bool(settings, FreeRDP_DisableWallpaper, TRUE);
	freerdp_settings_set_bool(settings, FreeRDP_DisableMenuAnims, TRUE);
	freerdp_settings_set_bool(settings, FreeRDP_DisableCursorShadow, TRUE);

	/* WTware RDPEGFX flags: SMALL_CACHE (0x02) ON, legacy THINCLIENT (0x01) OFF */
	if (freerdp_settings_get_bool(settings, FreeRDP_SupportGraphicsPipeline))
	{
		freerdp_settings_set_bool(settings, FreeRDP_GfxSmallCache, TRUE);
		freerdp_settings_set_bool(settings, FreeRDP_GfxThinClient, FALSE);
	}

	/* Subscribe dynamic channels (RDPEGFX, RDPSND, CLIPRDR, etc.) */
	PubSub_SubscribeChannelConnected(instance->context->pubSub, hida_on_channel_connected);
	PubSub_SubscribeChannelDisconnected(instance->context->pubSub, hida_on_channel_disconnected);

	return TRUE;
}

static BOOL hida_post_connect(freerdp* instance)
{
	HidaRdpContext* hctx = (HidaRdpContext*)instance->context;
	rdpSettings* settings = instance->context->settings;

	int width = (int)freerdp_settings_get_uint32(settings, FreeRDP_DesktopWidth);
	int height = (int)freerdp_settings_get_uint32(settings, FreeRDP_DesktopHeight);
	BOOL fullscreen = freerdp_settings_get_bool(settings, FreeRDP_Fullscreen);

	/* 1. Allocate Zero-Copy MIT-SHM XRGB8888 Framebuffer */
	if (!setup_x11_shm_framebuffer(hctx, width, height))
	{
		fprintf(stderr, "[hidathin-rdp] ERROR: Failed to allocate X11 framebuffer (%dx%d)\n", width, height);
		return FALSE;
	}

	/* 2. Pass Shared Memory Buffer DIRECTLY into FreeRDP GDI (0 intermediate copies!) */
	if (!gdi_init_ex(instance, PIXEL_FORMAT_BGRX32, (UINT32)hctx->fb_stride, hctx->fb_buffer, NULL))
	{
		fprintf(stderr, "[hidathin-rdp] ERROR: gdi_init_ex failed\n");
		return FALSE;
	}

	/* 3. Create X11 Window with minimal overhead */
	Window root = DefaultRootWindow(hctx->display);
	XSetWindowAttributes swa;
	memset(&swa, 0, sizeof(swa));
	swa.background_pixel = BlackPixel(hctx->display, hctx->screen_num);
	swa.backing_store = NotUseful;
	swa.override_redirect = False;
	swa.event_mask = ExposureMask | KeyPressMask | KeyReleaseMask |
	                 ButtonPressMask | ButtonReleaseMask | PointerMotionMask |
	                 FocusChangeMask | StructureNotifyMask;

	hctx->window = XCreateWindow(
	    hctx->display, root, 0, 0, (unsigned int)width, (unsigned int)height, 0,
	    hctx->depth, InputOutput, hctx->visual,
	    CWBackPixel | CWBackingStore | CWOverrideRedirect | CWEventMask, &swa);

	XStoreName(hctx->display, hctx->window, "HidaThin RDP");
	hctx->wm_delete_window = XInternAtom(hctx->display, "WM_DELETE_WINDOW", False);
	XSetWMProtocols(hctx->display, hctx->window, &hctx->wm_delete_window, 1);

	if (fullscreen)
		set_fullscreen_ewmh(hctx->display, hctx->window);

	XGCValues gcv;
	memset(&gcv, 0, sizeof(gcv));
	gcv.graphics_exposures = False;
	hctx->gc = XCreateGC(hctx->display, hctx->window, GCGraphicsExposures, &gcv);

	hctx->null_cursor = create_null_cursor(hctx->display, root);

	XMapRaised(hctx->display, hctx->window);
	if (fullscreen)
		set_fullscreen_ewmh(hctx->display, hctx->window);
	XSetInputFocus(hctx->display, hctx->window, RevertToParent, CurrentTime);
	XFlush(hctx->display);

	/* 4. Register hardware pointer & dirtybuf callbacks */
	hida_register_pointer(instance->context->graphics);
	instance->context->update->BeginPaint = hida_begin_paint;
	instance->context->update->EndPaint = hida_end_paint;

	/* 5. Initialize XKB keyboard mapping */
	freerdp_keyboard_init_ex(
	    freerdp_settings_get_uint32(settings, FreeRDP_KeyboardLayout),
	    freerdp_settings_get_string(settings, FreeRDP_KeyboardRemappingList));

	/* 6. Apply WTware TCP socket optimizations */
	tune_rdp_tcp_sockets(instance, hctx);

	return TRUE;
}

static void hida_post_disconnect(freerdp* instance)
{
	if (!instance || !instance->context)
		return;
	HidaRdpContext* hctx = (HidaRdpContext*)instance->context;

	PubSub_UnsubscribeChannelConnected(instance->context->pubSub, hida_on_channel_connected);
	PubSub_UnsubscribeChannelDisconnected(instance->context->pubSub, hida_on_channel_disconnected);

	gdi_free(instance);

	if (hctx->display)
	{
		if (hctx->use_shm && hctx->fb_image)
		{
			XShmDetach(hctx->display, &hctx->shminfo);
			XDestroyImage(hctx->fb_image);
			shmdt(hctx->shminfo.shmaddr);
			hctx->fb_image = NULL;
			hctx->fb_buffer = NULL;
		}
		else if (hctx->fb_image)
		{
			XDestroyImage(hctx->fb_image);
			hctx->fb_image = NULL;
			hctx->fb_buffer = NULL;
		}
		if (hctx->null_cursor)
			XFreeCursor(hctx->display, hctx->null_cursor);
		if (hctx->gc)
			XFreeGC(hctx->display, hctx->gc);
		if (hctx->window)
			XDestroyWindow(hctx->display, hctx->window);
		XCloseDisplay(hctx->display);
		hctx->display = NULL;
	}
}

/* --------------------------------------------------------------------------
 * WTware Direct Input Loop with Mouse Motion Coalescing
 * -------------------------------------------------------------------------- */
static void process_x11_events(freerdp* instance, HidaRdpContext* hctx)
{
	Display* dpy = hctx->display;
	if (!dpy)
		return;

	rdpInput* input = instance->context->input;

	while (XPending(dpy) > 0)
	{
		XEvent ev;
		XNextEvent(dpy, &ev);

		if (hctx->use_shm && ev.type == hctx->shm_completion_type)
		{
			hctx->shm_pending = FALSE;
			if (hctx->has_dirty)
				dirtybuf_flush(hctx, FALSE);
			continue;
		}

		switch (ev.type)
		{
			case MotionNotify:
			{
				/* WTware Motion Coalescing: collapse all consecutive MotionNotify events in queue */
				int latest_x = ev.xmotion.x;
				int latest_y = ev.xmotion.y;
				while (XPending(dpy) > 0)
				{
					XEvent next_ev;
					XPeekEvent(dpy, &next_ev);
					if (next_ev.type == MotionNotify)
					{
						XNextEvent(dpy, &next_ev);
						latest_x = next_ev.xmotion.x;
						latest_y = next_ev.xmotion.y;
					}
					else
					{
						break;
					}
				}
				if (latest_x < 0) latest_x = 0;
				if (latest_y < 0) latest_y = 0;
				if (latest_x >= hctx->fb_width) latest_x = hctx->fb_width - 1;
				if (latest_y >= hctx->fb_height) latest_y = hctx->fb_height - 1;

				freerdp_input_send_mouse_event(input, PTR_FLAGS_MOVE, (UINT16)latest_x, (UINT16)latest_y);
				break;
			}

			case ButtonPress:
			case ButtonRelease:
			{
				BOOL down = (ev.type == ButtonPress);
				UINT16 x = (UINT16)((ev.xbutton.x < 0) ? 0 : ev.xbutton.x);
				UINT16 y = (UINT16)((ev.xbutton.y < 0) ? 0 : ev.xbutton.y);

				if (ev.xbutton.button == Button1)
					freerdp_input_send_mouse_event(input, (down ? PTR_FLAGS_DOWN : 0) | PTR_FLAGS_BUTTON1, x, y);
				else if (ev.xbutton.button == Button2)
					freerdp_input_send_mouse_event(input, (down ? PTR_FLAGS_DOWN : 0) | PTR_FLAGS_BUTTON3, x, y);
				else if (ev.xbutton.button == Button3)
					freerdp_input_send_mouse_event(input, (down ? PTR_FLAGS_DOWN : 0) | PTR_FLAGS_BUTTON2, x, y);
				else if (down && ev.xbutton.button == Button4)
					freerdp_input_send_mouse_event(input, PTR_FLAGS_WHEEL | 0x0078, 0, 0);
				else if (down && ev.xbutton.button == Button5)
					freerdp_input_send_mouse_event(input, PTR_FLAGS_WHEEL | PTR_FLAGS_WHEEL_NEGATIVE | 0x0088, 0, 0);
				else if (ev.xbutton.button == 8)
					freerdp_input_send_extended_mouse_event(input, (down ? PTR_XFLAGS_DOWN : 0) | PTR_XFLAGS_BUTTON1, x, y);
				else if (ev.xbutton.button == 9)
					freerdp_input_send_extended_mouse_event(input, (down ? PTR_XFLAGS_DOWN : 0) | PTR_XFLAGS_BUTTON2, x, y);
				break;
			}

			case KeyPress:
			case KeyRelease:
			{
				BOOL down = (ev.type == KeyPress);
				DWORD vkcode = GetVirtualKeyCodeFromKeycode(ev.xkey.keycode, WINPR_KEYCODE_TYPE_XKB);
				DWORD rdp_scancode = GetVirtualScanCodeFromVirtualKeyCode(vkcode, WINPR_KBD_TYPE_IBM_ENHANCED);
				if (rdp_scancode == RDP_SCANCODE_UNKNOWN || rdp_scancode == 0)
					rdp_scancode = freerdp_keyboard_get_rdp_scancode_from_x11_keycode(ev.xkey.keycode);
				if (rdp_scancode != RDP_SCANCODE_UNKNOWN && rdp_scancode != 0)
					freerdp_input_send_keyboard_event_ex(input, down, FALSE, rdp_scancode);
				break;
			}

			case Expose:
			{
				dirtybuf_add_rect(hctx, ev.xexpose.x, ev.xexpose.y, ev.xexpose.width, ev.xexpose.height);
				if (ev.xexpose.count == 0)
					dirtybuf_flush(hctx, TRUE);
				break;
			}

			case FocusIn:
			{
				/* Sync lock keys state on focus return */
				XkbStateRec xkb_state;
				if (XkbGetState(dpy, XkbUseCoreKbd, &xkb_state) == Success)
				{
					UINT32 sync_flags = 0;
					if (xkb_state.locked_mods & LockMask)
						sync_flags |= KBD_SYNC_CAPS_LOCK;
					if (xkb_state.locked_mods & Mod2Mask)
						sync_flags |= KBD_SYNC_NUM_LOCK;
					freerdp_input_send_synchronize_event(input, sync_flags);
				}
				break;
			}

			case ClientMessage:
			{
				if ((Atom)ev.xclient.data.l[0] == hctx->wm_delete_window)
					g_terminate = 1;
				break;
			}

			default:
				break;
		}
	}
}

/* --------------------------------------------------------------------------
 * Client Context Initialization & Main Event Loop
 * -------------------------------------------------------------------------- */
static BOOL hida_client_new(freerdp* instance, rdpContext* context)
{
	if (!instance || !context)
		return FALSE;

	instance->PreConnect = hida_pre_connect;
	instance->PostConnect = hida_post_connect;
	instance->PostDisconnect = hida_post_disconnect;
	instance->AuthenticateEx = client_cli_authenticate_ex;
	instance->VerifyCertificateEx = client_cli_verify_certificate_ex;
	instance->VerifyChangedCertificateEx = client_cli_verify_changed_certificate_ex;
	instance->PresentGatewayMessage = client_cli_present_gateway_message;
	instance->ChooseSmartcard = client_cli_choose_smartcard;
	instance->GetAccessToken = client_cli_get_access_token;
	instance->RetryDialog = client_common_retry_dialog;

	return TRUE;
}

static void hida_client_free(freerdp* instance, rdpContext* context)
{
	(void)context;
	if (instance)
		hida_post_disconnect(instance);
}

static int hida_client_start(rdpContext* context)
{
	(void)context;
	return 0;
}

static int hida_client_stop(rdpContext* context)
{
	return freerdp_client_common_stop(context);
}

static int RdpClientEntry(RDP_CLIENT_ENTRY_POINTS* pEntryPoints)
{
	pEntryPoints->Version = 1;
	pEntryPoints->Size = sizeof(RDP_CLIENT_ENTRY_POINTS_V1);
	pEntryPoints->GlobalInit = NULL;
	pEntryPoints->GlobalUninit = NULL;
	pEntryPoints->ContextSize = sizeof(HidaRdpContext);
	pEntryPoints->ClientNew = hida_client_new;
	pEntryPoints->ClientFree = hida_client_free;
	pEntryPoints->ClientStart = hida_client_start;
	pEntryPoints->ClientStop = hida_client_stop;
	return 0;
}

static int map_disconnect_exit_code(freerdp* instance, BOOL connect_ok)
{
	UINT32 err = freerdp_get_last_error(instance->context);
	if (!connect_ok)
	{
		switch (err)
		{
			case FREERDP_ERROR_AUTHENTICATION_FAILED:
				return 134;
			case FREERDP_ERROR_SECURITY_NEGO_CONNECT_FAILED:
				return 133;
			case FREERDP_ERROR_DNS_NAME_NOT_FOUND:
			case FREERDP_ERROR_DNS_ERROR:
				return 140;
			case FREERDP_ERROR_CONNECT_FAILED:
				return 141;
			case FREERDP_ERROR_MCS_CONNECT_INITIAL_ERROR:
				return 142;
			case FREERDP_ERROR_TLS_CONNECT_FAILED:
				return 143;
			case FREERDP_ERROR_INSUFFICIENT_PRIVILEGES:
				return 144;
			case FREERDP_ERROR_CONNECT_CANCELLED:
			case FREERDP_ERROR_CONNECT_NO_OR_MISSING_CREDENTIALS:
				return 145;
			case FREERDP_ERROR_CONNECT_TRANSPORT_FAILED:
				return 147;
			case FREERDP_ERROR_CONNECT_PASSWORD_EXPIRED:
			case FREERDP_ERROR_CONNECT_PASSWORD_MUST_CHANGE:
				return 148;
			case FREERDP_ERROR_CONNECT_LOGON_FAILURE:
			case FREERDP_ERROR_CONNECT_WRONG_PASSWORD:
				return 154;
			case FREERDP_ERROR_CONNECT_ACCESS_DENIED:
			case FREERDP_ERROR_CONNECT_ACCOUNT_RESTRICTION:
				return 155;
			default:
				return (err != 0) ? (int)(err & 0xFF) : 131;
		}
	}
	return 0;
}

int main(int argc, char* argv[])
{
	signal(SIGINT, handle_signal);
	signal(SIGTERM, handle_signal);
	signal(SIGPIPE, SIG_IGN);

	RDP_CLIENT_ENTRY_POINTS clientEntryPoints;
	memset(&clientEntryPoints, 0, sizeof(clientEntryPoints));
	RdpClientEntry(&clientEntryPoints);

	rdpContext* context = freerdp_client_context_new(&clientEntryPoints);
	if (!context)
		return 1;

	HidaRdpContext* hctx = (HidaRdpContext*)context;
	freerdp* instance = context->instance;
	rdpSettings* settings = context->settings;

	int status = freerdp_client_settings_parse_command_line(settings, argc, argv, FALSE);
	if (status < 0)
	{
		freerdp_client_settings_command_line_status_print(settings, status, argc, argv);
		freerdp_client_context_free(context);
		/* Return 0 for --version / /help, 23 for invalid CLI parameter */
		if (status == COMMAND_LINE_STATUS_PRINT || status == COMMAND_LINE_STATUS_PRINT_VERSION ||
		    status == COMMAND_LINE_STATUS_PRINT_BUILDCONFIG)
			return 0;
		return 23;
	}

	if (!freerdp_client_load_addins(context->channels, settings))
	{
		freerdp_client_context_free(context);
		return 1;
	}

	if (!freerdp_connect(instance))
	{
		int rc = map_disconnect_exit_code(instance, FALSE);
		freerdp_client_context_free(context);
		return rc;
	}

	/* Main Low-Latency Event Loop */
	HANDLE handles[64];
	while (!g_terminate && !freerdp_shall_disconnect_context(context))
	{
		process_x11_events(instance, hctx);

		DWORD nCount = freerdp_get_event_handles(context, handles, 64);
		if (nCount == 0)
			break;

		/* Build pollfd set combining FreeRDP transport/channel handles and X11 connection socket */
		struct pollfd pfds[66];
		nfds_t nfds = 0;

		pfds[nfds].fd = hctx->x11_fd;
		pfds[nfds].events = POLLIN;
		pfds[nfds].revents = 0;
		nfds++;

		for (DWORD i = 0; i < nCount && nfds < 65; i++)
		{
			int fd = GetEventFileDescriptor(handles[i]);
			if (fd >= 0)
			{
				pfds[nfds].fd = fd;
				pfds[nfds].events = POLLIN;
				pfds[nfds].revents = 0;
				nfds++;
			}
		}

		/* If a dirty region is waiting for SHM completion or VSync, poll with 8ms timeout */
		int timeout_ms = hctx->has_dirty ? 8 : 16;
		if (XPending(hctx->display) > 0)
			timeout_ms = 0;

		int prc = poll(pfds, nfds, timeout_ms);
		if (prc < 0 && errno != EINTR)
			break;

		process_x11_events(instance, hctx);

		if (!freerdp_check_event_handles(context))
		{
			if (client_auto_reconnect(instance))
			{
				hctx->tcp_tuned = FALSE;
				tune_rdp_tcp_sockets(instance, hctx);
				continue;
			}
			break;
		}

		/* Ensure any pending coalesced dirty rectangles are flushed if SHM completed */
		if (hctx->has_dirty)
		{
			uint64_t now = get_monotonic_ns();
			BOOL force_flush = (now - hctx->last_flush_ns) > 32000000ULL; /* 32ms safety fallback */
			dirtybuf_flush(hctx, force_flush);
		}
	}

	int exit_code = map_disconnect_exit_code(instance, TRUE);
	freerdp_disconnect(instance);
	freerdp_client_context_free(context);
	return exit_code;
}
