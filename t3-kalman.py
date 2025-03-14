import asyncio
import time
import pytz
import socketio
from bleak import BleakClient, BleakScanner, BleakError
from location import decode_location_data
from global_var import *


# for kalman ######################
# from filterpy.kalman import KalmanFilter
import numpy as np
###################################



sio = socketio.AsyncClient()
time_zone = pytz.timezone('Asia/Ho_Chi_Minh')

tracking_enabled = False
last_sent_time = {}  # Lưu thời gian gửi gần nhất của từng tag
INTERVAL = 5
TIMEOUT = 5
DISCONNECTED_TAGS = set()  # Danh sách Tag bị mất kết nối


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


# Khởi tạo bộ lọc Kalman thủ công
kalman_filters = {}

def init_kalman_filter():
    kf = {
        "x": np.array([[0], [0], [0], [0]]),  # Trạng thái [x, vx, y, vy]
        "P": np.eye(4) * 1000,  # Hiệp phương sai
        "F": np.array([[1, 1, 0, 0],
                        [0, 1, 0, 0],
                        [0, 0, 1, 1],
                        [0, 0, 0, 1]]),
        "H": np.array([[1, 0, 0, 0],
                        [0, 0, 1, 0]]),
        "R": np.eye(2) * 5,  # Nhiễu đo lường
        "Q": np.eye(4) * 0.01  # Nhiễu quá trình
    }
    return kf

def kalman_predict(kf):
    kf["x"] = np.dot(kf["F"], kf["x"])
    kf["P"] = np.dot(np.dot(kf["F"], kf["P"]), kf["F"].T) + kf["Q"]

def kalman_update(kf, z):
    y = z - np.dot(kf["H"], kf["x"])
    S = np.dot(np.dot(kf["H"], kf["P"]), kf["H"].T) + kf["R"]
    K = np.dot(np.dot(kf["P"], kf["H"].T), np.linalg.inv(S))
    kf["x"] += np.dot(K, y)
    kf["P"] = np.dot((np.eye(4) - np.dot(K, kf["H"])), kf["P"])

async def notification_handler_kalman(sender, data, address):
    global tracking_enabled, last_sent_time, INTERVAL, kalman_filters
    decoded_data = decode_location_data(data)
    current_time = time.time()

    x, y = decoded_data.get("x", 0), decoded_data.get("y", 0)
    if address not in kalman_filters:
        kalman_filters[address] = init_kalman_filter()
        kalman_filters[address]["x"] = np.array([[x], [0], [y], [0]])

    kf = kalman_filters[address]
    kalman_predict(kf)
    kalman_update(kf, np.array([[x], [y]]))
    smoothed_x, smoothed_y = kf["x"][0, 0], kf["x"][2, 0]

    filtered_data = {"x": smoothed_x, "y": smoothed_y}

    if tracking_enabled:
        await safe_emit("tag_data", {"mac": address, "data": filtered_data})
        print(f"Filtered Data: {filtered_data}")
    else:
        last_sent = last_sent_time.get(address, 0)
        if current_time - last_sent >= INTERVAL:
            await safe_emit("tag_data", {"mac": address, "data": filtered_data})
            last_sent_time[address] = current_time
            print(f"Filtered Data Sent: {filtered_data}")



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
    global tracking_enabled
    tracking_enabled = True
    print("Tracking đã bật!")


@sio.on("stop_tracking")
async def stop_tracking(data=None):
    """Tắt tracking từ server."""
    global tracking_enabled
    tracking_enabled = False
    print("Tracking đã dừng!")


async def notification_handler(sender, data, address):
    """Xử lý dữ liệu từ BLE notify, kiểm soát tần suất gửi."""
    global tracking_enabled, last_sent_time, INTERVAL
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
                # await client.start_notify(LOCATION_DATA_UUID,
                #                           lambda s, d: asyncio.create_task(notification_handler(s, d, address))
                #                           )

                await client.start_notify(LOCATION_DATA_UUID,
                                          lambda s, d: asyncio.create_task(notification_handler_kalman(s, d, address))
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

    # Xử lý từng anchor (chỉ chạy một lần)
    # for anchor in anchors:
    #     await process_anchor(anchor)

    anchor_tasks = [asyncio.create_task(process_anchor(anchor)) for anchor in anchors]
    await asyncio.gather(*anchor_tasks)

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
