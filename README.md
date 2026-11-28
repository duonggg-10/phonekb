# PhoneKB

Biến điện thoại Android thành bàn phím rời không dây cho máy tính qua WiFi. Điện thoại chỉ cần một trình duyệt (Chrome hoặc Firefox), không cần cài ứng dụng. Server nhỏ chạy nền trên máy tính (Windows hoặc Linux) và gõ phím thay cho bạn.

```
[Điện thoại: trình duyệt] --WebSocket--> [Server Python trên PC] --SendInput / uinput--> phím được gõ vào máy
```

## Tính năng

- Bàn phím đầy đủ, bố cục ngang: QWERTY, hàng số, 4 phím mũi tên, Insert/Delete/Home/End/PgUp/PgDn, Ctrl/Alt/Win/Menu.
- **Touch bar** phía trên (vuốt trái/phải để đổi trang): F1-F12 và Esc; điều khiển media (tên bài/tab đang phát, bài trước, phát/tạm dừng, bài sau); âm lượng, tắt tiếng, độ sáng, PrtSc.
- **Bàn di chuột** và hai nút chuột: một ngón di chuyển, chạm để click trái; hai ngón để cuộn, chụm/giãn để zoom (Ctrl + lăn chuột), chạm hai ngón để click phải.
- Gửi sự kiện nhấn và nhả phím riêng biệt, nên giữ phím, gõ tổ hợp (Ctrl+C, Alt+Tab...) và đa chạm đều hoạt động.
- Phím dính cho Shift/Ctrl/Alt/Win: chạm nhanh để giữ, chạm lần nữa để nhả.
- Tương thích bộ gõ tiếng Việt (Unikey, EVKey, iBus-Bamboo...): phím được gửi dưới dạng scancode vật lý như bàn phím thật, bộ gõ trên PC tự xử lý Telex/VNI.
- Ghép đôi bằng mã QR kèm token, không cần nhập IP.
- Tự nhận thiết bị: điện thoại Android thấy bàn phím, máy chủ mở `localhost` thấy trang trạng thái và mã QR.
- Chỉ một điện thoại điều khiển cùng lúc. Khi mất kết nối, mọi phím đang giữ được nhả tự động.

## Yêu cầu

| | |
|---|---|
| Máy tính (chạy server) | Windows 10/11, hoặc Linux (Ubuntu, Arch, X11 hoặc Wayland) |
| Điện thoại | Android, Chrome/Chromium hoặc Firefox |
| Mạng | Điện thoại và máy tính cùng một mạng WiFi/LAN |
| Phần mềm | Python 3.9 trở lên |

Không hỗ trợ macOS và iOS. Không nhắm tới việc chơi game.

## Cài đặt

```bash
git clone <địa-chỉ-repo-của-bạn> phonekb
cd phonekb
pip install -r requirements.txt
python server.py
```

Trên máy tính, mở `http://localhost:3636/` để xem mã QR, rồi quét bằng điện thoại. Từ lần sau, trình duyệt điện thoại nhớ token, bạn chỉ cần mở lại cùng địa chỉ hoặc lưu vào màn hình chính.

Khi mở bằng điện thoại, nên bấm **Toàn màn hình** để xoay ngang và có nhiều chỗ hơn.

## Cấu hình

| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| `PHONEKB_PORT` | `3636` | Cổng server |

Token ghép đôi được sinh ngẫu nhiên và lưu ở `~/.phonekb_token`, nên mã QR không đổi giữa các lần chạy. Xóa file này để đổi token.

## Tên bài đang phát và độ sáng

- Windows: tên bài cần gói `winsdk` (đã có trong `requirements.txt`; nếu cài lỗi với Python mới, thử `pip install winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections`). Nút độ sáng chỉ chỉnh được màn hình tích hợp của laptop.
- Linux: tên bài cần `playerctl` (`sudo apt install playerctl` hoặc `sudo pacman -S playerctl`). Nút độ sáng và âm lượng do môi trường desktop xử lý.

## Windows

- Lần đầu chạy, cho phép Python đi qua Windows Firewall (mạng Private).
- Chạy nền không cửa sổ: `pythonw server.py`, và đặt shortcut vào thư mục `shell:startup` để tự chạy khi đăng nhập.
- Cửa sổ đang chạy quyền Administrator chỉ nhận phím nếu server cũng chạy bằng quyền Administrator.

## Linux

Server tạo bàn phím ảo qua `/dev/uinput` (chạy được cả X11 và Wayland), nên cần cấp quyền một lần:

```bash
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo usermod -aG input $USER
sudo modprobe uinput && echo uinput | sudo tee /etc/modules-load.d/uinput.conf
sudo udevadm control --reload && sudo udevadm trigger
```

Sau đó đăng xuất và đăng nhập lại. Để chạy nền bằng systemd, tạo `~/.config/systemd/user/phonekb.service`:

```ini
[Service]
ExecStart=/usr/bin/python3 %h/phonekb/server.py
Restart=on-failure

[Install]
WantedBy=default.target
```

rồi chạy `systemctl --user enable --now phonekb`.

## Gõ tiếng Việt

PhoneKB không gửi ký tự Unicode mà gửi phím vật lý, giống như bàn phím gắn vào máy. Vì vậy hãy bật bộ gõ (Unikey, EVKey, iBus-Bamboo...) trên máy tính như thường lệ và gõ Telex/VNI từ bàn phím ảo. Để đổi Việt/Anh, dùng phím tắt của bộ gõ, kết hợp phím dính Ctrl/Shift/Alt trên điện thoại.

## Bảo mật

Ai có token đều có thể gõ vào máy của bạn, tức là gần như điều khiển được máy.

- Token chỉ hiển thị trên trang `localhost` của máy chủ, không lộ cho thiết bị khác trong mạng.
- Server nghe trên mọi card mạng. Chỉ dùng trên mạng WiFi tin cậy, và không mở cổng ra Internet.
- Kết nối dùng HTTP thường, không mã hóa. Đừng dùng trên mạng công cộng.
- Muốn thu hồi quyền truy cập, xóa `~/.phonekb_token` và khởi động lại server.

## Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| `localhost:3636` ra chương trình khác | Cổng đang bị chiếm. Đổi bằng `PHONEKB_PORT`, hoặc tắt chương trình kia. |
| Điện thoại không vào được | Kiểm tra cùng WiFi, firewall có mở cổng, và router không bật "client isolation" (WiFi khách sạn/quán cà phê thường bật). |
| Linux báo lỗi `/dev/uinput` | Làm theo mục Linux ở trên, nhớ đăng xuất/đăng nhập lại. |
| Phím không vào cửa sổ Admin (Windows) | Chạy server bằng quyền Administrator. |
| Màn hình điện thoại tự tắt | Trang chạy HTTP nên không dùng được Wake Lock. Tăng thời gian tắt màn hình trong cài đặt Android. |
| Không khóa được xoay ngang | API khóa xoay cần toàn màn hình và có thể khác nhau giữa Chrome và Firefox. Hãy bật xoay tự động rồi xoay ngang máy. |
| Tên `phimtay.local` không mở được | Tên mDNS chỉ là phương án phụ. Dùng mã QR hoặc địa chỉ IP. |

## Cấu trúc

```
phonekb/
├── server.py          # server HTTP + WebSocket, gõ phím vào hệ điều hành
├── keyboard.html      # giao diện bàn phím trên điện thoại
├── requirements.txt
└── README.md
```

## Giao thức

Điện thoại gửi qua `ws://<máy>:<cổng>/ws?t=<token>` các tin JSON nhỏ, dùng `KeyboardEvent.code` làm mã phím:

```json
{"t": "d", "k": "KeyA"}
{"t": "u", "k": "KeyA"}
```

`d` là nhấn xuống, `u` là nhả. Mã phím không có trong bảng của server sẽ bị bỏ qua.

## Hạn chế đã biết

- Chỉ hỗ trợ bố cục phím QWERTY (kiểu Mỹ). Bàn phím vật lý trên PC nên đặt bố cục US.
- Chưa có phím số bên phải (numpad), Pause/ScrollLock; chưa có kéo-thả bằng cách chạm hai lần trên bàn di chuột (dùng nút Trái để kéo).
- Chưa hỗ trợ game cần quét phím ở mức thấp.
