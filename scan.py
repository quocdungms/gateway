import asyncio
from bleak import BleakClient

# UUID của Battery Service và Battery Level Characteristic
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# Địa chỉ Bluetooth của thiết bị (thay bằng địa chỉ thực tế của bạn)
DEVICE_ADDRESS = "D7:7A:01:92:9B:DB"  # Ví dụ, thay bằng địa chỉ thiết bị của bạn


async def get_battery_level():
    try:
        # Kết nối tới thiết bị
        async with BleakClient(DEVICE_ADDRESS) as client:
            if client.is_connected:
                print(f"Đã kết nối tới thiết bị: {DEVICE_ADDRESS}")

                # Đọc giá trị từ Battery Level Characteristic
                battery_level = await client.read_gatt_char(BATTERY_LEVEL_UUID)

                # Giá trị trả về là byte, chuyển thành phần trăm (0-100)
                battery_percentage = int.from_bytes(battery_level, "little")
                print(f"Mức pin: {battery_percentage}%")
            else:
                print("Không thể kết nối tới thiết bị.")
    except Exception as e:
        print(f"Lỗi: {e}")


# Chạy chương trình
if __name__ == "__main__":
    asyncio.run(get_battery_level())