import asyncio
from tkinter.constants import CURRENT

import pytz
from bleak import BleakClient, BleakScanner, BleakError
from helper import decode_location_data
from server_handler import safe_emit
from config import OPERATION_MODE_UUID, LOCATION_DATA_MODE_UUID, LOCATION_DATA_UUID
import time


# Global_var
TIMEOUT = 5
time_zone = pytz.timezone('Asia/Ho_Chi_Minh')
last_sent_time = {}
INTERVAL = 5
DISCONNECTED_TAGS = set()


async def notification_handler(sender, data, address):
    """Xử lý dữ liệu từ BLE notify, kiểm soát tần suất gửi."""
    global last_sent_time, INTERVAL
    from server_handler import TRACKING_ENABLE
    decoded_data = decode_location_data(data)
    current_time = time.time()

    if TRACKING_ENABLE:
        await safe_emit("tag_data", {"mac": address, "data": decoded_data})
        print(f"📨 Tag {address} gửi dữ liệu!\nTracking = {TRACKING_ENABLE}\nData: {decoded_data} \n")
    else:
        last_sent = last_sent_time.get(address, 0)
        if current_time - last_sent >= INTERVAL:
            if await safe_emit("tag_data", {"mac": address, "data": decoded_data}):
                last_sent_time[address] = current_time
                print(
                    f"📨 Tag [{address}] gửi dữ liệu!\nTracing = {TRACKING_ENABLE} - Delay: {INTERVAL}s\nData: {decoded_data} \n")


async def process_anchor(address):
    """Xử lý kết nối với Anchor: Chỉ kết thúc khi gửi dữ liệu thành công."""
    client = BleakClient(address)
    while True:
        try:
            print(f"🔍 Đang kết nối Anchor {address}...")
            await client.connect()
            if not client.is_connected:
                print(f"❌ Không thể kết nối {address}, thử lại sau {TIMEOUT} giây...")
                await asyncio.sleep(TIMEOUT)
                continue

            print(f"✅ Đã kết nối {address}, đọc dữ liệu...")
            data = await client.read_gatt_char(LOCATION_DATA_UUID)
            operation_mode_data = await client.read_gatt_char(OPERATION_MODE_UUID)

            decoded_data = decode_location_data(data)
            operation_mode_value = int.from_bytes(operation_mode_data[:2], byteorder="big")
            operation_mode_binary = f"{operation_mode_value:016b}"

            print(f"📨 Anchor {address} gửi dữ liệu: {decoded_data}")
            await safe_emit("anchor_data", {
                "mac": address,
                "data": decoded_data,
                "operation_mode": operation_mode_binary
            })
            # Gửi thành công thì kết thúc vòng lặp, không quét lại
            break

        except BleakError as e:
            print(f"❌ Lỗi BLE {address}: {e}")
            await asyncio.sleep(TIMEOUT)
        except Exception as e:
            print(f"❌ Lỗi không xác định với {address}: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()
    print(f"✅ Hoàn thành xử lý Anchor {address}, không quét lại!")


async def process_tag(address, max_retries=3):
    """Xử lý kết nối với Tag và tự động kết nối lại khi mất kết nối."""
    global DISCONNECTED_TAGS
    while True:
        client = BleakClient(address)
        for attempt in range(max_retries):
            try:
                await client.connect()
                if not client.is_connected:
                    print(f"❌ Không thể kết nối {address}, thử lần {attempt + 1}")
                    await asyncio.sleep(TIMEOUT)
                    continue

                print(f"✅ Kết nối {address} thành công, bắt đầu nhận dữ liệu...")
                DISCONNECTED_TAGS.discard(address)  # Đánh dấu là đã kết nối lại
                # Nhận notify từ Tag
                current_uuid = LOCATION_DATA_UUID
                await client.start_notify(current_uuid,
                                          lambda s, d: asyncio.create_task(notification_handler(s, d, address))
                                          )

                while client.is_connected:
                    try:

                    await asyncio.sleep(1)  # Giữ kết nối

            except BleakError as e:
                print(f"❌ Lỗi BLE {address}: {e}")
            except asyncio.TimeoutError:
                print(f"❌ Timeout khi kết nối {address}")
            except Exception as e:
                print(f"❌ Lỗi không xác định với {address}: {e}")
            finally:
                if client.is_connected:
                    await client.disconnect()

        # Nếu thử 3 lần vẫn lỗi thì vào chế độ chờ, quét lại mỗi 10s
        print(f"🔄 Không thể kết nối {address}, thử lại sau {TIMEOUT}s ...")
        DISCONNECTED_TAGS.add(address)
        await asyncio.sleep(TIMEOUT)

async def ensure_notify_stopped(client, current_uuid):
    if await client.stop_notify(current_uuid):
        return True
    return False

async def write_operation_mode(client, address, operation_mode):
    from helper import byte
    operation_mode =