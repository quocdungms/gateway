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

TRACKING_ENABLE = False
LAST_SENT_TIME = {}  # Lưu thời gian gửi gần nhất của từng tag
cached_data = {}  # Lưu dữ liệu mới nhất của từng tag


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
    global TRACKING_ENABLE
    tracking_enabled = True
    print("🚀 Tracking đã bật!")


@sio.on("stop_tracking")
async def stop_tracking(data=None):
    """Tắt tracking từ server."""
    global TRACKING_ENABLE
    tracking_enabled = False
    print("🛑 Tracking đã dừng!")


def notification_handler(sender, data, address):
    """Xử lý dữ liệu từ BLE notify, kiểm soát tần suất gửi."""
    global LAST_SENT_TIME, cached_data
    decoded_data = decode_location_data(data)
    current_time = time.time()

    if TRACKING_ENABLE:
        asyncio.create_task(safe_emit("tag_data", {"mac": address, "data": decoded_data}))
        print(f"📡 [Tracking] Tag {address} gửi ngay: {decoded_data}")
    else:
        # Lưu dữ liệu vào cache nhưng chỉ gửi nếu đủ 5 giây
        cached_data[address] = decoded_data
        if current_time - last_sent_time.get(address, 0) >= 5:
            asyncio.create_task(safe_emit("tag_data", {"mac": address, "data": cached_data[address]}))
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

                # while True:
                #     if tracking_enabled:
                #         await asyncio.sleep(2)  # Gửi liên tục khi bật tracking
                #     else:
                #         await asyncio.sleep(5)  # Gửi mỗi 5 giây khi tracking tắt

                while True:
                    await asyncio.sleep(0)
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
