import asyncio

from bleak import BleakScanner
from config import ANCHOR_MAC_LIST, TAG_MAC_LIST
from ble_hanlder import process_anchor, process_tag
from helper import MyPrint
async def main():
    from server_handler import connect_to_server, sio
    await connect_to_server()

    # # Tìm các thiết bị BLE
    # devices = await BleakScanner.discover(10)
    # anchors = [dev.address for dev in devices if dev.address in ANCHOR_MAC_LIST]
    # print(f"Danh sách anchor: {anchors}")
    # #
    # # Xử lý từng anchor (chỉ chạy một lần)
    # # print("Đang xử lý anchor...")
    # for anchor in anchors:
    #     await process_anchor(anchor)
    #
    # # # anchor_tasks = [asyncio.create_task(process_anchor(anchor)) for anchor in anchors]
    # # # await asyncio.gather(*anchor_tasks)
    # #
    # MyPrint.info("Đang xử lý tag...")
    # # print("Đang xử lý tag...")
    # # print("Chờ server lệnh để xử lý Tag...")
    # # Khởi chạy task cho từng Tag
    tasks = [asyncio.create_task(process_tag(tag)) for tag in TAG_MAC_LIST]
    await asyncio.gather(*tasks)

    await sio.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print(f"❌ Lỗi runtime: {e}")