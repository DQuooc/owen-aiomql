"""Quản lý cấu hình dùng chung của thư viện giao dịch aiomql."""
import os
import json
from pathlib import Path
from typing import Literal, TypeVar, Self
from logging import getLogger
from threading import Lock
from functools import cached_property

from .task_queue import TaskQueue
from .state import  State
from .store import Store

logger = getLogger(__name__)
Bot = TypeVar("Bot")

class Config:
    """Quản lý một thể hiện cấu hình dùng chung trong toàn bộ aiomql."""
    login: int
    trade_record_mode: Literal["csv", "json", "sql"]
    password: str
    config_file: str | Path
    server: str
    path: str | Path
    timeout: int
    filename: str
    _state: State
    _store: Store
    root: Path
    record_trades: bool
    records_dir: Path
    plots_dir: Path
    records_dir_name: str
    plots_dir_name: str
    db_dir_name: str  
    db_name: str | Path
    task_queue: TaskQueue
    bot: Bot
    _instance: Self
    mode: Literal["live"]
    shutdown: bool
    force_shutdown: bool
    db_commit_interval: float
    auto_commit: bool
    flush_state: bool
    stop_trading: bool
    lock: Lock
    auto_commit_state: bool
    _defaults = {
        "timeout": 60000,
        "record_trades": True,
        "records_dir_name": "trade_records",
        "db_dir_name": "db",
        "config_file": None,
        "trade_record_mode": "sql",
        "mode": "live",
        "filename": "aiomql.json",
        "db_name": "",
        "path": "",
        "login": None,
        "password": "",
        "server": "",
        "shutdown": False,
        "force_shutdown": False,
        "root": None,
        "plots_dir_name": "plots",
        "db_commit_interval": 30,
        "auto_commit": False,
        "flush_state": False,
        "stop_trading": False,
        "auto_commit_state": True
    }

    def __new__(cls, *args, **kwargs):
        """Tạo hoặc lấy thể hiện dùng chung của `Config`; phối hợp với `TaskQueue`."""
        with (lock := Lock()) as _:
            if not hasattr(cls, "_instance"):
                cls._lock = lock
                cls._instance = super().__new__(cls)
                cls._instance.task_queue = TaskQueue(mode='infinite')
                cls._instance.set_attributes(**cls._defaults)
                cls._instance.bot = None
        return cls._instance

    def __init__(self, **kwargs):
        """Khởi tạo `Config`; liên kết cấu hình tệp với `State` và `Store`."""
        root = kwargs.pop("root", None)
        config_file = kwargs.pop("config_file", None)
        if self.root is None or root is not None or config_file is not None:
            self.load_config(root=root, config_file=config_file, **kwargs)
        else:
            self.set_attributes(**kwargs)

    def __setattr__(self, name, value):
        """Kiểm soát việc gán thuộc tính của `Config`; liên kết cấu hình tệp với `State` và `Store`."""
        super().__setattr__(name, value)
        setattr(self.__class__, name, value)

    def set_attributes(self, **kwargs):
        """Thiết lập thuộc tính; liên kết cấu hình tệp với `State` và `Store`."""
        if kwargs.get("root", None) is not None:
            kwargs.pop("root", None)
            logger.debug("Tried setting root from set_attributes. Use load_config to change project root")
        if kwargs.get("config_file", None) is not None:
            kwargs.pop("config_file", None)
            logger.debug("Tried setting config_file from set_attributes. Use load_config to change project root")
        [setattr(self, key, value) for key, value in kwargs.items()]

    def find_config_file(self):
        """Tìm cấu hình tệp; đọc hoặc ghi dữ liệu trên hệ thống tệp."""
        try:
            current = Path.cwd()
            current = os.path.commonpath([current, self.root])
            current = Path(current).resolve()
            config_file = current / self.filename
            if config_file.exists():
                return config_file
            if current == self.root:
                return None
            for dirname in current.parents:
                config_file = dirname / self.filename
                if config_file.exists():
                    return config_file
                if self.root == dirname:
                    break
            return None
        except Exception as err:
            logger.debug(f"Error finding config file: {err}")
            return None

    def set_root(self, root: str | Path = None):
        """Thiết lập thư mục gốc; đọc hoặc ghi dữ liệu trên hệ thống tệp."""
        try:
            if root is not None:
                root = Path(root).resolve()
                root.mkdir(parents=True, exist_ok=True) if not root.exists() else ...
                self.root = root

            elif self.root is None:
                self.root = Path.cwd()

            elif not isinstance(self.root, Path):
                self.root = Path(self.root).resolve()
        except Exception as err:
            logger.warning("Error finding root path: %s. The current working directory will be used.", err)
            self.root = Path.cwd()

    def load_config(self, *, config_file: str | Path = None, filename: str = None, root: str | Path = None, **kwargs) -> Self:
        """Nạp cấu hình; đọc hoặc ghi dữ liệu trên hệ thống tệp."""
        self.set_root(root=root)

        if config_file is not None:
            config_file = Path(config_file).resolve()
            if not config_file.exists():
                self.filename = filename or self.filename
                self.config_file = self.find_config_file()
            else:
                self.filename = config_file.name
                self.config_file = config_file
        else:
            self.filename = filename or self.filename
            self.config_file = self.find_config_file()

        if self.config_file is None:
            logger.debug("No Config File Found")
            file_config = {}
        else:
            file_config = {}
            with open(self.config_file, mode="r") as fh:
                file_config = json.load(fh)

        data = file_config | kwargs
        self.set_attributes(**data)
        db_name = self.db_name or (f"db_{self.login}.sqlite3" if self.login else "db.sqlite3") 
        if not Path(db_name).exists():
            db_name = self.root / self.db_dir_name / db_name
            db_name.parent.mkdir(parents=True, exist_ok=True)
            self.db_name = str(db_name)
        os.environ["DB_NAME"] = self.db_name
        self.init_state()
        self.init_store()
        try:
            if self.path:
                self.path = self.root / self.path if not Path(self.path).resolve().exists() else self.path
        except Exception as err:
            logger.debug(f"Error setting path: {err}")
            self.path = ""
        return self

    @property
    def state(self):
        """Đọc hoặc cập nhật trạng thái dùng chung của cấu hình; liên kết cấu hình tệp với `State` và `Store`."""
        if not hasattr(self, "_state"):
            self.init_state()
        return self._state

    @state.setter
    def state(self, value: State):
        """Đọc hoặc cập nhật trạng thái dùng chung của cấu hình; liên kết cấu hình tệp với `State` và `Store`."""
        self._state = value

    @property
    def store(self):
        """Đọc hoặc cập nhật kho dữ liệu dùng chung của cấu hình; liên kết cấu hình tệp với `State` và `Store`."""
        if not hasattr(self, "_store"):
            self.init_store()
        return self._store

    @store.setter
    def store(self, value: Store):
        """Đọc hoặc cập nhật kho dữ liệu dùng chung của cấu hình; liên kết cấu hình tệp với `State` và `Store`."""
        self._store = value

    def init_state(self):
        """Khởi tạo trạng thái; phối hợp với `State`."""
        self.state = State(db_name=self.db_name, flush=self.flush_state, autocommit=self.auto_commit_state)

    def init_store(self):
        """Khởi tạo store; phối hợp với `Store`."""
        self.store = Store(db_name=self.db_name, flush=self.flush_state, autocommit=self.auto_commit_state)

    @cached_property
    def records_dir(self):
        """Lấy thư mục lưu bản ghi giao dịch; liên kết cấu hình tệp với `State` và `Store`."""
        rec_dir = self.root / self.records_dir_name
        rec_dir.mkdir(parents=True, exist_ok=True) if rec_dir.exists() is False else ...
        return rec_dir

    @cached_property
    def plots_dir(self):
        """Lấy thư mục lưu biểu đồ; liên kết cấu hình tệp với `State` và `Store`."""
        p_dir = self.root / self.plots_dir_name
        p_dir.mkdir(parents=True, exist_ok=True) if p_dir.exists() is False else ...
        return p_dir

    @property
    def account_info(self) -> dict[str, int | str]:
        """Lấy thông tin tài khoản giao dịch; liên kết cấu hình tệp với `State` và `Store`."""
        return {"login": self.login, "password": self.password, "server": self.server}
