import struct


def float_to_bytes(value):
    """Chuyển đổi số thực float thành mảng byte 4 byte (IEEE 754)"""
    return struct.pack('f', value)

def xyz_to_byte_array(x, y, z):
    """Chuyển đổi tọa độ x, y, z thành mảng byte"""
    return float_to_bytes(x) + float_to_bytes(y) + float_to_bytes(z)

# # Ví dụ
# x, y, z = 2.03, -1.75, 3.1416
# byte_array = xyz_to_byte_array(x, y, z)
#
# # In kết quả
# print("Mảng byte:", byte_array.hex())  # Hiển thị dưới dạng hex để dễ đọc

