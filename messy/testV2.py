import asyncio
from bleak import BleakClient

# Thay thế bằng địa chỉ MAC của thiết bị DWM1001
DEVICE_ADDRESS = "77:7F:F6:D1:D1:20"

async def list_uuids(address):
    async with BleakClient(address) as client:
        print(f"Connected: {client.is_connected}")
        print("Discovering services...")
        services = await client.get_services()
        for service in services:
            print(f"Service: {service.uuid}")
            for char in service.characteristics:
                print(f"  Characteristic: {char.uuid} | Properties: {char.properties}")


import asyncio
from bleak import BleakScanner

async def scan_devices():
    print("Scanning for BLE devices...")
    devices = await BleakScanner.discover()
    for device in devices:
        print(f"Device: {device.name}, Address: {device.address}")

# asyncio.run(scan_devices())

asyncio.run(list_uuids(DEVICE_ADDRESS))
