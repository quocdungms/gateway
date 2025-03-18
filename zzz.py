import asyncio
import time
import pytz
import socketio
from bleak import BleakClient, BleakScanner, BleakError
from location import decode_location_data
from global_var import *

sio = socketio.AsyncClient()
time_zone = pytz.timezone('Asia/Ho_Chi_Minh')

TRACKING_ENABLE = False
LAST_SENT_TIME = {}  # Lưu thời gian gửi gần nhất của từng tag
INTERVAL = 5
TIMEOUT = 5
DISCONNECTED_TAGS = set()  # Danh sách Tag bị mất kết nối



# NETWORK NODE  CHARACTERISTIC
SERVICE_UUID = "680c21d9-c946-4c1f-9c11-baa1c21329e7"
NAME_UUID = "00002a00-0000-1000-8000-00805f9b34fb"  # Label (GAP service)
OPERATION_MODE_UUID = "3f0afd88-7770-46b0-b5e7-9fc099598964"  # Operation mode UUID
LOCATION_DATA_UUID = "003bbdf2-c634-4b3d-ab56-7ec889b89a37"  # Location Data
LOCATION_DATA_MODE_UUID = "a02b947e-df97-4516-996a-1882521e0ead"  # Location Data Mode


NETWORK_NODE_SERVICE_UUID = "680c21d9-c946-4c1f-9c11-baa1c21329e7"
LABEL_CHAR_UUID = "00002a00-0000-1000-8000-00805f9b34fb"
OPERATION_MODE_CHAR_UUID = "3f0afd88-7770-46b0-b5e7-9fc099598964"
LOCATION_DATA_CHAR_UUID = "003bbdf2-c634-4b3d-ab56-7ec889b89a37"



DEVICE_INFO = "1e63b1ebd4ed-444eaf54-c1e965192501"
NETWORK_ID_UUID = "80f9d8bc-3bff-45bb-a181-2d6a37991208"
# ANCHOR SPECIFIC

LOCATION_PROXY_UUID = "f4a67d7d-379d-4183-9c03-4b6ea5103291"

# TAG SPECIFIC
UPDATE_RATE_UUID = "7bd47f30-5602-4389-b069-8305731308b6"

TAG_MAC = "EB:52:53:F5:D5:90"
TAG_2 = "E9:82:21:9E:C8:8F"
TAG_MAC_LIST= [
  'EB:52:53:F5:D5:90',
  'E9:82:21:9E:C8:8F'
]
# SERVER URL
# SERVER_URL = "http://172.16.2.92:5000"
# SERVER_URL = "http://192.168.137.128:5000"
SERVER_URL = "http://localhost:5000"
MAC_ADDRESS_ANCHOR_LIST = [ 
  'D7:7A:01:92:9B:DB',
  'C8:70:52:60:9F:38',
  'EB:C3:F1:BC:24:DD',
  'E7:E1:0F:DA:2D:82'
]








import struct

def decode_location_data(data):
    try:
        mode = data[0]
        if mode == 0:
            if len(data) <= 13:
                print("Invalid Type 0 data: Expected 13 bytes")
                return None
            return decode_location_mode_0(data)
        elif mode == 1:
            return decode_location_mode_1(data)
        elif mode == 2:
            return decode_location_mode_2(data)
        else:
            print(f"Unknown location mode: {mode}")

    except Exception as e:
        print(f"Error decoding location: {e}")
        return None


# Position Only
def decode_location_mode_0(data):
    result = {}
    # location_mode = data[0]
    # result["Mode:"] = location_mode
    x, y, z, quality_position = struct.unpack("<i i i B", data[1:14])
    result["Position"] = {
        "X": x / 1000,  # Chuyển từ mm sang m
        "Y": y / 1000,
        "Z": z / 1000,
        "Quality Factor": quality_position
    }
    return result

# Distances Only
def decode_location_mode_1(data):
    result = {}
    distances = []
    distance_count = data[0]
    result["Distances count:"] = distance_count
    for i in range(distance_count):
        offset = 1 + i * 7
        node_id, distance, quality = struct.unpack("<H i B", data[offset:offset + 7])
        distances.append({
            "Node ID": node_id,
            "Distance": distance / 1000,  # Chuyển từ mm sang m
            "Quality Factor": quality
        })
    result["Distances"] = distances
    return result

# Hàm giải mã Location Data Mode 2 (Position + Distances)
def decode_location_mode_2(data):
    result = {}
    mode_0 = decode_location_mode_0(data[:14])
    mode_1 = decode_location_mode_1(data[14:])
    result.update(mode_0)
    result.update(mode_1)
    return result



# data = bytearray(b'\x02\xc3\x02\x00\x00\x1e\x02\x00\x00i\x04\x00\x008\x04\x0f')
# data_1 =  bytearray(b'\x02\xc3\x02\x00\x00\x1e\x02\x00\x00i\x04\x00\x008\x04\x0f\xd4\x0e\t\x00\x00d\x9a\xd2y\x06\x00\x00d\x11\xc5-\x08\x00\x00d\x0e\xc6\xed\x08\x00\x00d')
#
# print_result(decode_location_mode_1(data_1[14:]))


async def safe_emit(event, data):
    if sio.connected:
        await sio.emit(event, data)
    else:
        print(f"❌ Không thể gửi '{event}' vì không kết nối với server!")

async def connect_to_server(max_retries=3):
    global sio
    for attempt in range(max_retries):
        try:
            print(f"🌐 Đang kết nối đến server (Thử lần {attempt + 1})...")
            await sio.connect(SERVER_URL)
            print("✅ Đã kết nối với server!")
            return

        except Exception as e:
            print(f"❌ Lỗi kết nối server: {e}")
            await asyncio.sleep(TIMEOUT)

    while True:
        try:
            print(f"🔄 Server vẫn chưa kết nối được, thử lại sau {TIMEOUT} giây...")
            await asyncio.sleep(TIMEOUT)
            await sio.connect(SERVER_URL)
            print("✅ Server đã kết nối lại thành công!")
            return
        except Exception as e:
            print(f"❌ Lỗi kết nối server: {e}")


async def connect_to_server_2(max_retries=3):
    """Kết nối đến server với khả năng tự động thử lại."""
    global sio

    if sio.connected:
        print("✅ Server đã kết nối, không cần thử lại!")
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
    asyncio.create_task(connect_to_server_2())

@sio.on("start_tracking")
async def start_tracking(data=None):
    """Bật tracking từ server."""
    global TRACKING_ENABLE
    tracking_enabled = True
    print("✅ Tracking đã bật!")


@sio.on("stop_tracking")
async def stop_tracking(data=None):
    """Tắt tracking từ server."""
    global TRACKING_ENABLE
    tracking_enabled = False
    print("❌ Tracking đã dừng!")


async def notification_handler(sender, data, address):
    """Xử lý dữ liệu từ BLE notify, kiểm soát tần suất gửi."""
    global TRACKING_ENABLE, LAST_SENT_TIME, INTERVAL
    decoded_data = decode_location_data(data)
    current_time = time.time()

    if tracking_enabled:
        await safe_emit("tag_data", {"mac": address, "data": decoded_data})
        print(f"Tracking = {tracking_enabled}\nTag {address} gửi ngay!\nData: {decoded_data} \n")
    else:
        last_sent = last_sent_time.get(address, 0)
        if current_time - last_sent >= INTERVAL:
            await safe_emit("tag_data", {"mac": address, "data": decoded_data})
            last_sent_time[address] = current_time
            print(
                f"Tracing = {tracking_enabled} - Delay: {INTERVAL}s\nTag [{address}] gửi dữ liệu!\nData: {decoded_data} \n")


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

            print(f"📡 Anchor {address} gửi dữ liệu: {decoded_data}")
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
                await client.start_notify(LOCATION_DATA_UUID,
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


async def main():
    """Chương trình chính."""
    await connect_to_server_2()

    # Tìm các thiết bị BLE
    devices = await BleakScanner.discover(10)
    anchors = [dev.address for dev in devices if dev.address in MAC_ADDRESS_ANCHOR_LIST]
    print(f"Danh sách anchor: {anchors}")

    #
    #
    # Xử lý từng anchor (chỉ chạy một lần)
    for anchor in anchors:
        await process_anchor(anchor)

    # anchor_tasks = [asyncio.create_task(process_anchor(anchor)) for anchor in anchors]
    # await asyncio.gather(*anchor_tasks)

    print("Chờ server lệnh để xử lý Tag...")
    # Khởi chạy task cho từng Tag
    tasks = [asyncio.create_task(process_tag(tag)) for tag in TAG_MAC_LIST]
    await asyncio.gather(*tasks)

    await sio.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print(f"❌ Lỗi runtime: {e}")