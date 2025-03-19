import asyncio
import time
import struct
import pytz
import socketio
from bleak import BleakClient, BleakScanner, BleakError

from config import *


sio = socketio.AsyncClient()
time_zone = pytz.timezone('Asia/Ho_Chi_Minh')

TRACKING_ENABLED = False
LAST_SENT_TIME = {}  # Lưu thời gian gửi gần nhất của từng tag
INTERVAL = 5
TIMEOUT = 5
DISCONNECTED_TAGS = set()  # Danh sách Tag bị mất kết nối

queue_location = asyncio.Queue()
command_queue = asyncio.Queue()


MODULE_STATUS = {}
TASK_MANAGER = {}


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
async def safe_emit(event, data):
    if sio.connected:
        await sio.emit(event, data)
        return True
    else:
        print(f"❌ Không thể gửi '{event}' vì không kết nối với server!")
        return False

async def connect_to_server():
    global sio
    while True:
        try:
            if sio.connected:
                print("✅ Server kết nối lại thành công!")
                return
            if not await sio.connect(SERVER_URL):
                continue
        except Exception as e:
            print(f"❌ Lỗi kết nối server: {e}")
            print(f"🔄 Server vẫn chưa kết nối được, thử lại sau {TIMEOUT} giây...")
            await asyncio.sleep(TIMEOUT)
def bits_to_bytes_array(bit_string):
    # Đảm bảo chuỗi bit có độ dài là bội số của 8
    bit_string = bit_string.zfill((len(bit_string) + 7) // 8 * 8)

    # Chuyển đổi sang số nguyên
    integer_value = int(bit_string, 2)

    # Chuyển thành mảng byte
    byte_length = len(bit_string) // 8
    return integer_value.to_bytes(byte_length, byteorder='big')

@sio.on("server_req")
async def server_req(msg):
    cmd = msg.get("command")
    payload = msg.get("payload", {})
    mac = payload.get("mac")
    data = payload.get("data")

    # if all([cmd, mac, data]) is not None:
    #     await command_queue.put((cmd, mac, data))

    if not all([cmd, mac, data]):
        print("Du lieu server_req khong hop le!")

    print(f"⬇️ Nhận server request: {cmd} {mac} {data}")


    if MODULE_STATUS.get(mac) == "processing":
        print(f"⏸️ Dừng task của {mac} để ghi dữ liệu...")
        if mac in TASK_MANAGER and not TASK_MANAGER[mac].done():
            TASK_MANAGER[mac].cancel()
            try:
                await TASK_MANAGER[mac]
            except asyncio.CancelledError:
                print(f"✅ Task của {mac} đã dừng.")

    MODULE_STATUS[mac] = "writing"
    print(f"📝 Ghi dữ liệu vào {mac}: {data}")
    # (Ghi dữ liệu BLE vào module ở đây)
    await asyncio.sleep(1)  # Giả lập thời gian ghi

    client = BleakClient(mac)

    max_retries = 3
    for attempt in range(max_retries):
        try:

            await client.connect()

            if not client.is_connected:
                raise BleakError(f"Thiết bị {mac} không kết nối được! Thử lại lần {attempt + 1}/3")

            if cmd == "set-operation-mode":
                operation_mode = bits_to_bytes_array(data)
                await client.write_gatt_char(OPERATION_MODE_UUID, operation_mode)
                print(f"✅ Ghi operation mode {mac} thành công")
                await asyncio.sleep(1)

            break  # Nếu kết nối thành công, thoát vòng lặp

        except BleakError as ble:
            print(f"❌ Lỗi BLE với {mac}: {ble}")
        except Exception as e:
            print(f"❌ Lỗi khi ghi dữ liệu vào module {mac}: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()

        if attempt < max_retries:
            print(f"🔄 Thử kết nối lại {mac} sau 3 giây...")
            await asyncio.sleep(3)

    MODULE_STATUS[mac] = 'idle'

    # Khởi động lại task cũ
    print(f"🔄 Khởi động lại {mac}...")
    TASK_MANAGER[mac] = asyncio.create_task(process_tag(mac))


@sio.event
async def disconnect():
    print("⚠️ Mất kết nối với server! Đang thử kết nối lại...")
    asyncio.create_task(connect_to_server())

@sio.on("start_tracking")
async def start_tracking(data=None):
    """Bật tracking từ server."""
    global TRACKING_ENABLED
    TRACKING_ENABLED = True
    print("Tracking đã bật!")


@sio.on("stop_tracking")
async def stop_tracking(data=None):
    """Tắt tracking từ server."""
    global TRACKING_ENABLED
    TRACKING_ENABLED = False
    print("Tracking đã dừng!")




async def notification_handler(sender, data, address):
    try:
        decoded_data = decode_location_data(data)
        await queue_location.put((address, decoded_data))
        # print(f"📡 Đã nhận notify từ {address}: {decoded_data}")
    except Exception as e:
        print(f"❌ Lỗi trong notification_handler: {e}")


async def send_location_handler():
    global TRACKING_ENABLED, LAST_SENT_TIME, INTERVAL
    while True:  # Luôn chạy để xử lý dữ liệu mới
        address, location = await queue_location.get()  # Chờ dữ liệu mới
        current_time = time.time()

        if TRACKING_ENABLED:
            if await safe_emit("tag_data", {"mac": address, "data": location}):
                print(f"📡 Tag [{address}] gửi dữ liệu!\nData: {location}")

        else:
            last_sent = LAST_SENT_TIME.get(address, 0)
            if current_time - last_sent >= INTERVAL:
                if await safe_emit("tag_data", {"mac": address, "data": location}):
                    print(f"🕒 Tag [{address}] gửi dữ liệu (INTERVAL={INTERVAL}s)\nData: {location}")
                LAST_SENT_TIME[address] = current_time
        await asyncio.sleep(0.1)


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
                MODULE_STATUS[address] = 'processing'
                await client.start_notify(LOCATION_DATA_UUID, lambda s, d: asyncio.create_task(notification_handler(s,d,address)))
                print(f"✅ Đã kích hoạt notify thành công cho {address}!")
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
    await connect_to_server()
    asyncio.create_task(send_location_handler())
    # # Tìm các thiết bị BLE
    # devices = await BleakScanner.discover(10)
    # anchors = [dev.address for dev in devices if dev.address in MAC_ADDRESS_ANCHOR_LIST]
    # print(f"Danh sách anchor: {anchors}")
    #
    #

    # Xử lý từng anchor (chỉ chạy một lần)
    # for anchor in anchors:
    #     await process_anchor(anchor)
    #
    # anchor_tasks = [asyncio.create_task(process_anchor(anchor)) for anchor in anchors]
    # await asyncio.gather(*anchor_tasks)


    # # Khởi chạy task cho từng Tag
    # for tag in TAG_MAC_LIST:
    #     await asyncio.create_task(process_tag(tag))
    # # await asyncio.gather(*tasks)




    # Khởi chạy task cho từng Tag
    for tag in TAG_MAC_LIST:
        TASK_MANAGER[tag] = asyncio.create_task(process_tag(tag))
    # await asyncio.gather(*tasks)


    await sio.wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print(f"❌ Lỗi runtime: {e}")
