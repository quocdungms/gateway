import asyncio
import struct
import socketio
import json
import logging
from bleak import BleakScanner, BleakClient


logging.basicConfig(level=logging.ERROR)
# Cấu hình Socket.IO client
sio = socketio.AsyncClient()
SERVER_URL = "http://21.64.9.144:5000"
CHARACTERISTIC_UUID = "003bbdf2-c634-4b3d-ab56-7ec889b89a37"  # UUID

async def send_data_to_server(data):
    """Gửi dữ liệu vị trí lên server qua Socket.IO."""
    try:
        await sio.emit("position_data", {"type": "position", "data": data})
    except Exception as e:
        print(f"Error sending data: {e}")

def decode_raw_data(data):
    """Giải mã dữ liệu từ DWM1001C."""
    try:
        decoded = {}
        data_type = data[0]
        decoded["type"] = data_type

        if data_type == 2:
            x, y, z = struct.unpack('<fff', data[1:13])
            quality_factor = data[13]
            distance_count = data[14]

            decoded["position"] = {"x": x, "y": y, "z": z}
            decoded["position_quality"] = quality_factor
            decoded["distance_count"] = distance_count

            distances = []
            offset = 15
            for _ in range(distance_count):
                if offset + 7 > len(data):
                    break
                node_id, distance = struct.unpack('<Hf', data[offset:offset + 6])
                quality = data[offset + 6]
                distances.append({"node_id": node_id, "distance": distance, "quality": quality})
                offset += 7
            decoded["distances"] = distances

        return decoded
    except Exception as e:
        print(f"Error decoding data: {e}")
        return None

async def write_characteristic_data(client, data):
    """Ghi dữ liệu vào thiết bị BLE."""
    try:
        await client.write_gatt_char(CHARACTERISTIC_UUID, data, response=True)
        print("Data written successfully")
    except Exception as e:
        print(f"Failed to write data: {e}")

async def read_and_send_data(client):
    """Đọc dữ liệu BLE & gửi lên server."""
    while True:
        try:
            data = await client.read_gatt_char(CHARACTERISTIC_UUID)
            # decoded_data = decode_raw_data(data)
            # if decoded_data:
            #     print(f"Decoded Data: {decoded_data}")
            #     await send_data_to_server(decoded_data)
            if data:
                print(f"Data raw: {data}")
                await send_data_to_server(data)
        except Exception as e:
            print(f"Read failed: {e}")
        await asyncio.sleep(1)

async def process_device(device):
    """Kết nối & xử lý dữ liệu từ DWM1001C."""
    try:
        async with BleakClient(device.address) as client:
            if not client.is_connected:
                print(f"Failed to connect: {device.address}")
                return
            print(f"Connected to {device.address}")

            # Đọc & gửi dữ liệu BLE
            asyncio.create_task(read_and_send_data(client))

            # Đăng ký thiết bị với server
            await sio.emit("register_gateway", {"mac": device.address})

            @sio.on("write_data")
            async def on_write_data(data):
                """Nhận lệnh từ server và ghi vào device BLE."""
                if data["mac"] == device.address:
                    print(f"Writing data to {device.address}: {data['characteristic_data']}")
                    # await write_characteristic_data(client, bytes.fromhex(data["characteristic_data"]))

            while True:
                await asyncio.sleep(10)
    except Exception as e:
        print(f"Connection error: {e}")

async def scan_and_connect():
    """Quét & kết nối với các thiết bị DWM1001C."""
    while True:
        print("Scanning for DWM1001C devices...")
        devices = await BleakScanner.discover()
        dw_devices = [d for d in devices if d.name and "DW" in d.name] # Edit name to Tag name

        if not dw_devices:
            print("No DWM1001C devices found. Retrying...")
            await asyncio.sleep(5)
            continue

        for device in dw_devices:
            print(f"Connecting to {device.address}...")
            asyncio.create_task(process_device(device))
        
        await asyncio.sleep(10)

async def main():
    """Kết nối với server & bắt đầu quét thiết bị."""
    try:
        await sio.connect(SERVER_URL)
        print("Connected to server")
    except Exception as e:
        print(f"Failed to connect: {e}")
    await scan_and_connect()

if __name__ == "__main__":
    asyncio.run(main())