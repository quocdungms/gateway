import socketio
import asyncio
from config import SERVER_URL, TAG_MAC_LIST, ANCHOR_MAC_LIST


sio = socketio.AsyncClient()
TIMEOUT = 5
TRACKING_ENABLE = False
command_queue = asyncio.Queue()

async def safe_emit(event, data):
    if sio.connected:
        await sio.emit(event, data)
    else:
        print(f"❌ Không thể gửi '{event}' vì không kết nối với server!")

async def connect_to_server(max_retries=3):
    """Kết nối đến server với khả năng tự động thử lại."""
    global sio
    if sio.connected:
        print("✅ Đã kết nối đến Server!")
        return

    for attempt in range(max_retries):
        if sio.connected:  # Kiểm tra lại trước khi thử kết nối
            print("✅ Server đã kết nối, không cần thử nữa!")
            return
        try:
            print(f"🌐 Đang kết nối đến server (Thử lần {attempt + 1})...")
            await sio.connect(SERVER_URL)

            if sio.connected:
                print("✅ Đã kết nối với server!")
                return  # Dừng vòng lặp nếu kết nối thành công

        except Exception as e:
            print(f"❌ Lỗi kết nối server: {e}")
            await asyncio.sleep(TIMEOUT)  # Chờ trước khi thử lại

    while True:
        if sio.connected:
            print("✅ Server đã kết nối, không cần thử lại!")
            return
        try:
            print(f"🔄 Server vẫn chưa kết nối được, thử lại sau {TIMEOUT} giây...")
            await asyncio.sleep(TIMEOUT)
            await sio.connect(SERVER_URL)

            if sio.connected:
                print("✅ Server đã kết nối lại thành công!")
                return

        except Exception as e:
            print(f"❌ Lỗi kết nối server: {e}")

@sio.event
async def disconnect():
    print("⚠️ Mất kết nối với server! Đang thử kết nối lại...")
    asyncio.create_task(connect_to_server())

@sio.on("start_tracking")
async def start_tracking(data=None):
    """Bật tracking từ server."""
    global TRACKING_ENABLE
    TRACKING_ENABLE = True
    print("Tracking đã bật!")


@sio.on("stop_tracking")
async def stop_tracking(data=None):
    """Tắt tracking từ server."""
    global TRACKING_ENABLE
    TRACKING_ENABLE = False
    print("Tracking đã dừng!")

@sio.on("update-device")
async def update_device_handler(msg):
    from ble_hanlder import set_operation_mode, set_location_mode, set_anchor_location, set_tag_rate

    cmd = msg.get("command")
    data = msg.get("data", {})
    mac_address = data.get("mac")
    payload = data.get("payload")
    # print(f"Nhan yeu cau tu server: command: {cmd}, data: {data}")

    if all([cmd, mac_address, payload]) is not None:
        print(f"Nhan lenh: {cmd} cho {mac_address}, payload: {payload}")
        await command_queue.put((cmd, mac_address, payload))


    is_tag = mac_address in TAG_MAC_LIST
    is_anchor = mac_address in ANCHOR_MAC_LIST

    if not (is_tag or is_anchor):
        print(f"Khong tim thay {mac_address} trong danh sach thiet bi")
        return
    if cmd == "set-operation-mode":
        if is_tag:
            set_operation_mode(mac_address, payload, device_type = "tag")
        else:
            set_operation_mode(mac_address, payload, device_type = "anchor")
    elif cmd == "set-location-mode":
        if is_tag:
            set_location_mode(mac_address,payload,device_type="tag")
        else:
            set_location_mode(mac_address,payload,device_type="anchor")
    elif cmd == "set-anchor-location":
        set_anchor_location(mac_address,payload)
    elif cmd == "set-tag-rate":
        set_tag_rate(mac_address,payload)


