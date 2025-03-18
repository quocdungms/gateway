import asyncio
from bleak import BleakClient


# Địa chỉ Bluetooth của thiết bị (thay bằng địa chỉ thực tế của bạn)
DEVICE_ADDRESS = "EB:52:53:F5:D5:90"  # Ví dụ, thay bằng địa chỉ thiết bị của bạn

OPERATION_MODE_UUID = "3f0afd88-7770-46b0-b5e7-9fc099598964"
def bytearray_to_bits(byte_arr):
    return ''.join(f"{byte:08b}" for byte in byte_arr)
def bits_to_bytes_array(bit_string):
    # Đảm bảo chuỗi bit có độ dài là bội số của 8
    bit_string = bit_string.zfill((len(bit_string) + 7) // 8 * 8)

    # Chuyển đổi sang số nguyên
    integer_value = int(bit_string, 2)

    # Chuyển thành mảng byte
    byte_length = len(bit_string) // 8
    return integer_value.to_bytes(byte_length, byteorder='big')
async def get_op():
    try:
        # Kết nối tới thiết bị
        async with BleakClient(DEVICE_ADDRESS) as client:
            if client.is_connected:
                print(f"Đã kết nối tới thiết bị: {DEVICE_ADDRESS}")
                data = "0101010100100000"
                data = bits_to_bytes_array(data)

                await client.write_gatt_char(OPERATION_MODE_UUID, data)
                print("ghi op thanh cong")
                # op = await client.read_gatt_char(OPERATION_MODE_UUID)



                # op = bytearray_to_bits(op)
                # print(f"op: {op}")
            else:
                print("Không thể kết nối tới thiết bị.")
    except Exception as e:
        print(f"Lỗi: {e}")





# Chạy chương trình
if __name__ == "__main__":
    asyncio.run(get_op())

