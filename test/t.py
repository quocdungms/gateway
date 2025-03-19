import json
import asyncio

file_lock = asyncio.Lock()

async def update_modules_json(mac, new_type, operation_mode):
    async with file_lock:
        try:
            with open("modules.json", "r", encoding="utf-8") as file:
                data = json.load(file)
            for device in data:
                if device["id"] == mac:
                    device["type"] = new_type
                    device["operation"] = operation_mode
                    break
            with open("modules.json", "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
            print(f"✅ Đã cập nhật modules.json cho {mac} thành {new_type}")
        except Exception as e:
            print(f"❌ Lỗi khi cập nhật modules.json: {e}")

# asyncio.run(update_modules_json("EB:52:53:F5:D5:90", "tag", "0101000100100000" ))

op = "0101000100100000"
print(op[0])