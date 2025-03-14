import asyncio
import time
import struct
import pytz
import socketio
from bleak import BleakClient, BleakScanner, BleakError
from location import decode_location_data
from global_var import *

# Kết nối server
sio = socketio.AsyncClient()
time_zone = pytz.timezone('Asia/Ho_Chi_Minh')

tracking_enabled = False
last_sent_time = {}  # Lưu thời gian gửi gần nhất của từng tag
cached_data = {}  # Lưu dữ liệu mới nhất của từng tag
data_queue = asyncio.Queue()  # Hàng đợi gửi dữ liệu


async def safe_emit(event, data):
    """Gửi dữ liệu lên server một cách an toàn."""
    if sio.connected:
        await sio.emit(event, data)
    else:
        print(f"Không thể gửi '{event}' vì không kết nối với server!")


async def connect_to_server():
    """Kết nối server Socket.IO."""
    try:
        await sio.connect(SERVER_URL)
        print("✅ Đã kết nối với server")
    except Exception as e:
        print(f"❌ Lỗi kết nối server: {e}")


@sio.on("start_tracking")
async def start_tracking(data=None):
    """Bật tracking từ server."""
    global tracking_enabled
    tracking_enabled = True
    print("🚀 Tracking đã bật!")


@sio.on("stop_tracking")
async def stop_tracking(data=None):
    """Tắt tracking từ server."""
    global tracking_enabled
    tracking_enabled = False
    print("🛑 Tracking đã dừng!")


async def send_loop():
    """Task liên tục gửi dữ liệu từ hàng đợi."""
    while True:
        tag_data = await data_queue.get()  # Lấy dữ liệu từ hàng đợi
        await safe_emit("tag_data", tag_data)
        data_queue.task_done()  # Đánh dấu hoàn thành


def notification_handler(sender, data, address):
    """Xử lý dữ liệu từ BLE notify, kiểm soát tần suất gửi."""
    global last_sent_time, cached_data, tracking_enabled
    decoded_data = decode_location_data(data)
    current_time = time.time()

    if tracking_enabled:
        # Tracking bật → gửi ngay lập tức vào queue
        asyncio.create_task(data_queue.put({"mac": address, "data": decoded_data}))
        print(f"📡 [Tracking] Tag {address} gửi ngay: {decoded_data}")
    else:
        # Tracking tắt → chỉ gửi mỗi 5 giây
        cached_data[address] = decoded_data
        if current_time - last_sent_time.get(address, 0) >= 5:
            asyncio.create_task(data_queue.put({"mac": address, "data": cached_data[address]}))
            last_sent_time[address] = current_time
            print(f"⌛ [Delay] Tag {address} gửi sau 5s: {decoded_data}")


async def process_device(address, is_tag=False, max_retries=3):
    """Kết nối BLE với Tag hoặc Anchor."""
    client = BleakClient(address)
    for attempt in range(max_retries):
        try:
            await client.connect()
            if not client.is_connected:
                print(f"❌ Không thể kết nối {address}, thử lần {attempt + 1}")
                await asyncio.sleep(2)
                continue

            print(f"✅ Kết nối {address} thành công")

            if is_tag:
                print(f"🕹️ Chờ server cho phép tracking từ {address}...")
                await client.start_notify(LOCATION_DATA_UUID, lambda s, d: notification_handler(s, d, address))

                while True:
                    await asyncio.sleep(1)  # Giữ kết nối nhưng không nghẽn

            else:  # Nếu là anchor
                data = await client.read_gatt_char(LOCATION_DATA_UUID)
                operation_mode_data = await client.read_gatt_char(OPERATION_MODE_UUID)
                decoded_data = decode_location_data(data)
                operation_mode_value = int.from_bytes(operation_mode_data[:2], byteorder="big")
                operation_mode_binary = f"{operation_mode_value:016b}"

                print(f"🏗️ Anchor {address} gửi dữ liệu: {decoded_data}")
                await safe_emit("anchor_data", {"mac": address, "data": decoded_data, "operation_mode": operation_mode_binary})

            break  # Thoát vòng lặp nếu kết nối thành công

        except BleakError as e:
            print(f"⚠️ Lỗi BLE {address}: {e}")
            await asyncio.sleep(2)  # Đợi trước khi thử lại
        except asyncio.TimeoutError:
            print(f"⏳ Timeout khi kết nối {address}")
        except Exception as e:
            print(f"🚨 Lỗi không xác định với {address}: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()


async def main():
    """Chương trình chính."""
    await connect_to_server()
    asyncio.create_task(send_loop())  # Chạy task gửi dữ liệu riêng

    # Tìm các thiết bị BLE
    devices = await BleakScanner.discover(10)
    anchors = [dev.address for dev in devices if dev.address in MAC_ADDRESS_ANCHOR_LIST]
    print(f"🛰️ Danh sách anchor: {anchors}")

    print("📡 Chờ server lệnh để xử lý Tag...")

    # Khởi chạy task cho từng Tag
    tasks = [asyncio.create_task(process_device(tag, is_tag=True)) for tag in TAG_MAC_LIST]

    await asyncio.gather(*tasks)  # Đợi tất cả task hoàn thành
    await sio.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print(f"❌ Lỗi runtime: {e}")
