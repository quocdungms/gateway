import asyncio
from bleak import BleakClient


# Địa chỉ Bluetooth của thiết bị (thay bằng địa chỉ thực tế của bạn)
DEVICE_ADDRESS = "EB:52:53:F5:D5:90"  # Ví dụ, thay bằng địa chỉ thiết bị của bạn

OPERATION_MODE_UUID = "3f0afd88-7770-46b0-b5e7-9fc099598964"
def bytearray_to_bits(byte_arr):
    return ''.join(f"{byte:08b}" for byte in byte_arr)

async def get_op():
    try:
        # Kết nối tới thiết bị
        async with BleakClient(DEVICE_ADDRESS) as client:
            if client.is_connected:
                print(f"Đã kết nối tới thiết bị: {DEVICE_ADDRESS}")

                op = await client.read_gatt_char(OPERATION_MODE_UUID)
                op = bytearray_to_bits(op)
                print(f"op: {op}")
            else:
                print("Không thể kết nối tới thiết bị.")
    except Exception as e:
        print(f"Lỗi: {e}")


# Chạy chương trình
if __name__ == "__main__":
    asyncio.run(get_op())