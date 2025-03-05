import asyncio
import struct
import websockets
from bleak import BleakScanner, BleakClient

SERVER_WS_URL = "ws://10.20.1.146:5000/api/test"  # Địa chỉ server WebSocket
CHARACTERISTIC_UUID = "003bbdf2-c634-4b3d-ab56-7ec889b89a37"

async def send_data_to_server(data):
    """Gửi dữ liệu đến server WebSocket."""
    try:
        async with websockets.connect(SERVER_WS_URL) as websocket:
            await websocket.send(data)
            response = await websocket.recv()
            print(f"Server response: {response}")
    except Exception as e:
        print(f"Failed to send data to server: {e}")

def decode_raw_data(data):
    """Giải mã dữ liệu BLE từ DWM1001C."""
    try:
        decoded = {}
        data_type = data[0]
        decoded["type"] = data_type

        if data_type == 2:  # Loại dữ liệu vị trí và khoảng cách
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

async def read_characteristic_data(client):
    """Đọc dữ liệu từ DWM1001C và gửi đến server."""
    while True:
        try:
            data = await client.read_gatt_char(CHARACTERISTIC_UUID)
            decoded_data = decode_raw_data(data)
            if decoded_data:
                print(f"Decoded Data: {decoded_data}")
                await send_data_to_server(str(decoded_data))  # Gửi dữ liệu qua WebSocket
        except Exception as e:
            print(f"Read failed: {e}")
        await asyncio.sleep(1)  # Đọc dữ liệu mỗi giây

async def process_device(device):
    """Kết nối với thiết bị BLE và liên tục đọc dữ liệu."""
    while True:
        try:
            async with BleakClient(device.address) as client:
                if not client.is_connected:
                    print(f"Failed to connect: {device.address}")
                    await asyncio.sleep(2)
                    continue
                print(f"Connected to {device.address}")
                await read_characteristic_data(client)
        except Exception as e:
            print(f"Connection error: {e}")
        await asyncio.sleep(2)  # Chờ trước khi thử lại

async def scan_and_connect():
    """Liên tục quét và kết nối với thiết bị DWM1001C."""
    while True:
        print("Scanning for DWM1001C devices...")
        devices = await BleakScanner.discover()
        dw_devices = [d for d in devices if d.name and "DW" in d.name]

        if not dw_devices:
            print("No DWM1001C devices found. Retrying...")
            await asyncio.sleep(5)
            continue

        for device in dw_devices:
            print(f"Connecting to {device.address}...")
            asyncio.create_task(process_device(device))
        
        await asyncio.sleep(10)  # Quét lại mỗi 10 giây

async def main():
    """Chạy chương trình chính."""
    await scan_and_connect()

if __name__ == "__main__":
    asyncio.run(main())
