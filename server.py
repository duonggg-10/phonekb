#!/usr/bin/env python3
"""PhoneKB: điện thoại Android thành bàn phím + chuột rời qua WiFi. Server chạy trên Windows/Linux."""
import asyncio, base64, json, os, pathlib, secrets, shutil, socket, subprocess, sys
from aiohttp import web, WSMsgType

PORT = int(os.environ.get("PHONEKB_PORT", 3636))
HERE = pathlib.Path(__file__).resolve().parent
WIN = sys.platform == "win32"
log = print if sys.stdout else (lambda *a, **k: None)  # pythonw không có stdout

# ---- Bảng phím: KeyboardEvent.code -> (scancode hoặc VK, loại, mã evdev)
# ---- loại: 0 thường, 1 extended, 2 phím media (Windows dùng VK)
NAMES = ("Escape Digit1 Digit2 Digit3 Digit4 Digit5 Digit6 Digit7 Digit8 Digit9 Digit0 Minus Equal Backspace Tab "
         "KeyQ KeyW KeyE KeyR KeyT KeyY KeyU KeyI KeyO KeyP BracketLeft BracketRight Enter ControlLeft "
         "KeyA KeyS KeyD KeyF KeyG KeyH KeyJ KeyK KeyL Semicolon Quote Backquote ShiftLeft Backslash "
         "KeyZ KeyX KeyC KeyV KeyB KeyN KeyM Comma Period Slash ShiftRight - AltLeft Space CapsLock "
         "F1 F2 F3 F4 F5 F6 F7 F8 F9 F10").split()
KEYS = {n: (i + 1, 0, i + 1) for i, n in enumerate(NAMES) if n != "-"}
KEYS["F11"], KEYS["F12"] = (0x57, 0, 87), (0x58, 0, 88)
EXT = {"Home": (0x47, 102), "ArrowUp": (0x48, 103), "PageUp": (0x49, 104), "ArrowLeft": (0x4B, 105),
       "ArrowRight": (0x4D, 106), "End": (0x4F, 107), "ArrowDown": (0x50, 108), "PageDown": (0x51, 109),
       "Insert": (0x52, 110), "Delete": (0x53, 111), "MetaLeft": (0x5B, 125), "ControlRight": (0x1D, 97),
       "AltRight": (0x38, 100), "ContextMenu": (0x5D, 127), "PrintScreen": (0x37, 99)}
KEYS.update({k: (s, 1, c) for k, (s, c) in EXT.items()})
MEDIA = {"VolumeMute": (0xAD, 113), "VolumeDown": (0xAE, 114), "VolumeUp": (0xAF, 115), "MediaTrackNext": (0xB0, 163),
         "MediaTrackPrevious": (0xB1, 165), "MediaPlayPause": (0xB3, 164), "BrightnessDown": (0, 224), "BrightnessUp": (0, 225)}
KEYS.update({k: (v, 2, c) for k, (v, c) in MEDIA.items()})
NO_REPEAT = {"ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight", "AltLeft", "AltRight", "MetaLeft", "CapsLock",
             "PrintScreen", "BrightnessDown", "BrightnessUp", "MediaTrackNext", "MediaTrackPrevious", "MediaPlayPause", "VolumeMute"}

# ---- Gõ phím/chuột vào hệ điều hành. Phím luôn gửi dạng scancode vật lý (không gửi Unicode)
# ---- để Unikey/EVKey/iBus-Bamboo nhận như phím từ bàn phím thật.
inject = mouse = mbtn = wheel = None
if WIN:
    import ctypes
    from ctypes import wintypes as w

    class KI(ctypes.Structure):
        _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
    class MI(ctypes.Structure):
        _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
    class IU(ctypes.Union):
        _fields_ = [("ki", KI), ("mi", MI)]
    class INPUT(ctypes.Structure):
        _fields_ = [("type", w.DWORD), ("u", IU)]

    def _send(i):
        ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))

    def bright(d):  # độ sáng: chỉ màn hình tích hợp của laptop (WMI)
        ps = ("$m=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods;"
              "$b=(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness;"
              f"Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness=[Math]::Max(0,[Math]::Min(100,$b+({d})))}}")
        subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def inject(k, state):  # state: 1 nhấn, 0 nhả
        v, kind, _ = KEYS[k]
        if kind == 2 and v == 0:
            if state:
                bright(10 if k == "BrightnessUp" else -10)
            return
        up = 0 if state else 2
        ki = KI(v, 0, 1 | up, 0, 0) if kind == 2 else KI(0, v, 0x8 | kind | up, 0, 0)  # SCANCODE | EXTENDED | KEYUP
        _send(INPUT(1, IU(ki=ki)))

    def mouse(dx, dy): _send(INPUT(0, IU(mi=MI(dx, dy, 0, 0x1, 0, 0))))
    def mbtn(b, s): _send(INPUT(0, IU(mi=MI(0, 0, 0, (2 if s else 4) if b == "l" else (8 if s else 16), 0, 0))))
    def wheel(n, h): _send(INPUT(0, IU(mi=MI(0, 0, (n * 120) & 0xFFFFFFFF, 0x1000 if h else 0x800, 0, 0))))


def setup_injector():
    global inject, mouse, mbtn, wheel
    if WIN:
        return
    try:
        from evdev import UInput, ecodes as ec
        kb = UInput({ec.EV_KEY: sorted({v[2] for v in KEYS.values()})}, name="PhoneKB")
        ms = UInput({ec.EV_KEY: [ec.BTN_LEFT, ec.BTN_RIGHT],
                     ec.EV_REL: [ec.REL_X, ec.REL_Y, ec.REL_WHEEL, ec.REL_HWHEEL]}, name="PhoneKB Mouse")
    except Exception as ex:
        sys.exit(f"Không tạo được thiết bị ảo /dev/uinput ({ex}).\nXem mục Linux trong README.md")

    def inject(k, state): kb.write(ec.EV_KEY, KEYS[k][2], state); kb.syn()
    def mouse(dx, dy): ms.write(ec.EV_REL, ec.REL_X, dx); ms.write(ec.EV_REL, ec.REL_Y, dy); ms.syn()
    def mbtn(b, s): ms.write(ec.EV_KEY, ec.BTN_LEFT if b == "l" else ec.BTN_RIGHT, s); ms.syn()
    def wheel(n, h): ms.write(ec.EV_REL, ec.REL_HWHEEL if h else ec.REL_WHEEL, n); ms.syn()
    globals().update(inject=inject, mouse=mouse, mbtn=mbtn, wheel=wheel)

# ---- Token ghép đôi (lưu lại để mã QR/bookmark không đổi) ----
TOKEN_FILE = pathlib.Path.home() / ".phonekb_token"
def load_token():
    try:
        t = TOKEN_FILE.read_text().strip()
    except OSError:
        t = ""
    if len(t) < 16:
        t = secrets.token_urlsafe(12)
        try:
            TOKEN_FILE.write_text(t)
        except OSError:
            pass
    return t
TOKEN = load_token()

def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # không gửi gói nào, chỉ để hệ điều hành chọn card mạng
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

MDNS_NAME = "phimtay.local"
mdns_on = False
def advertise(ip):  # tùy chọn: quảng bá tên phimtay.local
    global mdns_on
    try:
        from zeroconf import Zeroconf, ServiceInfo
        info = ServiceInfo("_http._tcp.local.", "PhoneKB._http._tcp.local.", addresses=[socket.inet_aton(ip)],
                           port=PORT, server=MDNS_NAME + ".")
        zc = Zeroconf(); zc.register_service(info); mdns_on = True
        return zc
    except Exception:
        return None

# ---- Điều khiển ----
held, mheld = {}, set()  # phím đang giữ (code -> task lặp hoặc None), nút chuột đang giữ
current = None           # kết nối điều khiển hiện tại (chỉ 1)
acc = {"x": 0.0, "y": 0.0, "z": 0.0}

def release_all():
    for k, t in list(held.items()):
        if t:
            t.cancel()
        inject(k, 0)
    for b in mheld:
        mbtn(b, 0)
    held.clear(); mheld.clear()

async def repeat(k):  # Windows không tự lặp phím giả lập (Linux thì compositor tự lặp)
    await asyncio.sleep(0.4)
    while True:
        inject(k, 1)
        await asyncio.sleep(0.035)

def key(down, k):
    if k not in KEYS:
        return
    if down and k not in held:
        inject(k, 1)
        held[k] = asyncio.ensure_future(repeat(k)) if WIN and k not in NO_REPEAT else None
    elif not down and k in held:
        t = held.pop(k)
        if t:
            t.cancel()
        inject(k, 0)

def notch(a, v, div):
    acc[a] += v / div
    n = int(acc[a]); acc[a] -= n
    return n

def scroll(x, y):  # y > 0: cuộn lên, x > 0: cuộn phải
    if n := notch("y", y, 24): wheel(n, False)
    if n := notch("x", x, 24): wheel(n, True)

def zoom(z):  # phóng/thu = Ctrl + lăn chuột
    if n := notch("z", z, 40):
        own = "ControlLeft" in held
        if not own: inject("ControlLeft", 1)
        wheel(n, False)
        if not own: inject("ControlLeft", 0)

cl = lambda v: max(-300, min(300, int(v)))

async def now_playing():
    try:
        if WIN:
            try:
                from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
            except ImportError:
                from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
            s = (await M.request_async()).get_current_session()
            if not s:
                return ""
            p = await s.try_get_media_properties_async()
            return f"{'▶' if s.get_playback_info().playback_status == 4 else '⏸'} {p.title} - {p.artist}".strip(" -")
        if shutil.which("playerctl"):
            pr = await asyncio.create_subprocess_exec("playerctl", "metadata", "--format", "{{artist}} - {{title}}",
                                                      stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await pr.communicate()
            return out.decode().strip(" -\n")
    except Exception:
        pass
    return ""

async def np_loop(ws):
    last = None
    while not ws.closed:
        t = await now_playing()
        if t != last:
            last = t
            await ws.send_json({"t": "np", "x": t})
        await asyncio.sleep(2)

async def ws_handler(req):
    global current
    if req.query.get("t") != TOKEN:
        raise web.HTTPForbidden()
    ws = web.WebSocketResponse(heartbeat=15)
    await ws.prepare(req)
    if current is not None and not current.closed:
        await current.close()
    release_all()
    current = ws
    np = asyncio.ensure_future(np_loop(ws))
    try:
        async for m in ws:
            if m.type != WSMsgType.TEXT:
                continue
            try:
                d = json.loads(m.data); t = d["t"]
                if t in ("d", "u"): key(t == "d", d["k"])
                elif t == "m": mouse(cl(d["x"]), cl(d["y"]))
                elif t == "s": scroll(float(d["x"]), float(d["y"]))
                elif t == "z": zoom(float(d["z"]))
                elif t == "b" and d["b"] in ("l", "r"):
                    s = 1 if d["s"] else 0
                    (mheld.add if s else mheld.discard)(d["b"]); mbtn(d["b"], s)
            except (ValueError, KeyError, TypeError):
                continue
    finally:
        np.cancel()
        if current is ws:
            current = None
            release_all()
    return ws

# ---- Trang web ----
STATUS = """<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=4>
<meta name=viewport content="width=device-width,initial-scale=1"><title>PhoneKB</title>
<body style="font:16px system-ui;background:#111318;color:#e8eaf0;text-align:center;padding:24px">
<h2>PhoneKB đang chạy</h2><p>Quét mã bằng điện thoại Android (cùng WiFi):</p>
$IMG<p><code>$URL</code></p><p>$MDNS</p><p>Trạng thái: $STATE</p>"""

def status_html():
    url = f"http://{lan_ip()}:{PORT}/?t={TOKEN}"
    img = ""
    try:
        import qrcode, qrcode.image.svg
        raw = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage).to_string()
        img = '<img width=260 style="background:#fff;padding:8px;border-radius:8px" src="data:image/svg+xml;base64,%s">' % base64.b64encode(raw).decode()
    except Exception:
        pass
    mdns = f"Thử tên: http://{MDNS_NAME}:{PORT}/?t={TOKEN}" if mdns_on else ""
    state = "đang có điện thoại điều khiển" if current else "chưa có điện thoại kết nối"
    return STATUS.replace("$IMG", img).replace("$URL", url).replace("$MDNS", mdns).replace("$STATE", state)

async def index(req):
    if "Android" in req.headers.get("User-Agent", "") or "kb" in req.query:
        return web.FileResponse(HERE / "keyboard.html")
    if req.remote in ("127.0.0.1", "::1"):  # chỉ máy chủ mới thấy token
        return web.Response(text=status_html(), content_type="text/html")
    return web.Response(text="Hãy mở địa chỉ này bằng điện thoại Android.", content_type="text/plain")

def main():
    setup_injector()
    ip = lan_ip()
    zc = advertise(ip)
    log(f"PhoneKB: http://{ip}:{PORT}/?t={TOKEN}\nMở http://localhost:{PORT}/ trên máy này để xem mã QR.")
    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/ws", ws_handler)])
    try:
        web.run_app(app, host="0.0.0.0", port=PORT, print=None)
    finally:
        release_all()
        if zc:
            zc.close()

if __name__ == "__main__":
    main()
