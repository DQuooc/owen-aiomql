import asyncio
from aiomql import ResultDB, Result, TradeRecords

async def update_sql_records():
    """Cập nhật các bản ghi giao dịch trong SQLite; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    tr = TradeRecords()
    # await tr.update_sql_records()
    # await tr.update_csv_records()
    await tr.update_json_records()


def to_csv():
    """Xuất bản ghi sang tệp CSV; phối hợp với `ResultDB.dump_to_csv`."""
    ResultDB.dump_to_csv()


if __name__ == "__main__":
    asyncio.run(update_sql_records())
    # to_csv()
