"""Điều phối chương trình giao dịch cùng các chiến lược và tác vụ liên quan."""

import asyncio
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Type, Iterable, Callable, Coroutine
import logging

from .executor import Executor
from ..core.config import Config
from ..core.meta_trader import MetaTrader
from .symbol import Symbol as Symbol
from .strategy import Strategy as Strategy

logger = logging.getLogger(__name__)


class Bot:
    """Điều phối các chiến lược và tác vụ của chương trình giao dịch."""
    """
Lớp Bot chính dùng để điều phối các chiến lược giao dịch.

Bot quản lý kết nối với MetaTrader 5, khởi tạo các chiến lược,
và phối hợp việc thực thi thông qua Executor. Hỗ trợ cả chế độ
đồng bộ (synchronous) và bất đồng bộ (asynchronous).



Thuộc tính:
    config (Config): Cấu hình chứa các thiết lập của bot và
        tham chiếu đến các tài nguyên dùng chung như hàng đợi tác vụ.
    executor (Executor): Bộ quản lý luồng (thread pool executor)
        để thực thi song song các chiến lược, coroutine và hàm.
    mt5 (MetaTrader): Đối tượng giao diện MetaTrader 5.
        Dùng cho giao dịch thực hoặc demo.
    strategies (list[Strategy]): Danh sách các chiến lược sẽ được
        khởi tạo và chạy bởi bot.
    initialized (bool): Cờ cho biết việc khởi tạo terminal có thành công hay không.
    login (bool): Cờ cho biết việc đăng nhập vào tài khoản giao dịch có thành công hay không.

Ví dụ:
    Sử dụng cơ bản với một chiến lược::

        bot = Bot()
        bot.add_strategy(strategy=MyStrategy(symbol=Symbol(name="EURUSD")))
        bot.execute()

    Thêm nhiều chiến lược cùng lúc::

        bot = Bot()
        strategies = [
            Strategy1(symbol=symbol1),
            Strategy2(symbol=symbol2),
        ]
        bot.add_strategies(strategies=strategies)
        await bot.start()
"""

    config: Config
    executor: Executor
    mt5: MetaTrader
    strategies: list[Strategy]
    initialized: bool
    login: bool

    def __init__(self):
        """Khởi tạo `Bot`; phối hợp với `Config` và `Executor`."""
        self.config = Config(bot=self)
        self.executor = Executor()
        self.mt5 = MetaTrader()
        self.strategies = []
        self.initialized = False
        self.login = False

    @classmethod
    def process_pool(cls, processes: dict[Callable:dict] = None, num_workers: int = None):
        """Chạy các hàm đã đăng ký trên nhóm tiến trình; được điều phối bởi `Executor` và `asyncio`."""
        num_workers = num_workers or len(processes) + 1
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            for bot, kwargs in processes.items():
                executor.submit(bot, **kwargs)

    async def start_terminal(self) -> bool:
        """Khởi động phần mềm đầu cuối MetaTrader; gọi `MetaTrader.initialize`, `MetaTrader.login`."""
        res = await self.mt5.initialize()
        if res:
            self.initialized = True
            res = await self.mt5.login()
            if res:
                self.login = True
        return res

    def start_terminal_sync(self) -> bool:
        """Khởi động phần mềm đầu cuối MetaTrader; gọi `MetaTrader.initialize_sync`, `MetaTrader.login_sync`."""
        res = self.mt5.initialize_sync()
        if res:
            self.initialized = True
            res = self.mt5.login_sync()
            if res:
                self.login = True
        return res

    async def initialize(self) -> None:
        """Khởi tạo dữ liệu và tài nguyên của `Bot`; phối hợp các tác vụ qua `asyncio`."""
        try:
            await self.start_terminal()
            if not self.login:
                logger.critical("Unable to sign in to MetaTrder 5 Terminal")
                raise Exception("Unable to sign in to MetaTrader 5 Terminal")
            logger.info("Login Successful")
            await self.init_strategies()
            self.add_coroutine(coroutine=self.config.task_queue.run, on_separate_thread=True)
            self.add_function(function=self.executor.exit)

            if len(self.executor.strategy_runners) == 0:
                logger.warning("No strategies were added to the bot. Exiting in one second")
                await asyncio.sleep(1)
                self.config.shutdown = True
        except Exception as err:
            logger.error("%s: Bot initialization failed", err)
            raise SystemExit

    def initialize_sync(self) -> None:
        """Khởi tạo `Bot` theo luồng đồng bộ; được điều phối bởi `Executor` và `asyncio`."""
        try:
            self.start_terminal_sync()
            if not self.login:
                logger.critical("Unable to sign in to MetaTrder 5 Terminal")
                raise Exception("Unable to sign in to MetaTrader 5 Terminal")
            logger.info("Login Successful")
            self.init_strategies_sync()
            self.add_coroutine(coroutine=self.config.task_queue.run, on_separate_thread=True)
            self.add_function(function=self.executor.exit)

            if len(self.executor.strategy_runners) == 0:
                logger.warning("No strategies were added to the bot. Exiting in one second")
                time.sleep(1)
                self.config.shutdown = True
        except Exception as err:
            logger.error("%s: Bot initialization failed", err)
            raise SystemExit

    def add_function(self, *, function: Callable[..., ...], **kwargs) -> None:
        """Thêm hàm; phối hợp với `Executor.add_function`."""
        self.executor.add_function(function=function, kwargs=kwargs)

    def add_coroutine(
        self, *, coroutine: Callable[..., ...] | Coroutine, on_separate_thread: bool = False, **kwargs
    ) -> None:
        """Thêm hàm bất đồng bộ; phối hợp với `Executor.add_coroutine`."""
        self.executor.add_coroutine(coroutine=coroutine, kwargs=kwargs, on_separate_thread=on_separate_thread)

    def execute(self) -> None:
        """Chạy toàn bộ công việc đã đăng ký trong `Bot`; phối hợp với `Executor.execute`."""
        self.initialize_sync()
        if self.config.shutdown is False:
            self.executor.execute()

    async def start(self) -> None:
        """Khởi động `Bot` và các tác vụ liên quan; phối hợp với `Executor.execute`."""
        await self.initialize()
        if self.config.shutdown is False:
            self.executor.execute()

    def add_strategy(self, *, strategy: Strategy) -> None:
        """Thêm chiến lược; được điều phối bởi `Executor` và `asyncio`."""
        self.strategies.append(strategy)

    def add_strategies(self, *, strategies: Iterable[Strategy]) -> None:
        """Thêm các chiến lược; được điều phối bởi `Executor` và `asyncio`."""
        [self.add_strategy(strategy=strategy) for strategy in strategies]

    def add_strategy_all(
        self, *, strategy: Type[Strategy], params: dict | None = None, symbols: list[Symbol] = None, **kwargs
    ) -> None:
        """Tạo cùng một chiến lược cho nhiều mã giao dịch; được điều phối bởi `Executor` và `asyncio`."""
        [self.add_strategy(strategy=strategy(symbol=symbol, params=params, **kwargs)) for symbol in symbols]

    async def init_strategy(self, *, strategy: Strategy) -> bool:
        """Khởi tạo chiến lược; phối hợp với `Executor.add_strategy`."""
        res = await strategy.initialize()
        if res:
            self.executor.add_strategy(strategy=strategy)
        return res

    async def init_strategies(self) -> None:
        """Khởi tạo các chiến lược; phối hợp các tác vụ qua `asyncio`."""
        tasks = [self.init_strategy(strategy=strategy) for strategy in self.strategies]
        await asyncio.gather(*tasks, return_exceptions=True)

    def init_strategy_sync(self, *, strategy: Strategy) -> bool:
        """Khởi tạo chiến lược; phối hợp với `Executor.add_strategy`."""
        res = strategy.initialize_sync()
        if res:
            self.executor.add_strategy(strategy=strategy)
        return res 

    def init_strategies_sync(self) -> None:
        """Khởi tạo các chiến lược; được điều phối bởi `Executor` và `asyncio`."""
        [self.init_strategy_sync(strategy=strategy) for strategy in self.strategies]
