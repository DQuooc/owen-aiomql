from typing import Callable
from concurrent.futures import ProcessPoolExecutor


def process_pool(processes: dict[Callable:dict] = None, num_workers: int = None):
    """Chạy các hàm đã đăng ký trên nhóm tiến trình; gửi công việc tới `ProcessPoolExecutor`."""
    num_workers = num_workers or len(processes) + 1
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        for bot, kwargs in processes.items():
            executor.submit(bot, **kwargs)
