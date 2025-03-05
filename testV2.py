import asyncio
from bleak import BleakScanner, BleakClient
import struct
import socketio
import json

# Server
sio = socketio.AsyncClient()
SERVER_URL = "http://172.16.0.210:5000"

# UUIDs
MAIN_CHARACTERISTIC_UUID = "003bbdf2-c634-4b3d-ab56-7ec889b89a37"
OPERATION_MODE_UUID = "3f0afd88-7770-46b0-b5e7-9fc099598964"
LOCATION_DATA_MODE_UUID = "a02b947e-df97-4516-996a-1882521e0ead"
READ_INTERVAL = 2  # Interval in seconds to read data
SELECTED_DEVICE_ADDRESS = "EB:52:53:F5:D5:90"

async def send_tag_data_to_server(data):
    """Gửi dữ liệu vị trí lên server qua Socket.IO."""
    try:
        await sio.emit("sendTagDataToServer", data)
    except Exception as e:
        print(f"Error sending data: {e}")

def bytearray_to_binary_list(byte_array):
    return [format(byte, '08b') for byte in byte_array]

def parse_position_data(data):
    x, y, z = struct.unpack('<fff', data[1:13])
    quality_factor = data[13]
    return {"position": {"x": format(x, ".2f"), "y": format(y, ".2f")}, "position_quality": quality_factor}

def parse_distance_data(data, offset):
    distances = []
    distance_count = data[offset]
    offset += 1
    for _ in range(distance_count):
        if offset + 7 > len(data):
            break
        node_id = struct.unpack('<H', data[offset:offset + 2])[0]
        distance = struct.unpack('<f', data[offset + 2:offset + 6])[0]
        quality = data[offset + 6]
        distances.append({"node_id": node_id, "distance": f"{distance:.2f} m", "quality": quality})
        offset += 7
    return {"distance_count": distance_count, "distances": distances}

def decode_location_data(data):
    try:
        data_type = data[0]
        if data_type == 2:
            decoded = parse_position_data(data)
            decoded.update(parse_distance_data(data, 14))
        elif data_type == 1:
            decoded = parse_distance_data(data, 1)
        elif data_type == 0:
            decoded = parse_position_data(data)
        else:
            print(f"Unknown or invalid data type: {data_type}")
            return None
        return decoded
    except Exception as e:
        print(f"Error decoding data: {e}")
        return None

async def connect_and_read(device):
    while True:
    try:
        async with BleakClient(device.address) as client:
        if not client.is_connected:
            print(f"Failed to connect to {device.name or 'Unknown'} ({device.address})")
            return
        print(f"Connected to {device.name or 'Unknown'} ({device.address})")
        
        while client.is_connected:
            try:
                await client.write_gatt_char(LOCATION_DATA_MODE_UUID, bytearray(b'\x02'))
                data = await client.read_gatt_char(MAIN_CHARACTERISTIC_UUID)
                location_data = decode_location_data(data)
                if location_data:
                    print(f"Decoded Data: {location_data}")
                    await send_tag_data_to_server(location_data)
                await asyncio.sleep(READ_INTERVAL)
            except Exception as e:
                print(f"Error reading characteristic: {e}")
                break
    except Exception as e:
        print(f"Connection error: {e}")

async def update_operation_mode(mac_address, operation_mode_value):
    """Cập nhật chế độ hoạt động của thiết bị BLE dựa trên chuỗi nhị phân 16-bit."""
    try:
        async with BleakClient(mac_address) as client:
            if not client.is_connected:
                print(f"Failed to connect to {mac_address}")
                return
            print(f"Connected to {mac_address}, updating operation mode...")

            # Chuyển đổi chuỗi nhị phân thành bytearray
            operation_mode_value = operation_mode_value.replace(" ", "")  # Xóa khoảng trắng
            if len(operation_mode_value) != 16:
                print(f"Invalid operation mode format: {operation_mode_value}")
                return
            
            mode_bytes = int(operation_mode_value, 2).to_bytes(2, byteorder="big")
            await client.write_gatt_char(OPERATION_MODE_UUID, mode_bytes)
            print(f"Updated operation mode for {mac_address} to {operation_mode_value}")
    except Exception as e:
        print(f"Error updating operation mode: {e}")

@sio.event
async def updateOperationMode(data):
    """Lắng nghe sự kiện 'updateOperationMode' từ server để cập nhật chế độ hoạt động."""
    try:
        mac_address = data.get("macAddress")
        operation_mode_value = data.get("operationMode")

        if not mac_address or not operation_mode_value:
            print("Invalid data received for operation mode update.")
            return

        print(f"Received operation mode update: {data}")
        await update_operation_mode(mac_address, operation_mode_value)

    except Exception as e:
        print(f"Error processing operation mode update: {e}")

async def main():
    """Kết nối với server & quét thiết bị."""
    try:
        await sio.connect(SERVER_URL)
        print("Connected to server")
    except Exception as e:
        print(f"Failed to connect: {e}")
    
    while True:
        devices = await BleakScanner.discover()
        dw_devices = [d for d in devices if d.name and "DW" in d.name]

        if not dw_devices:
            print("No DWM1001C devices found. Retrying...")
            await asyncio.sleep(5)
            continue

        tasks = []
        for device in dw_devices:
            print(f"Connecting to {device.address}...")
            await sio.emit("register_gateway", {"mac": device.address})
            if device.address == SELECTED_DEVICE_ADDRESS:
                tasks.append(connect_and_read(device))
        if tasks:
            await asyncio.gather(*tasks)
        await asyncio.sleep(100)

if __name__ == "__main__":
    asyncio.run(main())