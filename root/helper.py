from colorama import Fore, Style
import struct




def decode_location_data(data):
    try:
        mode = data[0]
        if mode == 0:
            if len(data) <= 13:
                print("Invalid Type 0 data: Expected 13 bytes")
                return None
            return decode_location_mode_0(data)
        elif mode == 1:
            return decode_location_mode_1(data)
        elif mode == 2:
            return decode_location_mode_2(data)
        else:
            print(f"Unknown location mode: {mode}")

    except Exception as e:
        print(f"Error decoding location: {e}")
        return None


# Position Only
def decode_location_mode_0(data):
    result = {}
    # location_mode = data[0]
    # result["Mode:"] = location_mode
    x, y, z, quality_position = struct.unpack("<i i i B", data[1:14])
    result["Position"] = {
        "X": x / 1000,  # Chuyển từ mm sang m
        "Y": y / 1000,
        "Z": z / 1000,
        "Quality Factor": quality_position
    }
    return result

# Distances Only
def decode_location_mode_1(data):
    result = {}
    distances = []
    distance_count = data[0]
    result["Distances count:"] = distance_count
    for i in range(distance_count):
        offset = 1 + i * 7
        node_id, distance, quality = struct.unpack("<H i B", data[offset:offset + 7])
        distances.append({
            "Node ID": node_id,
            "Distance": distance / 1000,  # Chuyển từ mm sang m
            "Quality Factor": quality
        })
    result["Distances"] = distances
    return result

# Position + Distances)
def decode_location_mode_2(data):
    result = {}
    mode_0 = decode_location_mode_0(data[:14])
    mode_1 = decode_location_mode_1(data[14:])
    result.update(mode_0)
    result.update(mode_1)
    return result





class MyPrint:
    SUCCESS_ICON = "✅"
    ERROR_ICON = "❌"
    INFO_ICON = "ℹ️"
    RECONNECT_ICON = "🔄"
    WARNING_ICON = "⚠️"

    @staticmethod
    def info(msg):
        print(MyPrint.INFO_ICON + " " + Fore.LIGHTCYAN_EX + msg + Style.RESET_ALL)

    @staticmethod
    def success(msg):
        print(MyPrint.SUCCESS_ICON + " " + Fore.LIGHTGREEN_EX + msg + Style.RESET_ALL)

    @staticmethod
    def warning(msg):
        print(MyPrint.WARNING_ICON + " " + Fore.YELLOW + msg + Style.RESET_ALL)

    @staticmethod
    def error(msg):
        print(MyPrint.ERROR_ICON + " " + Fore.LIGHTRED_EX + msg + Style.RESET_ALL)

    @staticmethod
    def reconnect(msg):
        print(MyPrint.RECONNECT_ICON + " " + Fore.LIGHTCYAN_EX + msg + Style.RESET_ALL)

# MyPrint.reconnect("Đang xử lý tag...")