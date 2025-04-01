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

# ICON_SUCCESS = "✅"
# ICON_WARNING = "⚠️"
# ICON_ERROR = "❌"
# ICON_SENDING = "📡"
# ICON_RECONNECT = "🔄"
# ICON_PAUSE = "⏸️"
# ICON_RECEIVE = "📩"
# ICON_WRITE = "📝"
# ICON_SEARCH = "🔍"

ICON_DICT = {
    "SUCCESS": "✅",
    "WARNING": "⚠️",
    "ERROR": "❌",
    "SENDING": "📡",
    "RECONNECT": "🔄",
    "PAUSE": "⏸️",
    "RECEIVE": "📩",
    "WRITE": "📝",
    "SEARCH": "🔍",
    "CLOCK": "🕒"
}


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


async def safe_emit(event, data) -> bool:
    if sio.connected:
        await sio.emit(event, data)
        return True
    else:
        print(f"{ICON_DICT["SUCCESS"]} Không thể gửi '{event}' vì không kết nối với server!")
        return False


async def connect_to_server():
    global sio, TIMEOUT
    while True:
        try:
            if sio.connected:
                print(f"{ICON_DICT["SUCCESS"]} Server kết nối thành công!")
                return
            if not await sio.connect(SERVER_URL):
                continue
        except Exception as e:
            print(f"{ICON_DICT["ERROR"]} Lỗi kết nối server: {e}")
            print(f"{ICON_DICT["RECONNECT"]} Server vẫn chưa kết nối được, thử lại sau {TIMEOUT} giây...")
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


def int_to_bytes_array_4_bytes(value):
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


async def load_devices_from_json(file_path):
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


def determine_module_type(operation_mode: str) -> str:
    if int(operation_mode[0]) == 0:
        return "tag"
    return "anchor"


async def update_modules_json(mac, new_type, operation_mode):
    async with file_lock:
        temp_filename = 'modules.temp'
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
            print(f"{ICON_DICT["SUCCESS"]} Đã cập nhật modules.json cho {mac} thành {new_type}")
        except Exception as e:
            print(f"{ICON_DICT["ERROR"]} Lỗi khi cập nhật modules.json: {e}")

        finally:
            # Nếu file tạm vẫn còn (trong trường hợp lỗi), hãy xóa nó
            if os.path.exists(temp_filename):
                os.remove(temp_filename)


async def ensure_write_status(mac_addr: str) -> bool:
    global MODULE_TYPE, MODULE_STATUS, TASK_MANAGER

    if mac_addr not in MODULE_TYPE:
        print(f"{ICON_DICT["ERROR"]} Module {mac_addr} không tồn tại!")
        return False

    if MODULE_STATUS.get(mac_addr) == "processing":
        print(f"{ICON_DICT["PAUSE"]} Dừng task của {mac_addr} để ghi dữ liệu...")
        if mac_addr in TASK_MANAGER and not TASK_MANAGER[mac_addr].done():
            TASK_MANAGER[mac_addr].cancel()
            try:
                await TASK_MANAGER[mac_addr]
            except asyncio.CancelledError:
                print(f"{ICON_DICT["SUCCESS"]} Task của {mac_addr} đã dừng.")
                return True
    return False


async def prepare_module(cmd: str, mac_addr: str, data: str) -> bool:
    if not all([mac_addr, data]):
        print(f"{ICON_DICT["ERROR"]} Dữ liệu {cmd} không hợp lệ!")
        return False
    if mac_addr not in MODULE_TYPE:
        print(f"{ICON_DICT["ERROR"]} Module {mac_addr} không tồn tại!")
        return False

    print(f"{ICON_DICT["RECEIVE"]} Nhận request: {cmd}, {mac_addr}, {data}!")
    await ensure_write_status(mac_addr)
    MODULE_STATUS[mac_addr] = "writing"
    await asyncio.sleep(0.5)
    return True


async def gateway_res(is_succeed: bool, command: str, mac_addr: str) -> None:
    if is_succeed:
        await safe_emit(command, {
            "mac": mac_addr,
            "result": "success"
        })
    else:
        await safe_emit(command, {
            "mac": mac_addr,
            "result": "error"
        })


async def ble_write_with_retry(mac_addr, char_uuid, data_to_write, max_reties=3, timeout=3):
    client = BleakClient(mac_addr)
    is_succeed = False
    for attempt in range(max_reties):
        try:
            await client.connect()
            if not client.is_connected:
                raise BleakError(f"{ICON_DICT["ERROR"]} Không thể kết nối đến thiết bị: {mac_addr}")
            await client.write_gatt_char(char_uuid, data_to_write)

            is_succeed = True

            print(f"{ICON_DICT["SUCCESS"]}Ghi dữ liệu thành công vào: {mac_addr}")
            break
        except BleakError as ble:
            print(f"{ICON_DICT["ERROR"]} Lỗi BLE với {mac_addr}: {ble}")
        except Exception as e:
            print(f"{ICON_DICT["ERROR"]} Lỗi khi ghi dữ liệu vào {mac_addr}: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()

        if attempt < max_reties - 1:
            print(f"{ICON_DICT["RECONNECT"]} Thử kết nối lại lần {attempt + 1} với {mac_addr} sau {timeout}s...")

    return is_succeed


@sio.on("set_anchor_location")
async def set_anchor_location(msg):
    cmd = "set_anchor_location"
    mac_addr = msg.get("mac")
    data = msg.get('data', {})

    if not await prepare_module(cmd, mac_addr, data):
        return
    try:
        x_float = data.get("x")
        y_float = data.get("y")
        z_float = data.get("z")
        quality_factor = data.get("quality_factor")
        if not isinstance(quality_factor, int) or quality_factor < 1 or quality_factor > 100:
            raise ValueError(f"{ICON_DICT["ERROR"]} Quality factor phải là số nguyên từ 1 đến 100")

        x_bytes = float_to_int32_bytes(x_float)
        y_bytes = float_to_int32_bytes(y_float)
        z_bytes = float_to_int32_bytes(z_float)
        quality_factor_bytes = bytearray([quality_factor])
        data_to_write = x_bytes + y_bytes + z_bytes + quality_factor_bytes

        is_succeed = await ble_write_with_retry(mac_addr, PERSISTED_POSITION, data_to_write)
        if is_succeed:
            print(
                f"{ICON_DICT["SUCCESS"]} {cmd} {mac_addr} thành công: x={x_float}, y={y_float}, z={z_float}, quality={quality_factor}")
    except Exception as e:
        print(f"{ICON_DICT["ERROR"]} Lỗi ghi dữ liệu {cmd},  {mac_addr}: {e}")
        is_succeed = False

    MODULE_STATUS[mac_addr] = "idle"
    await gateway_res(is_succeed, cmd, mac_addr)


@sio.on("set_tag_rate")
async def set_tag_rate(msg):
    cmd = "set_tag_rate"
    mac_addr = msg.get("mac")
    data = msg.get("data", {})

    if not await prepare_module(cmd, mac_addr, data):
        return
    try:
        u1_int = data.get("u1")
        u2_int = data.get("u2")
        u1_byte = int_to_bytes_array_4_bytes(u1_int)
        u2_byte = int_to_bytes_array_4_bytes(u2_int)

        data_to_rite = u1_byte + u2_byte

        is_succeed = await ble_write_with_retry(mac_addr, UPDATE_RATE_UUID, data_to_rite)
        if is_succeed:
            print(f"{ICON_DICT["SUCCESS"]} {cmd} {mac_addr} thành công: u1 = {u1_int}, u2 = {u2_int}!")

    except Exception as e:
        is_succeed = False
        print(f"{ICON_DICT["ERROR"]} Lỗi ghi dữ liệu {cmd}, {mac_addr}: {e}")

    MODULE_STATUS[mac_addr] = "idle"

    TASK_MANAGER[mac_addr] = asyncio.create_task(process_tag(mac_addr))

    await gateway_res(is_succeed, cmd, mac_addr)


@sio.on("set_location_mode")
async def set_location_mode(msg):
    cmd = "set_location_mode"
    mac_addr = msg.get("mac")
    data = msg.get("data", {})

    if not await prepare_module(cmd, mac_addr, data):
        return
    try:
        location_mode_int = data.get("mode")
        data_to_write = location_mode_int.to_bytes(1, byteorder='big')
        is_succeed = await ble_write_with_retry(mac_addr, LOCATION_DATA_MODE_UUID, data_to_write)
        if is_succeed:
            print(f"{ICON_DICT["SUCCESS"]} {cmd} {mac_addr} thành công: location mode = {location_mode_int}!")
    except Exception as e:
        is_succeed = False
        print(f"{ICON_DICT["ERROR"]} Lỗi ghi dữ liệu {cmd}, {mac_addr}: {e}")

    MODULE_STATUS[mac_addr] = "idle"
    if MODULE_TYPE[mac_addr] == "tag":
        TASK_MANAGER[mac_addr] = asyncio.create_task(process_tag(mac_addr))
    await gateway_res(is_succeed, cmd, mac_addr)


@sio.on("set_operation_mode")
async def set_operation_mode(msg):
    cmd = "set_operation_mode"
    mac_addr = msg.get("mac")
    data = msg.get("data", {})

    if not await prepare_module(cmd, mac_addr, data):
        return

    try:
        operation_mode_binary = data
        old_type = MODULE_TYPE.get(mac_addr)
        new_type = determine_module_type(operation_mode_binary)
        data_to_write = bits_to_bytes_array(operation_mode_binary)
        is_succeed = await ble_write_with_retry(mac_addr, OPERATION_MODE_UUID, data_to_write)

        if is_succeed:
            print(f"{ICON_DICT["SUCCESS"]} {cmd} {mac_addr} thành công: {operation_mode_binary}")

        # --------------- Developing---------------
        if old_type != new_type:
            MODULE_TYPE[mac_addr] = new_type
            await update_modules_json(mac_addr, new_type, operation_mode_binary)
        # ----------------------------------------
    except Exception as e:
        is_succeed = False
        print(f"{ICON_DICT["ERROR"]} Lỗi ghi dữ liệu {cmd}, {mac_addr}: {e}")

    MODULE_STATUS[mac_addr] = "idle"
    if MODULE_TYPE[mac_addr] == "tag":
        print(f"{ICON_DICT["RECONNECT"]} Khởi động lại task cho tag: {mac_addr}")
        TASK_MANAGER[mac_addr] = asyncio.create_task(process_tag(mac_addr))
    await gateway_res(is_succeed, cmd, mac_addr)


@sio.event
async def disconnect():
    print(f"{ICON_DICT["WARNING"]} Mất kết nối với server! Đang thử kết nối lại...")
    asyncio.create_task(connect_to_server())


@sio.on("start_tracking")
async def start_tracking(data=None):
    """Bật tracking từ server."""
    global TRACKING_ENABLED
    TRACKING_ENABLED = True
    print(f"{ICON_DICT["SUCCESS"]} Tracking đã bật!")


@sio.on("stop_tracking")
async def stop_tracking(data=None):
    """Tắt tracking từ server."""
    global TRACKING_ENABLED
    TRACKING_ENABLED = False
    print(f"{ICON_DICT["PAUSE"]} Tracking đã dừng!")


async def notification_handler(sender, data, mac_addr):
    try:
        decoded_data = decode_location_data(data)
        min_quality_factor = 5
        if "Distances count:" not in decoded_data or "Distances" not in decoded_data:
            # print(f"{ICON_DICT["WARNING"]} Dữ liệu từ {mac_addr} không hợp lệ, bỏ qua...")
            return
        distances_count = decoded_data.get("Distances count:", 0)
        distances_node = decoded_data.get("Distances", [])
        if distances_count < 3:
            # print(
            #     f"{ICON_DICT["WARNING"]} Dữ liệu từ {mac_addr} có số lượng điểm đo quá ít (count={distances_count}), bỏ qua...")
            return
        for d in distances_node:
            if d["Quality Factor"] < min_quality_factor:
                # print(f"{ICON_DICT["WARNING"]} Dữ liệu từ {mac_addr} có chất lượng thấp, bỏ qua...")
                return
        # current_time = time.time()
        await location_queue.put((mac_addr, decoded_data))
        # print(f"{ICON_DICT["RECEIVE"]} Đã nhận notify từ {mac_addr}: {decoded_data}")
    except Exception as e:
        print(f"{ICON_DICT["ERROR"]} Lỗi trong notification_handler: {e}")


async def send_location_handler():
    global TRACKING_ENABLED, LAST_SENT_TIME, INTERVAL
    while True:  # Luôn chạy để xử lý dữ liệu mới
        address, location, old_time = await location_queue.get()  # Chờ dữ liệu mới

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
                            print(f"📡 Tag [{address}] gửi dữ liệu ({ICON_DICT["CLOCK"]}={INTERVAL}s)\nData: {location}")
                        LAST_SENT_TIME[address] = current_time
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Lỗi ở send_location_handler: {e}!")


async def process_anchor(address):
    client = BleakClient(address)
    while True:
        try:
            print(f"{ICON_DICT["SEARCH"]} Đang kết nối Anchor {address}...")
            await client.connect()
            if not client.is_connected:
                print(f"{ICON_DICT["ERROR"]} Không thể kết nối Anchor {address}, thử lại sau {TIMEOUT} giây...")
                await asyncio.sleep(TIMEOUT)
                continue

            print(f"{ICON_DICT["SUCCESS"]} Đã kết nối Anchor {address}, đọc dữ liệu...")
            data = await client.read_gatt_char(LOCATION_DATA_UUID)
            await asyncio.sleep(0.5)
            operation_mode_data = await client.read_gatt_char(OPERATION_MODE_UUID)
            await asyncio.sleep(0.5)
            decoded_data = decode_location_data(data)
            operation_mode_value = int.from_bytes(operation_mode_data[:2], byteorder="big")
            operation_mode_binary = f"{operation_mode_value:016b}"

            print(f"{ICON_DICT["SENDING"]} Anchor {address} gửi dữ liệu: {decoded_data}")
            await safe_emit("anchor_data", {
                "mac": address,
                "data": decoded_data,
                "operation_mode": operation_mode_binary
            })
            # await update_modules_json(address, "anchor", operation_mode_binary)
            # Gửi thành công thì kết thúc vòng lặp, không quét lại
            print(f"✅ Hoàn thành xử lý Anchor {address}, không quét lại!")
            break

        except BleakError as e:
            print(f"{ICON_DICT["ERROR"]} Lỗi BLE Anchor {address}: {e}")
            await asyncio.sleep(TIMEOUT)
        except asyncio.TimeoutError:
            print(f"{ICON_DICT["ERROR"]} Timeout khi kết nối Anchor {address}")
        except Exception as e:
            print(f"{ICON_DICT["ERROR"]} Lỗi không xác định với Anchor {address}: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()


async def process_tag(address, max_retries=3):
    """Xử lý kết nối với Tag và tự động kết nối lại khi mất kết nối."""
    global DISCONNECTED_TAGS
    while True:
        client = BleakClient(address)
        for attempt in range(max_retries):
            try:
                await client.connect()
                if not client.is_connected:
                    print(f"{ICON_DICT["ERROR"]} Không thể kết nối Tag {address}, thử lần {attempt + 1}")
                    await asyncio.sleep(TIMEOUT)
                    continue

                print(f"✅ Kết nối Tag {address} thành công, bắt đầu nhận dữ liệu...")
                DISCONNECTED_TAGS.discard(address)  # Đánh dấu là đã kết nối lại
                # Nhận notify từ Tag
                operation_mode_bytes = await client.read_gatt_char(OPERATION_MODE_UUID)
                # operation_mode_binary = bytes_array_to_bits(operation_mode_bytes)
                await client.start_notify(LOCATION_DATA_UUID,
                                          lambda s, d: asyncio.create_task(notification_handler(s, d, address)))
                print(f"✅ Đã kích hoạt notify thành công cho Tag {address}!")
                # Đánh dấu task đang hoạt động
                MODULE_STATUS[address] = 'processing'
                # await update_modules_json(address,"tag",operation_mode_binary)
                while client.is_connected:
                    await asyncio.sleep(2)  # Giữ kết nối

            except BleakError as e:
                print(f"{ICON_DICT["ERROR"]} Lỗi BLE Tag {address}: {e}")
            except asyncio.TimeoutError:
                print(f"{ICON_DICT["ERROR"]} Timeout khi kết nối Tag {address}")
            except Exception as e:
                print(f"{ICON_DICT["ERROR"]} Lỗi không xác định với Tag {address}: {e}")
            finally:
                if client.is_connected:
                    await client.disconnect()

        # Nếu thử 3 lần vẫn lỗi thì vào chế độ chờ, quét lại mỗi 5s
        print(f"🔄 Không thể kết nối Tag {address}, thử lại sau {TIMEOUT}s ...")
        DISCONNECTED_TAGS.add(address)
        await asyncio.sleep(TIMEOUT)

async def scan_devices():
    scan_time = 10
    filtered_devices = []

    print(f"{ICON_DICT["SEARCH"]} Đang quét thiết bị Bluetooth...")
    devices = await BleakScanner.discover(scan_time)
    for device in devices:
        if device.name and device.name.lower().startswith(('dwc', 'dwd')):
            filtered_devices.append(device)
    for f_dv in filtered_devices:
        print(f"Thiết bị: {f_dv.name}, MAC: {f_dv.address}")

    return filtered_devices


async def main():


    # """Chương trình chính."""
    # await connect_to_server()
    # asyncio.create_task(send_location_handler())

    scan_dv = await asyncio.create_task(scan_devices())
    tag, anchor = await load_devices_from_json('modules.json')





    # for module in tags + anchors:
    #     mac_addr = module["id"]
    #     if module["type"] == "tag":
    #         TASK_MANAGER[mac_addr] = asyncio.create_task(process_tag(mac_addr))
    #     # elif module["type"] == "anchor":
    #     #     TASK_MANAGER[mac_addr] = asyncio.create_task(process_anchor(mac_addr))

    # await sio.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print(f"{ICON_DICT["ERROR"]} Lỗi runtime: {e}")
    except KeyboardInterrupt:
        print(f"\n{ICON_DICT["PAUSE"]}Chương trình đã dừng bởi người dùng.")
