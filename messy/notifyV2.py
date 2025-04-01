import asyncio
import struct
import socketio
from bleak import BleakClient, BleakScanner, BleakError
from location import decode_location_data
from global_var import TAG_MAC, SERVER_URL, LOCATION_DATA_UUID, LOCATION_DATA_MODE_UUID, MAC_ADDRESS_ANCHOR_LIST

# Khởi tạo socketio client
sio = socketio.AsyncClient()

# Danh sách anchor
anchors = []


async def safe_emit(event, data):
    if sio.connected:
        await sio.emit(event, data)
    else:
        print(f"Không thể gửi '{event}' vì không kết nối với server!")


def notification_handler(sender, data):
    decoded_data = decode_location_data(data)
    print(f"Nhận dữ liệu từ {sender}: {decoded_data}")
    asyncio.create_task(safe_emit("tag_data", {"mac": str(sender), "data": decoded_data}))


async def connect_to_server():
    try:
        await sio.connect(SERVER_URL)
        print("Đã kết nối với server")
    except Exception as e:
        print(f"Lỗi kết nối server: {e}")


async def process_device(address, is_tag=False):
    try:
        async with BleakClient(address) as client:
            if not await client.is_connected():
                print(f"Không thể kết nối tới {address}")
                return
            print(f"Đã kết nối tới {address}")

            loc_mode_data = await client.read_gatt_char(LOCATION_DATA_MODE_UUID)
            loc_mode = int(loc_mode_data[0])
            print(f"Location Data Mode ({address}): {loc_mode}")

            if is_tag:
                await client.start_notify(LOCATION_DATA_UUID, notification_handler)
                print(f"Tag {address} đang gửi data...")
                await asyncio.sleep(6000)
                await client.stop_notify(LOCATION_DATA_UUID)
            else:
                data = await client.read_gatt_char(LOCATION_DATA_UUID)
                decoded_data = decode_location_data(data)
                print(f"Anchor {address} gửi dữ liệu: {decoded_data}")
                await sio.emit("anchor_data", {"mac": str(address), "data": decoded_data})
    except BleakError as e:
        print(f"Lỗi BLE với {address}: {e}")
    except asyncio.TimeoutError:
        print(f"Timeout khi kết nối với {address}")
    except Exception as e:
        print(f"Lỗi không xác định với {address}: {e}")


async def main():
    await connect_to_server()

    devices = await BleakScanner.discover(10)

    for device in devices:
        if device.address in MAC_ADDRESS_ANCHOR_LIST:
            anchors.append(device.address)

    print(f"Danh sách anchor: {anchors}")

    for anchor in anchors:
        await process_device(anchor, is_tag=False)

    print("Bắt đầu xử lý Tag...")
    await process_device(TAG_MAC, is_tag=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        print("Lỗi: Event loop đã đóng hoặc không thể khởi chạy lại")
