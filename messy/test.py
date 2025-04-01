import asyncio
import struct
import socketio
from bleak import BleakClient, BleakScanner, BleakError
from location import decode_location_data
from global_var import *

sio = socketio.AsyncClient()

anchors = []
TRACKING_ENABLE = False  # Biến để kiểm soát việc gửi dữ liệu từ Tag


async def safe_emit(event, data):
    if sio.connected:
        await sio.emit(event, data)
    else:
        print(f"Không thể gửi '{event}' vì không kết nối với server!")


def notification_handler(sender, data, address):
    decoded_data = decode_location_data(data)
    print(f"Nhận dữ liệu từ {address}: {decoded_data}")

    if TRACKING_ENABLE:
        asyncio.create_task(safe_emit("tag_data", {"mac": str(address), "data": decoded_data}))

def _notification_handler(sender, data):
    decoded_data = decode_location_data(data)
    print(f"Nhận dữ liệu từ {sender}: {decoded_data}")

    if TRACKING_ENABLE:
        asyncio.create_task(safe_emit("tag_data", {"mac": str(sender), "data": decoded_data}))
        asyncio.sleep(10)

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


async def process_device(address, is_tag=False, max_retries=3):
    client = BleakClient(address)
    for attempt in range(max_retries):
        try:
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
                        await client.start_notify(LOCATION_DATA_UUID, lambda sender, data: notification_handler(sender, data, address))
                        print(f"Tag {address} đang gửi data...")
                        await asyncio.sleep(2)
                        await client.stop_notify(LOCATION_DATA_UUID)
                    else:
                        data = await client.read_gatt_char(LOCATION_DATA_UUID)
                        decoded_data = decode_location_data(data)
                        print(f"Nhận dữ liệu từ {address}: {decoded_data}")
                        await safe_emit("tag_data", {"mac": address, "data": decoded_data})
                        await asyncio.sleep(5)


                        # await client.start_notify(LOCATION_DATA_UUID, _notification_handler)
                        # print(f"Tag {address} đang gửi data...")
                        # await asyncio.sleep(2)
                        # await client.stop_notify(LOCATION_DATA_UUID)


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

                # await client.start_notify(OPERATION_MODE_UUID,
                #                           lambda slender, data: notification_handler(slender, data, address))
                # await asyncio.sleep(2)
                # await client.stop_notify(OPERATION_MODE_UUID)
                #
                # await client.start_notify(LOCATION_DATA_UUID,
                #                           lambda slender, data: notification_handler(slender, data, address))
                # await asyncio.sleep(2)
                # await client.stop_notify(LOCATION_DATA_UUID)
            break  # Thoát vòng lặp nếu kết nối thành công

        except BleakError as e:
            print(f"Lỗi BLE với {address}: {e}")
        except asyncio.TimeoutError:
            print(f"Timeout khi kết nối với {address}")
        except Exception as e:
            print(f"Lỗi không xác định với {address}: {e}")
        finally:
            await client.disconnect()  # Đảm bảo luôn đóng kết nối BLE khi kết thúc


async def main():
    await connect_to_server()

    devices = await BleakScanner.discover(10)

    for device in devices:
        if device.address in MAC_ADDRESS_ANCHOR_LIST:
            anchors.append(device.address)

    print(f"Danh sách anchor: {anchors}")

    for anchor in anchors:
        await process_device(anchor, is_tag=False)
        # asyncio.create_task(process_device(anchor, is_tag=False))

    print("Chờ lệnh từ server để xử lý Tag...")
    task = []
    for tag in TAG_LIST:
        task.append(process_device(tag, is_tag=True))
    await asyncio.gather(*task)
    # await process_device(TAG_MAC, is_tag=True)
    await sio.disconnect()


if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except RuntimeError as e:
        print(f"Lỗi runtime: {e}")
    finally:
        loop.close()
