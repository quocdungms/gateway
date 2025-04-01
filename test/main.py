import time
import pytz
import struct
import json
import asyncio
import socketio
from aiohttp.log import client_logger
from bleak import BleakClient, BleakScanner, BleakError
from config import SERVER_URL, LOCATION_DATA_UUID, OPERATION_MODE_UUID, LOCATION_DATA_MODE_UUID, UPDATE_RATE_UUID


sio = socketio.AsyncClient()
time_zone = pytz.timezone('Asia/Ho_Chi_Minh')
command_queue = asyncio.Queue()



TRACKING_ENABLED = False
LAST_SENT_TIME = {}  # Lưu thời gian gửi gần nhất của từng tag
INTERVAL = 5
TIMEOUT = 5
DISCONNECTED_TAGS = set()  # Danh sách Tag bị mất kết nối

module_tasks = {}
module_types = {}
file_lock = asyncio.Lock()


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

def decode_location_data(data: bytearray):
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


# Hàm load danh sách thiết bị từ file JSON
def load_devices_from_json(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        anchors = [device for device in data if device["type"] == "anchor"]
        tags = [device for device in data if device["type"] == "tag"]
        for device in data:
            module_types[device["id"]] = device["type"]
        return anchors, tags
    except Exception as e:
        print(f"Lỗi khi đọc file JSON: {e}")
        return [], []

def bytes_array_to_binary(data: bytearray):
    bit_string = ""
    for byte in data:
        bits = bin(byte)[2:].zfill(8)
        bit_string += bits + " "
    return bit_string.strip()

def bits_to_bytes_array(bit_string):
    # Đảm bảo chuỗi bit có độ dài là bội số của 8
    bit_string = bit_string.zfill((len(bit_string) + 7) // 8 * 8)

    # Chuyển đổi sang số nguyên
    integer_value = int(bit_string, 2)

    # Chuyển thành mảng byte
    byte_length = len(bit_string) // 8
    return integer_value.to_bytes(byte_length, byteorder='big')


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

async def connect_to_server2(max_retries=3):
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

async def connect_to_server3(max_retries=3):
    global sio
    if sio.connected:  # Kiểm tra nếu đã kết nối
        print("⚡ Server đã kết nối, không cần kết nối lại.")
        return

    for attempt in range(max_retries):
        try:
            print(f"🌐 Đang kết nối đến server (Thử lần {attempt + 1})...")
            await sio.connect(SERVER_URL)
            print("✅ Đã kết nối với server!")
            return
        except Exception as e:
            print(f"❌ Lỗi kết nối server: {e}")
            await asyncio.sleep(TIMEOUT)

    while not sio.connected:  # Chỉ thử lại nếu chưa kết nối
        try:
            print(f"🔄 Server vẫn chưa kết nối được, thử lại sau {TIMEOUT} giây...")
            await asyncio.sleep(TIMEOUT)
            await sio.connect(SERVER_URL)
            print("✅ Server đã kết nối lại thành công!")
        except Exception as e:
            print(f"❌ Lỗi kết nối server: {e}")

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

@sio.on("server_req")
async def server_req(data):
    command = data.get("command")
    payload = data.get("payload", {})
    mac_address = payload.get("mac")
    data = payload.get("data")
    print(f"Nhận request: command {command}, mac {mac_address}, data: {data}")
    if all([command, mac_address,data]) is not None:
        # print(f"Nhận request: command {command}, mac {mac_address}, data: {data}")
        await command_queue.put((command, mac_address, data))

def determine_module_type(operation_mode: bytearray):
    if operation_mode[0] == 0x01:
        return "tag"
    return "anchor"

# def bit_string_to_byte_array(bit_string: str) -> bytearray:
#     while len(bit_string) % 8 != 0:
#         bit_string = "0" + bit_string
#     byte_list = [int(bit_string[i:i+8], 2) for i in range(0, len(bit_string), 8)]
#     return bytearray(byte_list)


async def process_command(command, mac, data, max_retries=3):
    if mac not in module_types:
        print(f"Module {mac} không tồn tại!")
    client = BleakClient(mac)
    for attempt in range(max_retries):
        try:
            # await client.connect()
            if command == "set-operation-mode":
                print("bat dau xy ly set-operation")
                opetation_bytes_array = bits_to_bytes_array(data)
                await client.stop_notify(LOCATION_DATA_UUID)
                await client.write_gatt_char(OPERATION_MODE_UUID, opetation_bytes_array)
                print(f"Set operation mode thanh cong!!!")
                await asyncio.sleep(2)
                operation_mode_data = await client.read_gatt_char(OPERATION_MODE_UUID)
                new_type = determine_module_type(operation_mode_data)
                if new_type != module_types["mac"]:
                    module_types["mac"] = new_type
                    #kiem tra type moi va type cu
                    # Neu chuyen tag thanh anchor va nguoc lai thi dung task dang thuc thi
                    if mac in module_tasks:
                        module_tasks[mac].cancel()

                    if new_type == "tag":
                        module_tasks[mac] = asyncio.create_task(process_tag(mac))
                    elif new_type == "anchor":
                        module_tasks[mac] = asyncio.create_task(process_anchor(mac))
            elif command == "set-location-mode":
                    location_mode = bytearray(data)
                    await client.write_gatt_char(LOCATION_DATA_MODE_UUID, location_mode)
            elif command == "set-anchor-location" and module_types[mac] == "anchor":
                    print("Developing")
            elif command == "set-tag-rate" and module_types[mac] == "tag":
                print("Developing")
                print(f"✅ Thực hiện {command} cho {mac} thành công")
                break
        except BleakError as e:
            print(f"❌ Lỗi BLE khi xử lý {command} cho {mac} (thử lần {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            else:
                print(f"❌ Thất bại sau {max_retries} lần thử với {mac}")
        except Exception as e:
            print(f"❌ Lỗi không xác định khi xử lý {command} cho {mac}: {e}")
            break
        finally:
            if client.is_connected:
                await client.disconnect()

async def update_modules_json(mac, new_type):
    async with file_lock:
        try:
            with open("modules.json", "r", encoding="utf-8") as file:
                data = json.load(file)
            for device in data:
                if device["id"] == mac:
                    device["type"] = new_type
                    break
            with open("modules.json", "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
            print(f"✅ Đã cập nhật modules.json cho {mac} thành {new_type}")
        except Exception as e:
            print(f"❌ Lỗi khi cập nhật modules.json: {e}")

async def command_handler():
    while True:
        command, mac, data = await command_queue.get()
        await process_command(command, mac, data)



# # Hàm tìm thiết bị theo địa chỉ MAC
# def find_device_by_mac(mac_address):
#     for device in devices:
#         if device["id"] == mac_address:
#             return device  # Trả về thông tin thiết bị nếu tìm thấy
#    return None  # Trả về None nếu không tìm thấy


def tag_callback(sender, data, address):
    """Xử lý dữ liệu từ BLE notify, kiểm soát tần suất gửi."""
    global TRACKING_ENABLED, LAST_SENT_TIME, INTERVAL
    decoded_data = decode_location_data(data)
    current_time = time.time()


    if TRACKING_ENABLED:
        safe_emit("tag_data", {"mac": address, "data": decoded_data})
        print(f"Tracking = {TRACKING_ENABLED}\n📨 Tag {address} gửi ngay!\nData: {decoded_data} \n")
    else:
        last_sent = LAST_SENT_TIME.get(address, 0)
        if current_time - last_sent >= INTERVAL:
            safe_emit("tag_data", {"mac": address, "data": decoded_data})
            LAST_SENT_TIME[address] = current_time
            print(
                f"Tracing = {TRACKING_ENABLED} - Delay: {INTERVAL}s\n📨 Tag [{address}] gửi dữ liệu!\nData: {decoded_data} \n")


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
            operation_mode_binary = await client.read_gatt_char(OPERATION_MODE_UUID)

            decoded_data = decode_location_data(data)
            # operation_mode_value = int.from_bytes(operation_mode_data[:2], byteorder="big")
            # operation_mode_binary = f"{operation_mode_value:016b}"
            operation_mode_binary = bytes_array_to_binary(operation_mode_binary)

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
                await client.start_notify(LOCATION_DATA_UUID,
                                          lambda s, d: asyncio.create_task(tag_callback(s, d, address))
                                          )

                # await client.start_notify(LOCATION_DATA_UUID,
                #                           lambda s, d: tag_callback(s, d, address))
                await asyncio.sleep(5)
                await client.stop_notify(LOCATION_DATA_UUID)


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


# async def main():
#     """Chương trình chính."""
#     await connect_to_server()
#
#     # Tìm các thiết bị BLE
#     devices = await BleakScanner.discover(10)
#     # anchors = [dev.address for dev in devices if dev.address in MAC_ADDRESS_ANCHOR_LIST]
#
#     tags, anchors = load_devices_from_json("modules.json")
#
#     print(f"Danh sách anchor: {anchors}")
#     print("Đang xử lý anchor...")
#     for anchor in anchors:
#         await process_anchor(anchor)
#
#     # anchor_tasks = [asyncio.create_task(process_anchor(anchor)) for anchor in anchors]
#     # await asyncio.gather(*anchor_tasks)
#
#     print("Đang xử lý tag...")
#     # tasks = [asyncio.create_task(process_tag(tag)) for tag in TAG_MAC_LIST]
#     tasks = [asyncio.create_task(process_tag(tag)) for tag in tags]
#     await asyncio.gather(*tasks)
#
#     await sio.disconnect()



async def main():
    await connect_to_server()
    tags, anchors = load_devices_from_json("modules.json")
    for device in tags + anchors:
        mac = device["id"]
        if device["type"] == "tag":
            module_tasks[mac] = asyncio.create_task(process_tag(mac))
        # elif device["type"] == "anchor":
        #     module_tasks[mac] = asyncio.create_task(process_anchor(mac))

    await asyncio.create_task(command_handler())
    # await asyncio.gather(asyncio.create_task(command_handler()))
    await sio.wait()
    await sio.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print(f"❌ Lỗi runtime: {e}")