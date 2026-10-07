"""Thực thi đồng thời nhiều chiến lược và tác vụ giao dịch."""

import asyncio
import inspect
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Coroutine, Callable
from logging import getLogger

from ..core.config import Config
from .strategy import Strategy

logger = getLogger(__name__)


class Executor:
    """Chạy đồng thời nhiều chiến lược trên nhiều mã giao dịch."""
    executor: ThreadPoolExecutor
    config: Config

    def __init__(self):
        """Khởi tạo `Executor`; phối hợp với `Config`."""
        self.strategy_runners: list[Strategy] = []
        self.coroutines: dict[Coroutine: dict] = {}
        self.coroutine_threads: dict[Coroutine: dict] = {}
        self.functions: dict[Callable:dict] = {}
        self.config = Config()
        self.timeout = None  # Thời gian chờ của bộ thực thi, chỉ dùng khi kiểm thử

    def add_function(self, *, function: Callable, kwargs: dict = None):
        """Thêm hàm; được điều phối bởi `Executor` và `asyncio`."""
        kwargs = kwargs or {}
        self.functions[function] = kwargs

    def add_coroutine(self, *, coroutine: Callable | Coroutine, kwargs: dict = None, on_separate_thread=False):
        """Thêm hàm bất đồng bộ; được điều phối bởi `Executor` và `asyncio`."""
        kwargs = kwargs or {}
        if on_separate_thread:
            self.coroutine_threads[coroutine] = kwargs
        else:
            self.coroutines[coroutine] = kwargs

    def add_strategies(self, *, strategies: tuple[Strategy]):
        """Thêm các chiến lược; được điều phối bởi `Executor` và `asyncio`."""
        self.strategy_runners.extend(strategies)

    def add_strategy(self, *, strategy: Strategy):
        """Thêm chiến lược; được điều phối bởi `Executor` và `asyncio`."""
        self.strategy_runners.append(strategy)

    @staticmethod
    def run_strategy(strategy: Strategy):
        """Chạy vòng lặp giao dịch của một chiến lược; phối hợp các tác vụ qua `asyncio`."""
        if inspect.iscoroutinefunction(strategy.run_strategy):
            asyncio.run(strategy.run_strategy())
        else:
            strategy.run_strategy()

    async def run_coroutine_tasks(self):
        """Chạy đồng thời các hàm bất đồng bộ đã đăng ký; phối hợp các tác vụ qua `asyncio`."""
        try:
            await asyncio.gather(*[coroutine(**kwargs) for coroutine, kwargs in self.coroutines.items()],
                                 return_exceptions=True)
        except Exception as err:
            logger.error("%s: Error occurred in run_coroutine_tasks", err)

    @staticmethod
    def run_coroutine_task(coroutine, kwargs):
        """Chạy một hàm bất đồng bộ trong vòng lặp sự kiện riêng; phối hợp các tác vụ qua `asyncio`."""
        asyncio.run(coroutine(**kwargs))

    @staticmethod
    def run_function(function: Callable, kwargs: dict):
        """Chạy một hàm đồng bộ đã đăng ký; được điều phối bởi `Executor` và `asyncio`."""
        function(**kwargs)

    def exit(self):
        """Dừng `Executor` và giải phóng tác vụ đang chạy; phối hợp với `Config` và `Executor.shutdown`."""
        start = time.time()
        try:
            while True:
                if self.timeout is not None and self.timeout < (time.time() - start):
                    self.config.shutdown = True
                    break
                timeout = self.timeout or 1
                time.sleep(timeout)
                if self.config.shutdown or self.config.force_shutdown:
                    break
                if all(strategy.running is False for strategy in self.strategy_runners):
                    break
            for strategy in self.strategy_runners:
                strategy.running = False
            self.config.task_queue.cancel()
            self.executor.shutdown(wait=False, cancel_futures=False)

            if self.config.force_shutdown:
                os._exit(1)
        except Exception as err:
            logger.error("%s: Unable to shutdown executor", err)
            os._exit(1)

    def execute(self, *, workers: int = 5):
        """Chạy toàn bộ công việc đã đăng ký trong `Executor`; phối hợp với `Executor.submit`."""
        workers_ = len(self.strategy_runners) + len(self.functions) + len(self.coroutine_threads) + 3
        workers = max(workers, workers_)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            self.executor = executor
            [self.executor.submit(self.run_strategy, strategy) for strategy in self.strategy_runners]
            [self.executor.submit(function, **kwargs) for function, kwargs in self.functions.items()]
            [self.executor.submit(self.run_coroutine_task, coroutine, kwargs) for coroutine, kwargs in
             self.coroutine_threads.items()]
            self.executor.submit(asyncio.run, self.run_coroutine_tasks())
