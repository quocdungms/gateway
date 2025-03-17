import asyncio
import struct
from time import sleep
import time
import pytz
import socketio
from bleak import BleakClient, BleakScanner, BleakError
from location import decode_location_data
# from global_var import TAG_MAC, SERVER_URL, LOCATION_DATA_UUID, LOCATION_DATA_MODE_UUID, MAC_ADDRESS_ANCHOR_LIST, \
#     OPERATION_MODE_UUID
from global_var import *
from datetime import datetime
sio = socketio.AsyncClient()

time_zone = pytz.timezone('Asia/Ho_Chi_Minh')
anchors = []
TRACKING_ENABLE = False  # Biến để kiểm soát việc gửi dữ liệu từ Tag


async def safe_emit(event, data):
    if sio.connected:
        await sio.emit(event, data)
    else:
        print(f"Không thể gửi '{event}' vì không kết nối với server!")


async def connect_to_server():
    try:
        await sio.connect(SERVER_URL)
        print("Đã kết nối với server")
    except Exception as e:
        print(f"Lỗi kết nối server: {e}")


@sio.on("start_tracking")
async def start_tracking(data=None):
    global TRACKING_ENABLE
    tracking_enabled = True
    print("Tracking đã được bật!")


@sio.on("stop_tracking")
async def stop_tracking(data=None):
    global TRACKING_ENABLE
    tracking_enabled = False
    print("Tracking đã dừng!")


@sio.on("updateOperationMode")
async def update_operation_mode(data):
    mac_address = data.get("macAddress")
    operation_mode = data.get("operationMode")

    if not mac_address or not operation_mode:
        print("Dữ liệu updateOperationMode không hợp lệ!")
        return

    try:
        # Chuyển chuỗi nhị phân thành bytes
        if all(c in "01" for c in operation_mode):  # Kiểm tra nếu là chuỗi nhị phân
            operation_mode_bytes = int(operation_mode, 2).to_bytes(len(operation_mode) // 8, byteorder="big")
        else:  # Nếu là số thập phân dưới dạng chuỗi, chuyển sang int trước
            operation_mode_bytes = int(operation_mode).to_bytes(2, byteorder="big")

        print(f"Operation Mode (bytes): {operation_mode_bytes.hex()}")

        async with BleakClient(mac_address) as client:
            if not await client.is_connected():
                print(f"Không thể kết nối tới {mac_address}")
                return

            print(f"Đã kết nối tới {mac_address}, cập nhật operation mode...")

            await client.write_gatt_char(OPERATION_MODE_UUID, operation_mode_bytes)
            print(f"Đã cập nhật operation mode cho {mac_address}: {operation_mode}")

    except ValueError as e:
        print(f"Lỗi chuyển đổi operation_mode: {e}")
    except BleakError as e:
        print(f"Lỗi BLE với {mac_address}: {e}")
    except asyncio.TimeoutError:
        print(f"Timeout khi kết nối với {mac_address}")
    except Exception as e:
        print(f"Lỗi không xác định với {mac_address}: {e}")


def notification_handler(sender, data, address):
    # global current_time
    decoded_data = decode_location_data(data)
    # print(f"Nhận dữ liệu từ {address}: {decoded_data}")

    if TRACKING_ENABLE:
        asyncio.create_task(safe_emit("tag_data", {"mac": str(address), "data": decoded_data}))
        current_time = datetime.now(time_zone).strftime("%Y-%m-%d %H:%M:%S")
        print(f"Tag: {str(address)} gửi dữ liệu. Time: {str(current_time)} \n data: {decoded_data}\n")



last_sent_time = {}  # Lưu thời gian gửi cuối cùng của từng tag
cached_data = {}  # Lưu dữ liệu gần nhất của từng tag

async def notification_handler_test(sender, data, address):
    global last_sent_time, cached_data
    decoded_data = decode_location_data(data)

    current_time = time.time()  # Lấy thời gian hiện tại
    last_time = last_sent_time.get(address, 0)  # Lấy lần gửi gần nhất của tag này

    if TRACKING_ENABLE:
        # Nếu tracking_enabled == True, gửi ngay lập tức
        await safe_emit("tag_data", {"mac": address, "data": decoded_data})
        print(f"Tag {address} gửi dữ liệu ngay lập tức: {decoded_data}")
    else:
        # Lưu dữ liệu vào cache
        cached_data[address] = decoded_data

        # Nếu đã qua 5 giây thì mới gửi dữ liệu
        if current_time - last_time >= 5:
            await safe_emit("tag_data", {"mac": address, "data": cached_data[address]})
            last_sent_time[address] = current_time
            print(f"Tag {address} gửi dữ liệu sau 5 giây: {decoded_data}")



async def process_device(address, is_tag=False, max_retries=3):
    client = BleakClient(address)
    for attempt in range(max_retries):
        try:
            if await client.is_connected():
                print(f"Đã kết nối với {address}, bỏ qua kết nối lại.")
            else:
                await client.connect()

            if not await client.is_connected():
                print(f"Không thể kết nối tới {address}, thử lại lần {attempt + 1}")
                await asyncio.sleep(2)
                continue  # Thử lại nếu không kết nối được

            print(f"Đã kết nối tới {address}")

            # loc_mode_data = await client.read_gatt_char(LOCATION_DATA_MODE_UUID)
            # loc_mode = int(loc_mode_data[0])
            # print(f"Location Data Mode ({address}): {loc_mode}")

            if is_tag:
                print(f"Chờ lệnh từ server để bắt đầu gửi dữ liệu từ tag {address}...")
                while True:
                    if TRACKING_ENABLE:
                        await client.start_notify(LOCATION_DATA_UUID,
                                                  lambda sender, data: notification_handler_test(sender, data, address))
                        print(f"Tag {address} đang gửi data... Tracking = true")
                        await asyncio.sleep(2)
                        await client.stop_notify(LOCATION_DATA_UUID)
                    else:
                        # data = await client.read_gatt_char(LOCATION_DATA_UUID)
                        # decoded_data = decode_location_data(data)
                        # await safe_emit("tag_data", {"mac": address, "data": decoded_data})
                        # current_time = datetime.now(time_zone).strftime("%Y-%m-%d %H:%M:%S")
                        # print(f"Tag: {str(address)} gửi dữ liệu. Time: {str(current_time)} \n data: {decoded_data} \n")
                        # await asyncio.sleep(5)

                        await client.start_notify(LOCATION_DATA_UUID, lambda sender, data: notification_handler_test(sender, data,address))
                        print(f"Tag {address} đang gửi data... Tracking = False")
                        await asyncio.sleep(2)
                        await client.stop_notify(LOCATION_DATA_UUID)

            else:
                data = await client.read_gatt_char(LOCATION_DATA_UUID)
                operation_mode_data = await client.read_gatt_char(OPERATION_MODE_UUID)
                decoded_data = decode_location_data(data)
                operation_mode_value = int.from_bytes(operation_mode_data[:2], byteorder="big")
                operation_mode_binary = f"{operation_mode_value:016b}"
                print(f"Operation Mode (Binary 16-bit): {operation_mode_binary}")
                print(f"Anchor {address} gửi dữ liệu: {decoded_data}")
                await safe_emit("anchor_data",
                                {"mac": address, "data": decoded_data, "operation_mode_data": operation_mode_binary})
            break  # Thoát vòng lặp nếu kết nối thành công

        except BleakError as e:
            if "org.bluez.Error.InProgress" in str(e):
                print(f"Lỗi BLE với {address}: Operation already in progress, chờ 5 giây rồi thử lại...")
                await asyncio.sleep(2)  # Đợi rồi thử lại
                continue
            print(f"Lỗi BLE với {address}: {e}")
        except asyncio.TimeoutError:
            print(f"Timeout khi kết nối với {address}")
        except Exception as e:
            print(f"Lỗi không xác định với {address}: {e}")
        finally:
            if await client.is_connected():
                await client.disconnect()  # Đảm bảo đóng kết nối


async def main():
    await connect_to_server()

    devices = await BleakScanner.discover(10)

    for device in devices:
        if device.address in MAC_ADDRESS_ANCHOR_LIST:
            anchors.append(device.address)

    print(f"Danh sách anchor: {anchors}")
    #
    # for anchor in anchors:
    #     await process_device(anchor, is_tag=False)
    #     # asyncio.create_task(process_device(anchor, is_tag=False))

    print("Chờ lệnh từ server để xử lý Tag...")
    # asyncio.create_task(process_device(TAG_MAC, is_tag=True))
    # await process_device(TAG_MAC, is_tag=True)

    # for tag in TAG_MAC_LIST:
    #     asyncio.create_task(process_device(tag, is_tag=True))
    #     await asyncio.sleep(5)

    tasks = [asyncio.create_task(process_device(tag, is_tag=True)) for tag in TAG_MAC_LIST]
    await asyncio.gather(*tasks)
    await sio.disconnect()


if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except RuntimeError as e:
        print(f"Lỗi runtime: {e}")
    finally:
        loop.close()
