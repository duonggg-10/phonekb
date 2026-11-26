#!/usr/bin/env python3
"""PhoneKB: dùng điện thoại Android làm bàn phím rời qua WiFi (server chạy trên Windows/Linux)."""
import asyncio, base64, json, os, pathlib, secrets, socket, sys
from aiohttp import web, WSMsgType

PORT = int(os.environ.get("PHONEKB_PORT", 3636))
HERE = pathlib.Path(__file__).resolve().parent
WIN = sys.platform == "win32"
log = print if sys.stdout else (lambda *a, **k: None)  # pythonw không có stdout

# ---- Bảng phím: KeyboardEvent.code -> (scancode set 1, extended, mã evdev) ----
NAMES = ("Escape Digit1 Digit2 Digit3 Digit4 Digit5 Digit6 Digit7 Digit8 Digit9 Digit0 Minus Equal Backspace Tab "
         "KeyQ KeyW KeyE KeyR KeyT KeyY KeyU KeyI KeyO KeyP BracketLeft BracketRight Enter ControlLeft "
         "KeyA KeyS KeyD KeyF KeyG KeyH KeyJ KeyK KeyL Semicolon Quote Backquote ShiftLeft Backslash "
         "KeyZ KeyX KeyC KeyV KeyB KeyN KeyM Comma Period Slash ShiftRight - AltLeft Space CapsLock "
         "F1 F2 F3 F4 F5 F6 F7 F8 F9 F10").split()
KEYS = {n: (i + 1, False, i + 1) for i, n in enumerate(NAMES) if n != "-"}
KEYS["F11"], KEYS["F12"] = (0x57, False, 87), (0x58, False, 88)
EXT = {"Home": (0x47, 102), "ArrowUp": (0x48, 103), "PageUp": (0x49, 104), "ArrowLeft": (0x4B, 105),
       "ArrowRight": (0x4D, 106), "End": (0x4F, 107), "ArrowDown": (0x50, 108), "PageDown": (0x51, 109),
       "Insert": (0x52, 110), "Delete": (0x53, 111), "MetaLeft": (0x5B, 125), "ControlRight": (0x1D, 97),
       "AltRight": (0x38, 100), "ContextMenu": (0x5D, 127)}
KEYS.update({k: (s, True, c) for k, (s, c) in EXT.items()})
NO_REPEAT = {"ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight", "AltLeft", "AltRight", "MetaLeft", "CapsLock"}

# ---- Gõ phím vào hệ điều hành. Luôn gửi scancode "vật lý" (không gửi Unicode) để
# ---- Unikey/EVKey/iBus-Bamboo nhận được như phím từ bàn phím thật.
inject = None
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

    def inject(k, state):  # state: 1 = nhấn, 0 = nhả
        sc, ext, _ = KEYS[k]
        flags = 0x8 | (1 if ext else 0) | (0 if state else 2)  # SCANCODE | EXTENDEDKEY | KEYUP
        inp = INPUT(1, IU(ki=KI(0, sc, flags, 0, 0)))
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def setup_injector():
    global inject
    if WIN:
        return
    try:
        from evdev import UInput, ecodes as ec
        ui = UInput({ec.EV_KEY: sorted({v[2] for v in KEYS.values()})}, name="PhoneKB")
    except Exception as ex:
        sys.exit(f"Không tạo được bàn phím ảo /dev/uinput ({ex}).\nXem mục Linux trong README.md")

    def _inject(k, state):
        ui.write(ec.EV_KEY, KEYS[k][2], state)
        ui.syn()
    inject = _inject

# ---- Token ghép đôi (lưu lại để mã QR/bookmark không đổi mỗi lần khởi động) ----
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
def advertise(ip):  # tùy chọn, thử quảng bá tên phimtay.local
    global mdns_on
    try:
        from zeroconf import Zeroconf, ServiceInfo
        info = ServiceInfo("_http._tcp.local.", "PhoneKB._http._tcp.local.", addresses=[socket.inet_aton(ip)],
                           port=PORT, server=MDNS_NAME + ".")
        zc = Zeroconf(); zc.register_service(info); mdns_on = True
        return zc
    except Exception:
        return None

# ---- WebSocket nhận phím ----
held = {}       # code -> task lặp phím (chỉ Windows) hoặc None
current = None  # kết nối điều khiển hiện tại (chỉ 1)

def release_all():
    for k, t in list(held.items()):
        if t:
            t.cancel()
        inject(k, 0)
    held.clear()

async def repeat(k):  # Windows không tự lặp phím giả lập; Linux thì compositor tự lặp
    await asyncio.sleep(0.4)
    while True:
        inject(k, 1)
        await asyncio.sleep(0.035)

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
    try:
        async for m in ws:
            if m.type != WSMsgType.TEXT:
                continue
            try:
                d = json.loads(m.data); k, t = d["k"], d["t"]
            except (ValueError, KeyError, TypeError):
                continue
            if k not in KEYS:
                continue
            if t == "d" and k not in held:
                inject(k, 1)
                held[k] = asyncio.ensure_future(repeat(k)) if WIN and k not in NO_REPEAT else None
            elif t == "u" and k in held:
                task = held.pop(k)
                if task:
                    task.cancel()
                inject(k, 0)
    finally:
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
        if current is not None or held:
            release_all()
        if zc:
            zc.close()

if __name__ == "__main__":
    main()
