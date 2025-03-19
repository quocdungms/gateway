import asyncio
import time
import struct
import pytz
import socketio
from bleak import BleakClient, BleakScanner, BleakError
import json
from config import *
import os

file_module = "modules.json"
sio = socketio.AsyncClient()
time_zone = pytz.timezone('Asia/Ho_Chi_Minh')

TRACKING_ENABLED = False
LAST_SENT_TIME = {}  # Lưu thời gian gửi gần nhất của từng tag
INTERVAL = 5
TIMEOUT = 5
DISCONNECTED_TAGS = set()  # Danh sách Tag bị mất kết nối

location_queue = asyncio.Queue()
command_queue = asyncio.Queue()
file_lock = asyncio.Lock()

MODULE_TYPE = {}
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
                print("✅ Server kết nối thành công!")
                return
            if not await sio.connect(SERVER_URL):
                continue
        except Exception as e:
            print(f"❌ Lỗi kết nối server: {e}")
            print(f"🔄 Server vẫn chưa kết nối được, thử lại sau {TIMEOUT} giây...")
            await asyncio.sleep(TIMEOUT)

def bytes_array_to_bits(byte_array):
    return ''.join(bin(byte)[2:].zfill(8) for byte in byte_array)
def bits_to_bytes_array(bit_string):
    # Đảm bảo chuỗi bit có độ dài là bội số của 8
    bit_string = bit_string.zfill((len(bit_string) + 7) // 8 * 8)

    # Chuyển đổi sang số nguyên
    integer_value = int(bit_string, 2)

    # Chuyển thành mảng byte
    byte_length = len(bit_string) // 8
    return integer_value.to_bytes(byte_length, byteorder='big')


def int_to_bytes_array(value):
    """
    Chuyển số nguyên dương thành 4 byte (little-endian).
    - value: Số nguyên dương (uint32_t)
    - Trả về: bytearray 4 byte
    """
    if not isinstance(value, int) or value < 0 or value > 0xFFFFFFFF:
        raise ValueError("Giá trị phải là số nguyên dương từ 0 đến 4294967295")

    return bytearray([
        value & 0xFF,
        (value >> 8) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 24) & 0xFF
    ])

def float_to_int32_bytes(value):
    """
    Chuyển số thực (mét) thành 4 byte (little-endian, mm).
    - value: Số thực (mét)
    - Trả về: bytearray 4 byte (đơn vị mm)
    """
    # Chuyển mét sang mm (nhân 1000) và làm tròn thành số nguyên
    value_mm = round(value * 1000)

    # Kiểm tra phạm vi int32_t (-2147483648 đến 2147483647 mm)
    if value_mm < -2147483648 or value_mm > 2147483647:
        raise ValueError(f"Giá trị {value}m vượt quá phạm vi cho phép (-2147.483648m đến 2147.483647m)")

    # Chuyển thành 4 byte little-endian
    return bytearray([
        value_mm & 0xFF,
        (value_mm >> 8) & 0xFF,
        (value_mm >> 16) & 0xFF,
        (value_mm >> 24) & 0xFF
    ])
async def write_anchor_location(address, x, y, z, quality_factor):
    """
    Ghi vị trí (X, Y, Z) và quality factor vào anchor của DWM1001 module.
    - x, y, z: Tọa độ (mét), số thực
    - quality_factor: Độ tin cậy (1-100)
    """
    # Kiểm tra quality factor


    # Chuyển X, Y, Z từ mét sang byte (mm)
    x_bytes = float_to_int32_bytes(x)
    y_bytes = float_to_int32_bytes(y)
    z_bytes = float_to_int32_bytes(z)

    # Quality factor là 1 byte
    quality_bytes = bytearray([quality_factor])

    # Ghép thành buffer 13 byte: X (4) + Y (4) + Z (4) + Quality (1)
    data = x_bytes + y_bytes + z_bytes + quality_bytes

    # Mô phỏng dữ liệu hex để kiểm tra
    hex_data = " ".join(f"{byte:02x}" for byte in data)
    print(f"Input: X = {x}m, Y = {y}m, Z = {z}m, Quality = {quality_factor}")
    print(f"Data (hex): {hex_data}")

def load_devices_from_json(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        anchors = [device for device in data if device["type"] == "anchor"]
        tags = [device for device in data if device["type"] == "tag"]
        for device in data:
            MODULE_TYPE[device["id"]] = device["type"]
        return anchors, tags
    except Exception as e:
        print(f"Lỗi khi đọc file JSON: {e}")
        return [], []


def determine_module_type(operation_mode: bin):
    if operation_mode[0] == '0':
        return "tag"
    return "anchor"

async def update_modules_json(mac, new_type, operation_mode):
    async with file_lock:
        temp_filename = "modules.temp"
        try:
            with open(file_module, "r", encoding="utf-8") as file:
                data = json.load(file)
            for device in data:
                if device["id"] == mac:
                    device["type"] = new_type
                    device["operation"] = operation_mode
                    break
            with open(temp_filename, "w", encoding="utf-8") as temp_file:
                json.dump(data, temp_file, indent=4)

                # Đóng file tạm trước khi thay thế
                temp_file.close()
            os.replace(temp_filename, file_module)
            print(f"✅ Đã cập nhật modules.json cho {mac} thành {new_type}")
        except Exception as e:
            print(f"❌ Lỗi khi cập nhật modules.json: {e}")

        finally:
            # Nếu file tạm vẫn còn (trong trường hợp lỗi), hãy xóa nó
            if os.path.exists(temp_filename):
                os.remove(temp_filename)

@sio.on("server_req")
async def server_req(msg):
    cmd = msg.get("command")
    payload = msg.get("payload", {})
    mac_addr = payload.get("mac")
    data = payload.get("data")
    # if all([cmd, mac, data]) is not None:
    #     await command_queue.put((cmd, mac, data))

    if not all([cmd, mac_addr, data]):
        print("Du lieu server_req khong hop le!")

    print(f"⬇️ Nhận server request: {cmd} {mac_addr} {data}")

    if mac_addr not in MODULE_TYPE:
        print(f"Module {mac_addr} không tồn tại!")
        return

    restart_task = True
    if MODULE_STATUS.get(mac_addr) == "processing":
        print(f"⏸️ Dừng task của {mac_addr} để ghi dữ liệu...")
        if mac_addr in TASK_MANAGER and not TASK_MANAGER[mac_addr].done():
            TASK_MANAGER[mac_addr].cancel()
            try:
                await TASK_MANAGER[mac_addr]
            except asyncio.CancelledError:
                print(f"✅ Task của {mac_addr} đã dừng.")

    MODULE_STATUS[mac_addr] = "writing"
    print(f"📝 Ghi dữ liệu vào {mac_addr}: {data}")
    # (Ghi dữ liệu BLE vào module ở đây)
    await asyncio.sleep(1)
    client = BleakClient(mac_addr)
    max_retries = 3
    is_succeed = False
    for attempt in range(max_retries):
        try:
            await client.connect()
            if not client.is_connected:
                raise BleakError(f"Thiết bị {mac_addr} không kết nối được! Thử lại lần {attempt + 1}/3")
            if cmd == "set_operation_mode":
                operation_mode_binary = data
                operation_mode_bytes = bits_to_bytes_array(operation_mode_binary)
                await client.write_gatt_char(OPERATION_MODE_UUID, operation_mode_bytes)
                print(f"✅ Ghi operation mode {mac_addr} thành công")
                new_type = determine_module_type(operation_mode_binary)
                if new_type != MODULE_TYPE[mac_addr]:
                    MODULE_TYPE[mac_addr] = new_type
                    await update_modules_json(mac_addr,new_type,operation_mode_binary)
                # if new_type == "anchor":
                #     restart_task = False

            elif cmd == "set_tag_rate":
                u1_int = data.get("u1")
                u2_int = data.get("u2")
                rate_data_to_write = int_to_bytes_array(u1_int) + int_to_bytes_array(u2_int)
                await client.write_gatt_char(UPDATE_RATE_UUID, rate_data_to_write)
                print(f"✅ Update tag rate {mac_addr} thành công. U1: {u1_int}ms, U2: {u2_int}ms")
            elif cmd == "set_anchor_location":
                ##### Đang lỗi phân biệt tag và anchor, set anchor thì ko restart task
                x_float = data.get("x")
                y_float = data.get("y")
                z_float = data.get("z")
                quality_factor = data.get("quality_factor")
                if not isinstance(quality_factor, int) or quality_factor < 1 or quality_factor > 100:
                    raise ValueError("Quality factor phải là số nguyên từ 1 đến 100")

                x_bytes = float_to_int32_bytes(x_float)
                y_bytes = float_to_int32_bytes(y_float)
                z_bytes = float_to_int32_bytes(z_float)
                quality_factor_bytes = bytearray([quality_factor])

                data_to_write = x_bytes + y_bytes + z_bytes + quality_factor_bytes
                await client.write_gatt_char(PERSISTED_POSITION, data_to_write)
                print(f"✅ Set anchor location {mac_addr} thành công!\n"
                      f"x: {x_float}, y: {y_float}, z: {z_float}, qulity_factor: {quality_factor}")

            is_succeed = True
            await safe_emit("gw_res", {
                "result": "succeed",
                "command": cmd,
                "mac": mac_addr
            })
            await asyncio.sleep(1)
            break  # Nếu kết nối thành công, thoát vòng lặp

        except BleakError as ble:
            print(f"❌ Lỗi BLE với {mac_addr}: {ble}")
        except Exception as e:
            print(f"❌ Lỗi khi ghi dữ liệu vào module {mac_addr}: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()

        if attempt < max_retries:
            print(f"🔄 Thử kết nối lại {mac_addr} sau 3 giây...")
            await asyncio.sleep(3)


    if not is_succeed:
        await safe_emit("gw_res", {
            "result": "error",
            "command": str(cmd),
            "mac": str(mac_addr),
        })

    # if is_stopped_task:
    #     # Cập nhật lại module status
    #
    #     MODULE_STATUS[mac_addr] = 'idle'
    #     # Khởi động lại task cũ
    #     print(f"🔄 Khởi động lại task: {mac_addr}...")
    #     TASK_MANAGER[mac_addr] = asyncio.create_task(process_tag(mac_addr))

    MODULE_STATUS[mac_addr] = 'idle'
    if MODULE_TYPE[mac_addr] == "tag":
        print(f"🔄 Khởi động lại task: {mac_addr}...")
        TASK_MANAGER[mac_addr] = asyncio.create_task(process_tag(mac_addr))
    elif MODULE_TYPE[mac_addr] == "anchor":
        print(f"🔄 Khởi động lại task: {mac_addr}...")
        TASK_MANAGER[mac_addr] = asyncio.create_task(process_anchor(mac_addr))


    # if MODULE_TYPE[mac_addr] == "anchor" and not restart_task:
    #     print(f"Không cần chạy lại task!")
    #     return

    # MODULE_STATUS[mac_addr] = 'idle'
    # # Khởi động lại task cũ
    # print(f"🔄 Khởi động lại task: {mac_addr}...")
    # TASK_MANAGER[mac_addr] = asyncio.create_task(process_tag(mac_addr))



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
        min_quality_factor = 5
        if "Distances count:" not in decoded_data or "Distances" not in decoded_data:
            # print(f"⚠️ Dữ liệu từ {address} không hợp lệ, bỏ qua...")
            return
        distances_count = decoded_data.get("Distances count:",0)
        distances_node = decoded_data.get("Distances", [])
        if distances_count < 3:
            # print(f"⚠️ Dữ liệu từ {address} có số lượng điểm đo quá ít (count={distances_count}), bỏ qua...")
            return
        for d in distances_node:
            if d["Quality Factor"] < min_quality_factor:
                # print(f"⚠️ Dữ liệu từ {address} có chất lượng thấp, bỏ qua...")
                return
        await location_queue.put((address, decoded_data))
        # print(f"📡 Đã nhận notify từ {address}: {decoded_data}")
    except Exception as e:
        print(f"❌ Lỗi trong notification_handler: {e}")


async def send_location_handler():
    global TRACKING_ENABLED, LAST_SENT_TIME, INTERVAL
    while True:  # Luôn chạy để xử lý dữ liệu mới
        address, location = await location_queue.get()  # Chờ dữ liệu mới
        current_time = time.time()
        if address is not None and location is not None:
            try:
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
            except Exception as e:
                print(f"Lỗi ở send_location_handler: {e}!")


async def process_anchor(address):
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
            await asyncio.sleep(0.5)
            operation_mode_data = await client.read_gatt_char(OPERATION_MODE_UUID)
            await asyncio.sleep(0.5)
            decoded_data = decode_location_data(data)
            operation_mode_value = int.from_bytes(operation_mode_data[:2], byteorder="big")
            operation_mode_binary = f"{operation_mode_value:016b}"

            print(f"📡 Anchor {address} gửi dữ liệu: {decoded_data}")
            await safe_emit("anchor_data", {
                "mac": address,
                "data": decoded_data,
                "operation_mode": operation_mode_binary
            })
            await update_modules_json(address, "anchor", operation_mode_binary)
            # Gửi thành công thì kết thúc vòng lặp, không quét lại
            break

        except BleakError as e:
            print(f"❌ Lỗi BLE Anchor {address}: {e}")
            await asyncio.sleep(TIMEOUT)
        except Exception as e:
            print(f"❌ Lỗi không xác định với Anchor {address}: {e}")
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
                    print(f"❌ Không thể kết nối Tag {address}, thử lần {attempt + 1}")
                    await asyncio.sleep(TIMEOUT)
                    continue

                print(f"✅ Kết nối Tag {address} thành công, bắt đầu nhận dữ liệu...")
                DISCONNECTED_TAGS.discard(address)  # Đánh dấu là đã kết nối lại
                # Nhận notify từ Tag
                operation_mode_bytes = await client.read_gatt_char(OPERATION_MODE_UUID)
                operation_mode_binary = bytes_array_to_bits(operation_mode_bytes)
                await client.start_notify(LOCATION_DATA_UUID, lambda s, d: asyncio.create_task(notification_handler(s,d,address)))
                print(f"✅ Đã kích hoạt notify thành công cho Tag {address}!")
                # Đánh dấu task đang hoạt động
                MODULE_STATUS[address] = 'processing'
                # await update_modules_json(address,"tag",operation_mode_binary)
                while client.is_connected:
                    await asyncio.sleep(2)  # Giữ kết nối

            except BleakError as e:
                print(f"❌ Lỗi BLE Tag {address}: {e}")
            except asyncio.TimeoutError:
                print(f"❌ Timeout khi kết nối Tag {address}")
            except Exception as e:
                print(f"❌ Lỗi không xác định với Tag {address}: {e}")
            finally:
                if client.is_connected:
                    await client.disconnect()

        # Nếu thử 3 lần vẫn lỗi thì vào chế độ chờ, quét lại mỗi 5s
        print(f"🔄 Không thể kết nối Tag {address}, thử lại sau {TIMEOUT}s ...")
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


    tags, anchors = load_devices_from_json("modules.json")
    for module in tags + anchors:
        mac_addr = module["id"]
        if module["type"] == "tag":
            TASK_MANAGER[mac_addr] = asyncio.create_task(process_tag(mac_addr))
        elif module["type"] == "anchor":
            TASK_MANAGER[mac_addr] = asyncio.create_task(process_anchor(mac_addr))


    # # Khởi chạy task cho từng Tag
    # for tag in TAG_MAC_LIST:
    #     TASK_MANAGER[tag] = asyncio.create_task(process_tag(tag))
    # await asyncio.gather(*tasks)


    await sio.wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print(f"❌ Lỗi runtime: {e}")
