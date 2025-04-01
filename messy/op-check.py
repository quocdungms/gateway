# Hàm giải mã Operation Mode
def decode_operation_mode(data):
    if len(data) != 2:
        return "Dữ liệu Operation Mode không hợp lệ (cần 2 bytes)"

    byte1, byte2 = data[0], data[1]

    # Byte 1
    node_type = "Tag" if (byte1 & 0x80) == 0 else "Anchor"
    uwb_mode = ["Off", "Passive", "Active"][(byte1 & 0x60) >> 5]
    firmware = "Firmware 1" if (byte1 & 0x10) == 0 else "Firmware 2"
    accel_enable = bool(byte1 & 0x08)
    led_enable = bool(byte1 & 0x04)
    fw_update_enable = bool(byte1 & 0x02)

    # Byte 2
    initiator_enable = bool(byte2 & 0x80)  # Anchor-specific
    low_power_mode = bool(byte2 & 0x40)  # Tag-specific
    loc_engine_enable = bool(byte2 & 0x20)  # Tag-specific

    return {
        "Node Type": node_type,
        "UWB Mode": uwb_mode,
        "Firmware": firmware,
        "Accelerometer Enabled": accel_enable,
        "LED Enabled": led_enable,
        "Firmware Update Enabled": fw_update_enable,
        "Initiator Enabled": initiator_enable,
        "Low Power Mode": low_power_mode,
        "Location Engine Enabled": loc_engine_enable
    }