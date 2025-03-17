import socketio
import asyncio
from config import SERVER_URL


sio = socketio.AsyncClient()
TIMEOUT = 5
TRACKING_ENABLE = False
command_queue = asyncio.Queue()

async def safe_emit(event, data):
    if sio.connected:
        await sio.emit(event, data)
        return True
    else:
        print(f"❌ Không thể gửi '{event}' vì không kết nối với server!")
        return False

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
async def update_operation(data):
    mode = data.get("type")
    mac_address = data.get("data", {}).get("mac")
    payload = data.get("data", {}).get("payload")
    if mode == "operation" and mac_address and payload:
        await command_queue.put((mac_address, payload))
        print(f"Nhận lệnh update {mac_address}: {payload}")



