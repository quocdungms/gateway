import asyncio
from bleak import BleakClient

from global_var import UPDATE_RATE_UUID
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


def int_to_bytes(value):
    """
    Chuyển số nguyên dương thành 4 byte (little-endian).
    - value: Số nguyên dương (uint32_t)
    - Trả về: bytearray 4 byte
    """
    if not isinstance(value, int) or value < 0 or value > 0xFFFFFFFF:
        raise ValueError("Giá trị phải là số nguyên dương từ 0 đến 4294967295")

    return bytearray([
        value & 0xFF,
        (value >> 8) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 24) & 0xFF
    ])


async def get_op():
    try:
        # Kết nối tới thiết bị
        async with BleakClient(DEVICE_ADDRESS) as client:
            if client.is_connected:
                print(f"Đã kết nối tới thiết bị: {DEVICE_ADDRESS}")

                u1 = 500
                u2 = 100

                u1 = int_to_bytes(u1)
                u2 = int_to_bytes(u2)

                data = u1 + u2
                print("ghi du lieu")
                await client.write_gatt_char(UPDATE_RATE_UUID, data)

                ans = await client.read_gatt_char(UPDATE_RATE_UUID)

                u1 = int.from_bytes(ans[0:4], byteorder="little")
                # Giải mã U2 (4 byte sau, little-endian)
                u2 = int.from_bytes(ans[4:8], byteorder="little")

                print(f"Update rate: U1 = {u1}ms (khi di chuyển), U2 = {u2}ms (khi đứng yên)")


                # data = "0101010100100000"
                # data = bits_to_bytes_array(data)
                #
                # await client.write_gatt_char(OPERATION_MODE_UUID, data)
                # print("ghi op thanh cong")
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


# u1 = 100
# u2 = 2000
#
# print(f"u1: {int_to_bytes(u1)}\nu2: {int_to_bytes(u2)}")
