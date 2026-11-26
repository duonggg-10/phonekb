# PhoneKB

Turn your Android phone into a wireless external keyboard for your computer over WiFi. Your phone only needs a browser (Chrome or Firefox)—no app installation required. A small server runs in the background on your computer (Windows or Linux) and types keys for you.

```
[Phone: browser] --WebSocket--> [Python Server on PC] --SendInput / uinput--> keys typed into the machine
```

## Features

- Full keyboard, landscape layout: QWERTY, number row, F1–F12, 4 arrow keys, Insert/Delete/Home/End/PgUp/PgDn, Ctrl/Alt/Win/Menu.
- Sends separate key-down and key-up events, so holding keys, typing shortcuts (Ctrl+C, Alt+Tab, etc.), and multi-touch all work.
- Sticky keys for Shift/Ctrl/Alt/Win: quick tap to hold, tap again to release.
- Compatible with Vietnamese IMEs (Unikey, EVKey, iBus-Bamboo, etc.): keys are sent as physical scancodes like a real keyboard, and the IME on your PC handles Telex/VNI as usual.
- Pair via QR code with a token—no need to type an IP address.
- Auto-discovery: your Android phone sees the keyboard, and opening `localhost` on the host shows the status page and QR code.
- Only one phone can control at a time. When disconnected, any held keys are released automatically.

## Requirements

| | |
|---|---|
| Computer (running server) | Windows 10/11, or Linux (Ubuntu, Arch, X11 or Wayland) |
| Phone | Android, Chrome/Chromium or Firefox |
| Network | Phone and computer on the same WiFi/LAN network |
| Software | Python 3.9 or newer |

macOS and iOS are not supported. Not aimed at gaming.

## Installation

```bash
git clone https://github.com/duonggg-10/phonekb phonekb
cd phonekb
pip install -r requirements.txt
python server.py
```

On your computer, open `http://localhost:3636/` to view the QR code, then scan it with your phone. From the next time onward, your phone's browser remembers the token—just reopen the same address or save it to your home screen.

When opening on your phone, tap **Fullscreen** to rotate to landscape and get more room.

## Configuration

| Environment variable | Default | Meaning |
|---|---|---|
| `PHONEKB_PORT` | `3636` | Server port |

The pairing token is randomly generated and stored at `~/.phonekb_token`, so the QR code stays the same across runs. Delete this file to rotate the token.

## Windows

- On first run, allow Python through Windows Firewall (Private networks).
- Run in the background without a window: `pythonw server.py`, and place a shortcut in the `shell:startup` folder to start automatically at login.
- Windows running as Administrator only receive keystrokes if the server is also running as Administrator.

## Linux

The server creates a virtual keyboard via `/dev/uinput` (works on both X11 and Wayland), so a one-time permission setup is needed:

```bash
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo usermod -aG input $USER
sudo modprobe uinput && echo uinput | sudo tee /etc/modules-load.d/uinput.conf
sudo udevadm control --reload && sudo udevadm trigger
```

Then log out and log back in. To run in the background with systemd, create `~/.config/systemd/user/phonekb.service`:

```ini
[Service]
ExecStart=/usr/bin/python3 %h/phonekb/server.py
Restart=on-failure

[Install]
WantedBy=default.target
```

then run `systemctl --user enable --now phonekb`.

## Typing Vietnamese

PhoneKB does not send Unicode characters; it sends physical key events just like an attached keyboard. Turn on your IME (Unikey, EVKey, iBus-Bamboo, etc.) on your computer as usual and type Telex/VNI from the virtual keyboard. To switch between Vietnamese and English, use your IME's shortcut in combination with the sticky Ctrl/Shift/Alt keys on your phone.

## Security

Anyone with the token can type into your computer, which means nearly full control of the machine.

- The token is only shown on the host's `localhost` page and is not exposed to other devices on the network.
- The server listens on all network interfaces. Only use it on a trusted WiFi network, and do not expose the port to the internet.
- The connection uses plain HTTP without encryption. Do not use it on public networks.
- To revoke access, delete `~/.phonekb_token` and restart the server.

## Troubleshooting

| Symptom | How to fix |
|---|---|
| `localhost:3636` shows another program | The port is in use. Change it with `PHONEKB_PORT`, or close the other program. |
| Phone cannot connect | Check that both are on the same WiFi, the firewall allows the port, and the router does not have "client isolation" enabled (common on hotel/café WiFi). |
| Linux reports `/dev/uinput` error | Follow the Linux section above, and remember to log out and log back in. |
| Keys do not go into Admin windows (Windows) | Run the server as Administrator. |
| Phone screen turns off automatically | The page runs over HTTP, so Wake Lock is unavailable. Increase the screen timeout in Android settings. |
| Cannot lock landscape orientation | The orientation lock API requires fullscreen and may behave differently between Chrome and Firefox. Turn on auto-rotate and rotate your phone sideways. |
| `phimtay.local` does not open | The mDNS name is only a fallback. Use the QR code or IP address. |

## Structure

```
phonekb/
├── server.py          # HTTP + WebSocket server, sends keystrokes to the OS
├── keyboard.html      # phone keyboard UI
├── requirements.txt
└── README.md
```

## Protocol

The phone sends small JSON messages over `ws://<host>:<port>/ws?t=<token>`, using `KeyboardEvent.code` as the key code:

```json
{"t": "d", "k": "KeyA"}
{"t": "u", "k": "KeyA"}
```

`d` means key down, and `u` means key up. Key codes not in the server's mapping table are ignored.

## Known Limitations

- Only supports the QWERTY (US style) layout. The physical keyboard on your PC should be set to the US layout.
- No numpad, media keys, or PrintScreen/Pause/ScrollLock yet.
- Does not support games that require low-level key scanning.
