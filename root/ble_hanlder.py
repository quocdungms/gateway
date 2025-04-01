import asyncio


import pytz
from bleak import BleakClient, BleakScanner, BleakError
from helper import decode_location_data

from config import OPERATION_MODE_UUID, LOCATION_DATA_MODE_UUID, LOCATION_DATA_UUID
import time


# Global_var
TIMEOUT = 5
time_zone = pytz.timezone('Asia/Ho_Chi_Minh')
LAST_SENT_TIME = {}
INTERVAL = 5
DISCONNECTED_TAGS = set()

def set_operation_mode(mac_address, payload, device_type):
    print("sdaasg")

def set_location_mode(mac_address, payload, device_type):
    print("sdaasg")

def set_anchor_location(mac_address, payload, device_type):
    print("sdaasg")

def set_tag_rate(mac_address, payload, device_type):
    print("sdaasg")


async def notification_handler(sender, data, address):
    """Xử lý dữ liệu từ BLE notify, kiểm soát tần suất gửi."""
    global LAST_SENT_TIME, INTERVAL
    from server_handler import TRACKING_ENABLE, safe_emit
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
    from server_handler import safe_emit
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



# async def write_operation_mode(client, address, operation_data, current_uuid, max_retry=3) :
#     await client.stop_notify(current_uuid)
#     from helper import bit_string_to_byte_array
#     operation_data = bit_string_to_byte_array(operation_data)
#     for attempt in range(max_retry):
#         try:
#             await client.write_gatt_char(OPERATION_MODE_UUID, operation_data)
#             print(f"Ghi du lieu operation mode thanh cong vao {address}")
#             break
#         except BleakError as e:
#             attempt += 1
#             print(f"Loi khi ghi operation mode (lan {attempt}) : {e}")
#             if attempt <= max_retry:
#                 await asyncio.sleep(TIMEOUT)
#
#     # print(f"✅ Ghi operation mode thành công {address}")
