# AIOMQL — Execution Flow Overview

Ngày phân tích: 2026-10-18 (Asia/Bangkok). Repository: `E:\BLC\Dev_AI_MT5`.

Snapshot tham chiếu: HEAD `431e133e85bcea44dd8bbc9d192c40f8c0cd3155`, **cộng nội dung working tree hiện tại**. `open_position.py`, hai wrapper MetaTrader và một số file khác đã có thay đổi trước phiên này. Line number bên dưới trỏ vào nội dung trên đĩa lúc đọc, không mặc định trỏ vào HEAD.

Đây là phân tích tĩnh để học code. Không import/chạy aiomql, không chạy bot/test, không kết nối MT5, không gửi lệnh. Chỉ hai tài liệu trong `docs/code-reading` được tạo. Không sửa source, test, config hay thực hiện lệnh thay đổi Git state.

Quy ước bằng chứng:

- **VERIFIED**: tìm thấy trực tiếp trong source và call site; không đồng nghĩa đã chạy thành công trên MT5.
- **PARTIALLY VERIFIED**: đã trace một phần, phần còn lại được chỉ rõ.
- **INFERENCE**: suy luận hoặc nhận định hướng dẫn đọc, không phải hành vi đã quan sát khi chạy.
- **NOT FOUND**: không thấy trong phạm vi tìm kiếm được nêu.
- **NOT VERIFIED**: chưa kiểm tra; không đoán.

Mỗi bảng hoặc sơ đồ có nhãn áp dụng cho toàn bộ nội dung của nó, trừ nơi ghi nhãn riêng. Tất cả path source là path chính xác tương đối với repository root; ví dụ `src/aiomql/lib/bot.py:153–157` tương ứng `E:\BLC\Dev_AI_MT5\src\aiomql\lib\bot.py`, dòng 153–157. Các đoạn code/sơ đồ là chỉ dẫn đọc, không phải lệnh để chạy bot.

## 1. Execution flow tổng quan

**VERIFIED — tuyến chính được chọn:** demo `examples/sample_app/bot.py::x_bot()` nối được startup, gửi lệnh và quản lý position. Sơ đồ ban đầu `Bot → Executor → Strategy → Trader → Order → MetaTrader → MT5 API` đúng về quan hệ điều phối, nhưng chưa thể hiện construction, startup API calls, các lần check, thread và nhánh tracker.

```text
examples/sample_app/bot.py::__main__ → x_bot()
  ├─ ForexSymbol(...) → EMAXOver(...) → TestTrader(...) → Order(...)
  └─ Bot() → add_strategies(...) + add_coroutine(OpenPositionsTracker.track, separate_thread=True)
       → Bot.execute()
          → initialize_sync()
             ├─ start_terminal_sync() → MetaTrader.initialize_sync()/login_sync() → MT5 API
             └─ init_strategy_sync() → Strategy.initialize_sync() → Symbol.initialize_sync() → MT5 API
          → Executor.execute() [ThreadPoolExecutor]
             ├─ run_strategy(strategy) → asyncio.run(strategy.run_strategy())
             │    → Strategy.live_strategy() → EMAXOver.trade() → find_entry()
             │    → TestTrader.place_trade() → Trader helpers → Order.check()/send()
             │    → MetaTrader.order_send() → _handler() → asyncio.to_thread(_order_send, request)
             │    → MetaTrader5.order_send(request)
             ├─ OpenPositionsTracker.track() [event loop riêng]
             ├─ Config.task_queue.run() [event loop riêng]
             └─ Executor.exit() [hàm đồng bộ ở worker khác]
```

**VERIFIED — entry point và cách strategy vào runtime:**

| Loại | Vị trí | Vai trò thực tế |
|---|---|---|
| Example chính | `examples/sample_app/bot.py:10–23`, `x_bot()` | Tạo symbol và `EMAXOver` trước `Bot`; thêm strategy vào Bot; đăng ký tracker; gọi `bot.execute()` ở dòng 19. Guard dòng 22–23 bắt đầu lifecycle khi module được chạy làm main. |
| Example async | `examples/sample_app_2/bot.py:7–17`, `rs_bot()` | Tạo Bot trước symbol/strategy; tạo `RibbonScalper`; `await bot.start()`; ngoài cùng `asyncio.run(rs_bot())`. Không đăng ký `OpenPositionsTracker` trong entry này. |
| Framework core | `src/aiomql/lib/bot.py:66–73,153–163` | `Bot` là đối tượng điều phối do ứng dụng tạo; không tự phát hiện và instantiate strategy. Hai API bắt đầu là `execute()` và `start()`. |
| Contrib strategy | `src/aiomql/contrib/strategies/chaos.py:28–32,58–71` | `Chaos` tạo `ScalpTrader`; `trade()` gọi `place_trade()`. Đây là lớp strategy có thể được app đăng ký, không phải entry point. |
| Đăng ký runtime | `src/aiomql/lib/bot.py:165–200` | `add_strategies()` chỉ lưu instance. Chỉ sau `strategy.initialize[_sync]()` trả truthy thì Bot gọi `executor.add_strategy()`; Executor mới đưa instance vào thread pool. |

**NOT FOUND — production/custom entry point riêng:** tìm call site `Bot(`, `bot.start()`, `bot.execute()` và `process_pool(` trong `src`/`examples`; ngoài core/docstring, chỉ thấy hai demo trên. `pyproject.toml` không có `[project.scripts]` hoặc `[project.entry-points...]`. Điều này không chứng minh cách người dùng đang launch ngoài repository. Không xem README snippet là một production deployment đã xác minh.

**INFERENCE — nên bắt đầu học ở đâu:** mở `src/aiomql/lib/bot.py::Bot.execute()` trước để thấy chốt nối startup với runtime trong vài dòng; sau đó xem caller `examples/sample_app/bot.py::x_bot()`. Entry point dùng để trace vẫn là `x_bot()`. Phần 7 và README dùng cùng điểm bắt đầu học `Bot.execute()` để lần sau tiếp tục nhất quán.

## 2. Actual call chain

### 2.1. Construction và startup của tuyến chính

**VERIFIED — các bước theo call site, không suy từ tên class:**

| Bước / file:line / class.method | Ai gọi | Gọi tiếp / nhiệm vụ |
|---|---|---|
| 1. `examples/sample_app/bot.py:22–23`, module guard → `x_bot()` tại 10–19 | Python khi module là main | Bắt đầu cấu hình app; không phải framework tự gọi. |
| 2. `examples/sample_app/bot.py:12–14`, `x_bot()` | Bước 1 | Tạo năm `ForexSymbol`, rồi năm `EMAXOver(symbol=...)`; truyền instance, không truyền tên lớp vào Bot. |
| 3. `examples/sample_app/emaxover.py:19–24`, `EMAXOver.__init__()` | List comprehension dòng 14 của entry | `Strategy.__init__()`, `Tracker(...)`, `TestTrader(symbol=self.symbol)`. Trader và Order tồn tại trước khi Bot chạy. |
| 4. `src/aiomql/lib/strategy.py:60–70`, `Strategy.__init__()` | Constructor subclass | Copy/merge parameters, thêm `symbol`/`name`, giữ symbol, tạo Sessions mặc định, `running=True`, Config và MetaTrader. |
| 5. `examples/sample_app/traders/test_trader.py:12–16`, `TestTrader.__init__()` | `EMAXOver.__init__()` | `Trader.__init__()`, `Positions()`, `Store()`. Store không phải đường gửi lệnh trong demo này. |
| 6. `src/aiomql/lib/trader.py:30–36`, `Trader.__init__()` | Constructor subclass | Giữ cùng symbol, tạo `RAM()` mặc định và **một** `Order(symbol=symbol.name)`, parameters rỗng. |
| 7. `src/aiomql/lib/order.py:15–18`, `Order.__init__()` | Trader | Đặt mặc định `action=DEAL`, `type_time=DAY`, `type_filling=FOK`, rồi `Base.__init__()`/`set_attributes()`. |
| 8. `src/aiomql/core/base.py:21–32,40–42,55–70`, `BaseMeta.__call__()/_setup()`, `Base` | Construction của lớp dùng BaseMeta, gồm Order/Symbol/Positions | Sau construction, thiết lập `config`, `mt5` cấp lớp nếu chưa có. Mặc định chọn async MetaTrader; không tạo connection broker tại riêng bước gán wrapper. |
| 9. `examples/sample_app/bot.py:15` → `src/aiomql/lib/bot.py:66–73`, `Bot.__init__()` | `x_bot()` | `Config(bot=self)`, `Executor()`, `MetaTrader()`, danh sách strategies và hai cờ startup. |
| 10. `src/aiomql/lib/bot.py:169–171,165–167`, `Bot.add_strategies()/add_strategy()` | Entry dòng 16 | Lưu chính các strategy instance vào `self.strategies`; chưa gọi trade. |
| 11. `examples/sample_app/bot.py:17` → `src/aiomql/lib/bot.py:147–151` → `src/aiomql/lib/executor.py:36–42`, `add_coroutine()` | `x_bot()` | Lưu bound callable `OpenPositionsTracker(...).track` vào `coroutine_threads`. Chưa gọi coroutine và chưa tạo asyncio Task. |
| 12. `src/aiomql/lib/bot.py:153–157`, `Bot.execute()` | Entry dòng 19 | Gọi `initialize_sync()`, rồi chỉ chạy Executor khi `config.shutdown is False`. |
| 13. `src/aiomql/lib/bot.py:123–141,93–101`, `initialize_sync()/start_terminal_sync()` | `execute()` | `mt5.initialize_sync()` rồi `mt5.login_sync()` nếu initialize thành công; cập nhật cờ. Login không thành công làm startup kết thúc bằng SystemExit qua handler. |
| 14. `src/aiomql/core/meta_trader.py:118–133,92–99`, `MetaTrader.initialize_sync()/login_sync()` | Bot startup | Đọc Config, gọi `_initialize(...)`, `_login(...)` trực tiếp trong caller thread. Đây vẫn là **async-wrapper class có sync helpers**, không phải chuyển sang `core/sync/meta_trader.py`. |
| 15. `src/aiomql/core/_core.py:247–280,299–308`, `MetaBase.__new__()` | Khi lớp MetaCore/MetaTrader được tạo lúc import | Gắn `_initialize`, `_login`, `_order_send`... từ `MetaTrader5.__dict__`. Vì vậy bước 14 thực sự gọi package MetaTrader5. Đây là cơ chế binding, không phải một frame gọi lại metaclass cho mỗi order. |
| 16. `src/aiomql/lib/bot.py:198–200,191–196`, `init_strategies_sync()/init_strategy_sync()` | `initialize_sync()` | Lần lượt gọi `strategy.initialize_sync()`; chỉ đăng ký strategy khởi tạo thành công vào Executor. |
| 17. `src/aiomql/lib/strategy.py:109–111` → `src/aiomql/lib/symbol.py:89–112`, `initialize_sync()` | Bot bước 16 | Symbol gọi `_symbol_select`, `_market_book_add`, `_symbol_info`, `_symbol_info_tick`; cập nhật symbol/tick, trả bool. Native calls này chạy trực tiếp, chưa có strategy event loop. |
| 18. `src/aiomql/lib/executor.py:48–50`, `Executor.add_strategy()` | Bot khi bước 17 thành công | Giữ instance trong `strategy_runners`. |
| 19. `src/aiomql/lib/bot.py:132–133` → `add_coroutine()/add_function()` | `initialize_sync()` | Đăng ký thêm `config.task_queue.run` ở separate thread và hàm `executor.exit`; sau đó trở về `execute()`. |

**VERIFIED — nhánh startup async khác ở đâu:** `examples/sample_app_2/bot.py:13` → `Bot.start()` (`lib/bot.py:159–163`) → `initialize()` (103–121) → `start_terminal()` (83–91) → `MetaTrader.initialize()/login()` (`core/meta_trader.py:101–116,84–90`, dùng `asyncio.to_thread`). `Bot.init_strategies()` (186–189) dùng `gather(..., return_exceptions=True)`; `init_strategy()` (179–184) await `Strategy.initialize()` (105–107) → `Symbol.initialize()` (`lib/symbol.py:62–87`). Các symbol calls đi qua wrapper async và `_handler`. Sau startup, **cả hai nhánh đều gọi đồng bộ cùng `Executor.execute()`**.

### 2.2. Runtime đến API gửi lệnh

**VERIFIED — tuyến `EMAXOver → TestTrader`, trong điều kiện signal và preflight hợp lệ:**

| Bước / file:line / class.method | Ai gọi | Gọi tiếp / nhiệm vụ |
|---|---|---|
| 20. `src/aiomql/lib/executor.py:103–113`, `Executor.execute()` | Bot execute/start | Tạo ThreadPoolExecutor, `submit(run_strategy, strategy)` cho từng runner; submit function, coroutine riêng thread và nhóm coroutine chung. |
| 21. `src/aiomql/lib/executor.py:52–58`, `Executor.run_strategy()` | Thread pool worker | Nếu `strategy.run_strategy` là coroutine function, gọi `asyncio.run(strategy.run_strategy())`; nhánh sync gọi thẳng method. |
| 22. `src/aiomql/lib/strategy.py:128–139`, `Strategy.run_strategy()/live_strategy()` | `asyncio.run` ở bước 21 | Await `live_strategy`; vào async context, loop theo `running`; await Sessions.check rồi await **subclass** `self.trade()`. |
| 23. `src/aiomql/lib/strategy.py:88–92` → `src/aiomql/lib/sessions.py:197–222`, `Strategy.__aenter__()/Sessions.check()` | `async with self` và mỗi vòng strategy | Chọn/mở/chuyển phiên hoặc ngủ đến phiên tiếp; session mặc định của Strategy không cấu hình action đóng lệnh. Không phải chu kỳ nào cũng đi tới trader ngay. |
| 24. `examples/sample_app/emaxover.py:52–59,26–50`, `EMAXOver.trade()/find_entry()` | `Strategy.live_strategy()` | Lấy nến, tính EMA/above/below, cập nhật Tracker. Không có signal thì sleep; có signal thì await `trader.place_trade(...)`, sau đó delay. |
| 25. `src/aiomql/lib/symbol.py:181–186` → `src/aiomql/core/meta_trader.py:243–251`, `copy_rates_from_pos()` | `find_entry()` dòng 29 | Wrapper Symbol → wrapper MetaTrader → `_handler(_copy_rates_from_pos)` → to_thread → package API; array quay về được bọc thành `Candles`. Đây là nhánh dữ liệu thị trường trước gửi lệnh. |
| 26. `examples/sample_app/traders/test_trader.py:18–27`, `TestTrader.place_trade()` | `EMAXOver.trade()` dòng 58 | Merge parameters; chọn volume; await `create_order_no_stops()`, await `check_order()`, đặt comment, await `send_order()`. |
| 27. `src/aiomql/lib/trader.py:112–117,38–48`, `Trader.create_order_no_stops()/_set_order_volume()` | TestTrader | Await Symbol.info_tick; xác thực/chặn giới hạn volume; cập nhật chính Order đã có bằng price và type. BUY dùng ask. |
| 28. `src/aiomql/lib/symbol.py:31–46` → `src/aiomql/core/meta_trader.py:189–193`, `Symbol.info_tick()/MetaTrader.symbol_info_tick()` | Trader bước 27 | `_handler(_symbol_info_tick)` → to_thread → MT5 API; tạo Tick và lưu `symbol.tick`. |
| 29. `src/aiomql/lib/trader.py:119–132`, `Trader.check_order()` | TestTrader | `_order_check_passed=False`; await `order.check()`; chỉ retcode 0 mới bật True và trả check result; retcode khác trả None. |
| 30. `src/aiomql/lib/order.py:54–60,101–104`, `Order.check()/request` | Trader.check_order, hoặc Order.send | Tạo dict request; await `mt5.order_check(req)`; None gây OrderError; kết quả native được bọc thành aiomql OrderCheckResult. |
| 31. `src/aiomql/core/meta_trader.py:331–339`, `MetaTrader.order_check()` | Order.check | Cắt comment dài quá 25 ký tự trên dict nhận vào; `_handler` với `_order_check`; trả raw MT5 result. |
| 32. `src/aiomql/lib/trader.py:134–152`, `Trader.send_order()` | TestTrader sau check | Không gửi nếu cờ check là False; kiểm volume lần nữa; await `order.send()`; phân nhánh DONE_PARTIAL/DONE/retcode khác rồi trả result. |
| 33. `src/aiomql/lib/order.py:62–68`, `Order.send()` | Trader.send_order | Snapshot `request=self.request`; **check lại** bằng `await self.check(**request)`; rejected thì OrderError; hợp lệ mới gọi classmethod `send_order(request=...)`. |
| 34. `src/aiomql/lib/order.py:70–79`, `Order.send_order()` | Order.send, hoặc caller gửi dict trực tiếp như Positions | Await `cls.mt5.order_send(request)`; unconfirmed result gây OrderSendAmbiguous; result xác định được bọc thành aiomql OrderSendResult. `connection_retries` giữ signature nhưng không dùng để resend. |
| 35. `src/aiomql/core/meta_trader.py:341–375`, `MetaTrader.order_send()` — preflight | Order.send_order | Copy dict; lấy symbol_info, validate volume cho DEAL/PENDING hoặc có volume; cắt comment; native check cuối qua `_handler(... retry_safe=False)` trên một copy; đòi retcode int 0 và request không bị check thay đổi. |
| 36. `src/aiomql/core/meta_trader.py:376–385,59–82`, `order_send()/_handler()` — submission | Bước 35 thành công | Chọn `func=self._order_send`, `args=(request,)`; await `_handler(... retry_safe=False)` → **await `asyncio.to_thread(func, *args, **kwargs)` tại dòng 68**. |
| 37. `src/aiomql/core/_core.py:267–268,299–308`, binding `_order_send` → `MetaTrader5.order_send` | Worker do `to_thread` sử dụng | Chạy native callable của package với dict request. Không có một function Python `_order_send()` riêng để tìm trong repo; tên được metaclass gắn vào lớp. |
| 38. `src/aiomql/core/meta_trader.py:378–385` → `src/aiomql/lib/order.py:76–79` → `src/aiomql/lib/trader.py:140–152` | Native call hoàn tất | Raw result → wrapper MetaTrader → aiomql model → Trader. TestTrader đọc `retcode` tại dòng 28 để tiếp tục position tracking và record. |

**VERIFIED — kết quả không tự đi nguyên vẹn tới Bot:** `TestTrader.place_trade()` không `return res`; `EMAXOver.trade()` chỉ await, rồi delay. `Strategy.live_strategy()` tiếp tục vòng lặp. Executor submit strategy chạy dài hạn, không thu `OrderSendResult` từ mỗi trade (`executor.py:109–113`). Đường trả result trực tiếp dừng ở logic trader/custom caller, trừ khi subclass chủ động truyền nó đi.

### 2.3. Data flow và lifetime cần nắm

**VERIFIED — các object trực tiếp trên tuyến; lifetime mô tả nơi source giữ reference, không cam kết thời điểm GC:**

| Object/data | Tạo ở đâu → truyền cho ai | Ai thay đổi / ai đọc | Reference/lifetime |
|---|---|---|---|
| `Config` | `core/config.py:74–92`; có thể được tạo từ construction symbol trước Bot; `Bot.__init__` gọi `Config(bot=self)` | Chứa flags, credentials, state/store, TaskQueue; Bot/Executor/Trader/wrappers đọc cùng singleton. `Config.__setattr__` 94–97 gán cả instance và class. | Giữ trong `_instance`; không phải một Config độc lập cho từng strategy. |
| Strategy instance | Entry tạo `EMAXOver` (`sample_app/bot.py:14`) | Constructor thiết lập parameters; Bot initialize; Executor và chính strategy đọc/đổi `running`; `trade()` dùng subclass trader. | Cùng reference trong list Bot và `Executor.strategy_runners`; sống qua nhiều chu kỳ. |
| `ForexSymbol` / `Symbol` | Entry dòng 13; lớp ForexSymbol kế thừa Symbol, không override startup (`contrib/symbols/forex_symbol.py:6–27`) | Symbol.initialize cập nhật metadata/limits/tick; Trader đọc volume_min/max/step, ask/bid. Strategy và Trader giữ cùng symbol instance. | Dài hạn theo strategy/trader; tick và metadata có thể được cập nhật tại các lần gọi. |
| `Candles`, `Tick` | `lib/symbol.py:181–186,31–43` sau API trả array/namedtuple | Strategy thêm/đổi cột EMA; Trader đọc Tick.ask để định giá BUY. | Candles là dữ liệu phân tích của lần find_entry; latest Tick còn được symbol giữ. Không có stream callback ở tuyến này. |
| `Tracker` = `StrategyTracker` | `contrib/utils/__init__.py:1` export alias; `EMAXOver.__init__:23` tạo | `StrategyTracker.update()` (`strategy_tracker.py:35–51`) đổi order_type/snooze; `trade()` đọc. | Dài hạn theo strategy. **Không phải PositionTracker** và không chứa position broker. |
| `Trader` / `TestTrader` | `EMAXOver.__init__:24` | Giữ symbol, RAM, parameters, Order; helpers mutate Order; place_trade đọc kết quả. | Dùng lại qua chu kỳ. TestTrader không gọi reset_order trong place_trade; RSTrader/ScalpTrader có gọi ở nhánh bình thường. |
| `Order` | `Trader.__init__:35`, không phải cứ có signal mới instantiate | Trader điền type/price/volume/comment. `Order` kế thừa TradeRequest; `Base.set_attributes()` convert theo annotations. | Theo Trader cho tới khi thay reference; `Trader.reset_order()` ở 178–181 tạo Order mới. Không giả định mọi subclass đều reset. |
| Request `dict` | `Order.request` (`order.py:101–104`) lấy Base.dict rồi lọc field bằng native `TradeRequest.__match_args__` | `check()` merge kwargs thành dict; wrapper check có thể rút comment. `MetaTrader.order_send()` copy/validate/normalize rồi check một copy khác. | Các snapshot theo lần check/send; không phải chính Order object được truyền qua native API. |
| `TradeRequest` model | `core/models.py:249–270`; Order kế thừa, result models tạo nested request | `OrderCheckResult.__init__` và `OrderSendResult.__init__` convert raw request; record_trade có thể cập nhật nested sl/tp từ history. | Nằm trong result wrapper, tách với request dict và mutable Order đang chuẩn bị. |
| `OrderCheckResult` | `Order.check():60` từ native `res._asdict()`; model `core/models.py:273–291` | Trader đọc retcode 0; Order.send cũng đọc retcode. Final check ở MetaTrader dùng **raw** native result, không tạo model này. | Ngắn hạn theo preflight, không lưu làm bằng chứng cho phép wrapper gửi bỏ qua final check. |
| `OrderSendResult` | `Order.send_order():79`; model `core/models.py:305–326` | Trader kiểm retcode; TestTrader đọc order ticket; record_trade/Result giữ result và nested request. | Có thể được Result giữ lâu hơn coroutine gửi; không tự trở thành position. |
| `TradePosition` | `Positions.get_positions()` (`lib/positions.py:23–43`) bọc raw positions_get | OpenPosition giữ snapshot; update_position thay snapshot khi polling; callbacks đọc profit, volume, type, ticket. | Snapshot mới mỗi lần lấy; OpenPosition là manager dài hạn. Order ticket và position ticket được demo nối bằng `res.order`, không phải phép đồng nhất được đảm bảo cho mọi tình huống broker. |
| `OpenPosition` | `TestTrader.place_trade():29–31` sau DONE | Post-init đăng ký state, thêm default trackers; callbacks và position methods đổi snapshot/flags/pending/hedges/stacks. | Được State giữ ở tracked_positions; có thể chuyển sang archived_positions khi remove_from_state. |
| `State` | `Config.init_state()` (`config.py:214–216`) và `State.__new__/__init__` (`state.py:26–39`) | OpenPosition ghi vào mapping; OpenPositionsTracker đọc cùng singleton, không đọc từ Strategy.tracker. State có persistence, chỉ trace điểm gọi cần cho execution. | `_instance`, `_data` dùng chung; nested dict giữ OpenPosition trong luồng logic này. Khả năng serialize/reload graph object không được xác minh runtime. |
| `Result` / `QueueItem` | `Trader.record_trade()` (`trader.py:154–176`) → `Result(...)` → `QueueItem(res.save)` | record_trade copy parameters, bổ sung expected_profit/history; TaskQueue worker await save. | QueueItem giữ bound method, từ đó giữ Result; queue xử lý sau, place_trade không đợi file/DB save khi dùng queue. |

**NOT FOUND:** tên class `OrderRequest`, `TradeResult`, `Position` trong các thư mục `src/aiomql/lib`, `core`, `contrib` và examples đã search. Tên dùng trên tuyến này là `TradeRequest`, `OrderSendResult`/`Result`, `TradePosition`/`OpenPosition`; không nên thay chúng bằng tên trong sơ đồ giả định.

### 2.4. Giải thích các class như người hướng dẫn code

Các câu về vai trò/caller/state/method dưới đây là **VERIFIED** qua các vị trí đã dẫn. Câu “nếu bỏ” và “đọc trước” là **INFERENCE** nhằm hiểu trách nhiệm, không phải đề xuất bỏ hoặc sửa lớp.

#### Bot — `src/aiomql/lib/bot.py:18–200`

- **Class này tồn tại để làm gì?** Ghép startup terminal, initialize strategies và runtime executor.
- **Ai tạo nó?** `x_bot()` hoặc `rs_bot()` trong hai example.
- **Ai gọi nó?** App gọi add_strategies/add_coroutine rồi execute/start.
- **Nó giữ state gì?** Config, Executor, MetaTrader, strategies, initialized/login.
- **Method quan trọng nhất là gì?** `execute()` và `start()`, với startup ở initialize_sync/initialize.
- **Nó gọi class nào tiếp theo?** MetaTrader, Strategy/Symbol khi startup, Executor khi runtime.
- **Nếu bỏ class này khỏi flow thì chuyện gì xảy ra?** App phải tự lắp toàn bộ startup/registration/execution; Bot không thực hiện quyết định BUY.
- **Khi mở source, method nào đọc trước?** `execute():153`, rồi __init__, initialize_sync, init_strategy_sync, start.

#### Executor — `src/aiomql/lib/executor.py:17–113`

- **Tồn tại để làm gì?** Chạy runners và các callable đã đăng ký bằng thread pool; dựng event loop cho callable async.
- **Ai tạo?** Bot.__init__.
- **Ai gọi?** Bot thêm strategy/coroutine/function và gọi execute.
- **Giữ state gì?** strategy_runners, coroutines, coroutine_threads, functions, Config, executor và timeout.
- **Method quan trọng nhất?** execute và run_strategy; run_coroutine_task là cầu cho background coroutine.
- **Gọi class nào tiếp?** Strategy; đồng thời gọi TaskQueue hoặc tracker qua callable đã đăng ký.
- **Nếu bỏ?** Không còn scheduler của framework đưa strategy/background job vào worker như demo.
- **Đọc trước?** execute:103 → run_strategy:53 → run_coroutine_task:69 → exit:78.

#### Strategy / EMAXOver — `lib/strategy.py:60–160`, `examples/sample_app/emaxover.py:19–59`

- **Tồn tại để làm gì?** Strategy quản lý loop/session; EMAXOver quyết định tín hiệu và nhịp gọi Trader.
- **Ai tạo?** Entry tạo subclass; subclass gọi constructor Strategy.
- **Ai gọi?** Bot initialize; Executor gọi run_strategy; live_strategy gọi dynamic-dispatch trade.
- **Giữ state gì?** symbol, parameters, name, running, sessions/current_session; EMAXOver thêm trader và Tracker.
- **Method quan trọng nhất?** live_strategy ở base; trade/find_entry ở subclass.
- **Gọi class nào tiếp?** Sessions, Symbol, TestTrader. Strategy base không tự instantiate Trader.
- **Nếu bỏ?** Không còn nơi biến dữ liệu thị trường thành lần gọi place_trade và lặp nó theo session.
- **Đọc trước?** Base run_strategy:128 → live_strategy:132 → subclass trade:52 → find_entry:26.

#### Trader / TestTrader — `lib/trader.py:30–185`, `examples/sample_app/traders/test_trader.py:11–49`

- **Tồn tại để làm gì?** Base cung cấp helper chuẩn bị/check/send/record; subclass quyết định orchestration cụ thể và bước sau kết quả.
- **Ai tạo?** EMAXOver tạo TestTrader; RibbonScalper tạo RSTrader; Chaos tạo ScalpTrader.
- **Ai gọi?** Subclass Strategy.trade gọi place_trade; place_trade gọi helper kế thừa.
- **Giữ state gì?** Config, Symbol, RAM, parameters, mutable Order, cờ _order_check_passed; TestTrader thêm Positions/Store.
- **Method quan trọng nhất?** place_trade ở subclass; send_order/check_order ở base.
- **Gọi class nào tiếp?** Symbol lấy tick, Order check/send, Result/TaskQueue record; TestTrader còn tạo OpenPosition.
- **Nếu bỏ?** Strategy phải tự thực hiện orchestration mà subclass đang giữ. Order vẫn có thể được caller khác gọi trực tiếp; đây không phải tầng bắt buộc cho mọi request.
- **Đọc trước?** TestTrader.place_trade:18 → Trader.__init__:30 → create_order_no_stops:112 → check_order:119 → send_order:134.

#### Order — `src/aiomql/lib/order.py:13–121`

- **Tồn tại để làm gì?** Giữ fields request, tạo dict hợp lệ theo native fields, bọc kết quả và cung cấp đường check/send.
- **Ai tạo?** Trader constructor/reset; các helper OpenPosition còn tự tạo Order riêng.
- **Ai gọi?** Trader; OpenPosition; Positions gọi thẳng classmethod send_order bằng dict khi đóng position.
- **Giữ state gì?** Fields TradeRequest và defaults DEAL/DAY/FOK; mt5/config là dependency cấp lớp được BaseMeta thiết lập.
- **Method quan trọng nhất?** send:62, send_order:71, request:102, check:54.
- **Gọi class nào tiếp?** Async MetaTrader; tạo aiomql OrderCheckResult/OrderSendResult từ raw native objects.
- **Nếu bỏ?** Caller phải tự tạo request dict và bọc result; wrapper MetaTrader vẫn tồn tại, không bị biến thành Trader.
- **Đọc trước?** send → check → request → send_order; phân biệt Order.send_order với Trader.send_order.

#### MetaTrader + MetaCore/MetaBase — `core/meta_trader.py:34–385`, `core/_core.py:296–311`

- **Tồn tại để làm gì?** Async façade cho API sync, preflight cuối và xử lý result không xác định; MetaBase nối tên `_...` tới callable của package.
- **Ai tạo?** Bot, Strategy và BaseMeta._setup của các lớp dùng _Base; không có singleton MetaTrader instance trong __new__ hiện tại.
- **Ai gọi?** Order/Symbol/Positions/Account và Bot. Chúng có thể giữ các wrapper instance khác nhau; không coi `Bot.mt5` là object duy nhất truyền xuyên mọi tầng.
- **Giữ state gì?** config cấp lớp, error và asyncio.Lock trên từng instance. `_handler` và order_send đã trace không acquire lock đó.
- **Method quan trọng nhất?** order_send:341 và _handler:59; metaclass __new__:299 giải thích native binding.
- **Gọi class nào tiếp?** Native callables lấy từ module MetaTrader5, qua to_thread cho đường async đã chỉ ra.
- **Nếu bỏ?** Các lib object mất façade đang await và chính sách normalize/preflight của wrapper; metaclass giải thích chỗ cuối cùng tới API.
- **Đọc trước?** order_send → _handler → order_check → _core.MetaBase.__new__; sau đó mới so startup sync/async.

#### Symbol / ForexSymbol — `lib/symbol.py:18–112,181–186`, `contrib/symbols/forex_symbol.py:6–27`

- **Tồn tại để làm gì?** Giữ metadata/limits và cung cấp market data; ForexSymbol thêm tính pip/volume.
- **Ai tạo?** Entry examples.
- **Ai gọi?** Strategy initialize/find_entry; Trader lấy tick và tính/kiểm volume.
- **Giữ state gì?** name, metadata SymbolInfo, initialized, tick, Account reference.
- **Method quan trọng nhất?** initialize[_sync], info_tick, copy_rates_from_pos.
- **Gọi class nào tiếp?** MetaTrader; bọc output thành Tick/Candles.
- **Nếu bỏ?** Strategy/Trader mất object chia sẻ dữ liệu và các helper đang gọi trực tiếp.
- **Đọc trước?** initialize_sync:89 → info_tick:31 → copy_rates_from_pos:181, chỉ mở bổ trợ theo call site trong lượt đọc đầu.

#### OpenPosition — `contrib/trackers/open_position.py:41–109,150–165,222–258,323–379`

- **Tồn tại để làm gì?** Quản lý một position snapshot cùng callback, pending orders và position liên quan.
- **Ai tạo?** TestTrader sau result DONE; helper hedge/stack có thể tạo các OpenPosition tiếp theo.
- **Ai gọi?** OpenPositionsTracker gọi track; callbacks gọi update/close/modify/hedge.
- **Giữ state gì?** Symbol, ticket, TradePosition, flags, _trackers, pending_orders/hedges/stacks và unresolved exposure attempts.
- **Method quan trọng nhất?** __post_init__, track, update_position; close_position dẫn ngược xuống gửi request.
- **Gọi class nào tiếp?** PositionTracker, Positions, Order, Config.state.
- **Nếu bỏ?** Send result vẫn nhận được, nhưng graph quản lý position/callback mà demo lắp không được tạo.
- **Đọc trước?** __post_init__:77 → track:323 → update_position:150 → remove_closed:96 → close_position:230.

#### PositionTracker — `contrib/trackers/position_trackers.py:17–48`

- **Tồn tại để làm gì?** Gắn function + params + rank với một OpenPosition.
- **Ai tạo?** OpenPosition.__post_init__ và TestTrader.place_trade.
- **Ai gọi?** Constructor gọi set_tracker; OpenPosition.track await tracker(), kích hoạt __call__.
- **Giữ state gì?** function, params, rank, name, open_position reference.
- **Method quan trọng nhất?** __call__:35, set_tracker:46.
- **Gọi class nào tiếp?** Callback được truyền vào; callback thường gọi OpenPosition. Constructor không tạo background Task.
- **Nếu bỏ?** Mất adapter và thứ tự callback gắn cho mỗi position.
- **Đọc trước?** __call__ → __init__ → set_tracker.

#### OpenPositionsTracker — `contrib/trackers/position_trackers.py:51–103`

- **Tồn tại để làm gì?** Poll các OpenPosition đã đăng ký trong State và await việc quản lý chúng.
- **Ai tạo?** x_bot dòng 17; __new__ thiết lập Config/Positions/State cấp lớp, nhưng mỗi lần vẫn trả một instance mới.
- **Ai gọi?** Executor.run_coroutine_task gọi bound track sau khi Bot đăng ký separate thread.
- **Giữ state gì?** interval, state_key, autocommit, auto_remove_closed; class references dùng chung.
- **Method quan trọng nhất?** track:78.
- **Gọi class nào tiếp?** State, OpenPosition.track; remove_closed_positions dùng Positions khi bật option.
- **Nếu bỏ?** Chỉ tạo OpenPosition/PositionTracker không đủ tự chạy polling quản lý position.
- **Đọc trước?** track → __init__ → __new__ → remove_closed_positions.

#### Config — `core/config.py:74–92,148–220`

- **Tồn tại để làm gì?** Chia sẻ cấu hình, flags, queue và state/store giữa các thành phần.
- **Ai tạo?** Lần gọi Config đầu tiên; các lần sau __new__ trả `_instance`.
- **Ai gọi?** Bot/Executor/Strategy/Trader/wrappers và các tracker.
- **Giữ state gì?** Startup credentials/path, shutdown/force_shutdown, record mode, TaskQueue, State, Store, bot reference.
- **Method quan trọng nhất?** __new__/__init__, load_config; init_state nối sang state tracking.
- **Gọi class nào tiếp?** TaskQueue, State, Store. Constructor có thể đọc config và tạo/nạp tài nguyên persistence.
- **Nếu bỏ?** Không còn shared control/resource object mà các lớp hiện truy cập.
- **Đọc trước?** __new__:74 → __init__:85; chỉ xem load_config/init_state khi cần hiểu ownership. Không import để “thăm dò” vì construction có side effect.

## 3. Order lifecycle

### 3.1. Một BUY trên tuyến EMAXOver/TestTrader

**VERIFIED — trace có điều kiện, không giả định tín hiệu hay fill đã xảy ra thực tế:**

```text
EMAXOver.find_entry():45–46
  fas.iloc[-1] truthy → tracker.update(order_type=OrderType.BUY, snooze=timeout)
EMAXOver.trade():58
  await TestTrader.place_trade(order_type=BUY, parameters=self.parameters)
TestTrader.place_trade():21–27
  parameters merge; default volume = symbol.volume_min * 20
  await Trader.create_order_no_stops(BUY, volume)
    await symbol.info_tick() → ask
    _set_order_volume(...) → self.order.volume
    self.order.price = tick.ask; self.order.type = BUY
  await Trader.check_order()
    await Order.check() → MetaTrader.order_check() → MT5.order_check [CHECK A]
  self.order.comment = parameters['name'] hoặc tên class
  await Trader.send_order()
    _set_order_volume(...) lần nữa
    await Order.send()
      snapshot request
      await Order.check(**request) → MT5.order_check [CHECK B]
      await Order.send_order(request=...)
        await MetaTrader.order_send(request)
          copy + validate volume theo symbol_info mới + normalize comment
          _handler(_order_check, retry_safe=False) → MT5.order_check [CHECK C]
          _handler(_order_send, retry_safe=False)
            await asyncio.to_thread(...) → MetaTrader5.order_send(request)
          raw result
        aiomql OrderSendResult(**raw._asdict())
    Trader phân nhánh retcode, trả result
TestTrader.place_trade():28–45
  nếu retcode == 10009:
    lấy TradePosition → tạo OpenPosition → đăng ký callback → đặt pending hedge/stack → record_trade
EMAXOver.trade():59
  delay; quay lại Strategy.live_strategy loop
```

Các method trong sơ đồ thuộc file/line trong bảng 2.2. `Order` ban đầu được tạo trong `Trader.__init__` trước khi signal xuất hiện, còn “create_order_no_stops” **điền lại object sẵn có**. Không có `Order.create()` mới trong mỗi lần gọi đó.

**VERIFIED — hiểu đúng ba lần check:**

| Check | Mục đích theo vị trí thực thi | Có thể dừng ở đâu? |
|---|---|---|
| A: Trader.check_order → Order.check | Check trước khi TestTrader thêm comment, set cờ trader | Nonzero retcode làm TestTrader return; raw None gây OrderError trong Order.check. |
| B: Order.send → Order.check | Check snapshot lấy khi send, có comment vừa đặt | Nonzero gây OrderError, chưa tới Order.send_order. |
| C: MetaTrader.order_send → `_handler(_order_check, retry_safe=False)` | Check dữ liệu cuối đã validate volume và chuẩn hóa comment, cho cả caller bỏ qua Order.send | Raw check thiếu/retcode sai kiểu/nonzero hoặc request bị đổi làm OrderError trước native send. |

Đây là ba **điểm gọi check** trên nhánh thường, không cam kết chỉ ba native check invocation khi có connection failure: wrapper order_check dùng `_handler` mặc định retry-safe; `_handler` có thể initialize/login và retry khi res=None với connection error (`meta_trader.py:59–82`). Final check C và native send đều truyền retry_safe=False.

### 3.2. Kết quả và nhánh dừng

**VERIFIED:**

- `retcode == 0` là điều kiện check mà code đòi hỏi; không được nhầm với `retcode == 10009` mà các trader dùng làm điều kiện gửi thành công.
- `Trader.send_order()` trả cả DONE_PARTIAL và retcode thất bại xác định cho caller (`trader.py:145–152`). Riêng TestTrader chỉ đi vào block tạo OpenPosition/record khi `res.retcode == 10009`. Không suy rằng partial fill được block này quản lý như full fill.
- `MetaTrader.order_send()` ném `OrderSendAmbiguous` nếu native send trả None, thiếu retcode, TIMEOUT/CONNECTION, hoặc exception/cancellation trong đoạn await submission (`meta_trader.py:376–384`). Không tự resend ở đây; `Order.send_order()` cũng không thực hiện connection_retries (`order.py:71–79`).
- TestTrader re-raise OrderSendAmbiguous (`test_trader.py:46–47`); Strategy.live_strategy đặt running=False rồi re-raise (`strategy.py:141–143`). Kết luận này là dừng strategy đó theo path đã trace, không phải đã chứng minh mọi background loop/toàn bot tự dừng ngay.
- Lỗi thông thường trong TestTrader.place_trade bị log/catch ở dòng 48–49; place_trade có thể hoàn tất mà không có trade. Vì vậy “await place_trade đã xong” không chứng minh order đã khớp.
- `Trader.record_trade()` có guard record_trades và DONE/DONE_PARTIAL; nó lấy expected profit và history order trước enqueue Result.save (`trader.py:154–176`). Tuy nhiên guard của **caller TestTrader** chỉ gọi nó sau DONE và sau các bước position/pending phía trước; không tự động ghi mọi result từ mọi call site.

### 3.3. Tuyến RibbonScalper/RSTrader và Chaos đang mở trong IDE

**VERIFIED — không gộp các subclass thành một lifecycle duy nhất:**

| Tuyến | Đường đi và khác biệt |
|---|---|
| RibbonScalper | `sample_app_2/bot.py:11–13` → `Strategy.live_strategy()` → `strategies/ribbon_scalper.py:48–57::trade()` → find_entry:25–46. BUY được set ở dòng 35–37 khi hai cross cùng truthy; trade truyền sl và pips_target cho RSTrader. |
| RSTrader | `sample_app_2/traders/rs_trader.py:21–35::place_trade()` đặt Order.type → await create_order:8–19 → await send_order → record khi 10009 → reset_order. create_order lấy RAM amount, tick, tính volume từ SL, gán sl/tp/volume/price. **Không gọi Trader.check_order() một cách tường minh** trong place_trade. |
| Check của RSTrader | Cờ _order_check_passed ban đầu chưa có; Trader.send_order chỉ chặn khi cờ là False. Sau đó Order.send vẫn check B và MetaTrader.order_send vẫn check C. Không được mô tả RSTrader là “không check”. |
| RAM amount của RSTrader | `lib/ram.py:44–52::get_amount()` dùng fixed_amount nếu có; nếu không await `Account.refresh()` (`lib/account.py:59–64`) → `MetaTrader.account_info()` (`core/meta_trader.py:154–158`) → _handler/to_thread → MT5.account_info; tính từ margin_free và risk. |
| Chaos | `contrib/strategies/chaos.py:28–32` tạo ScalpTrader; `trade():58–71` → check_trend:34–56; hướng BUY/SELL được chọn bằng random.choice tại dòng 49 sau khi lấy nến. `contrib/traders/scalp_trader.py:14–30` dùng create_order_no_stops → explicit check_order → comment → send_order → record_trade → reset_order. |
| Position continuation | Entry sample_app_2 và RSTrader không đăng ký OpenPositionsTracker/tạo OpenPosition trong các call site đã đọc. Chaos/ScalpTrader cũng không tự lắp phần này. Việc một tab tracker đang mở trong IDE không chứng minh runtime của RibbonScalper đi qua nó. |

**NOT VERIFIED:** các tín hiệu của những strategy trên có phát sinh đúng điều kiện trên dữ liệu/account thực tế hay không. Phần này chỉ xác minh đường gọi khi branch được chọn.

## 4. Async / thread / task boundaries

### 4.1. Sơ đồ concurrency

**VERIFIED — phân bố logic theo submit/asyncio.run/to_thread trong source; không gán thread ID cụ thể:**

```text
Caller thread của x_bot
  Bot.execute → initialize_sync
    MetaTrader.initialize_sync/login_sync       [SYNC native API trực tiếp]
    Symbol.initialize_sync                     [SYNC native API trực tiếp]
  Executor.execute                             [đồng bộ, giữ ThreadPoolExecutor context]
    |
    +-- pool worker S1: run_strategy(strategy_1)
    |      asyncio.run(...) → event loop L1
    |        await Strategy → await Trader → await Order → await MetaTrader
    |          await asyncio.to_thread(native_func, ...)
    |            └─ default-executor worker của L1 [SYNC MT5 callable]
    |        await result → tiếp tục coroutine ở L1
    |
    +-- pool worker S2 ...: strategy_2 → event loop L2 ...
    |
    +-- pool worker P: run_coroutine_task(OpenPositionsTracker.track)
    |      asyncio.run(...) → event loop LP
    |        sleep(interval) → await gather(pos.track() ...)
    |          mỗi pos: await callback 1 → callback 2 → ... theo rank
    |          API calls → to_thread → native workers của loop đó
    |
    +-- pool worker Q: run_coroutine_task(Config.task_queue.run)
    |      asyncio.run(...) → event loop LQ
    |        add_workers → asyncio.create_task(worker(...))
    |        await queue.join()
    |
    +-- pool worker E: Executor.exit()           [SYNC polling/time.sleep]
    |
    +-- pool worker G: asyncio.run(run_coroutine_tasks())
           await gather(coroutines đăng ký on_separate_thread=False)
```

L1/L2/LP/LQ là ký hiệu giải thích; source không đặt các tên này. Một future dài hạn được submit cho mỗi strategy, không có cam kết cố định OS thread ID ở tài liệu này. Native workers do `to_thread` sử dụng **không phải cùng pool object `Executor.executor`**: code không truyền pool đó vào `to_thread` hay set_default_executor trên các path đã trace.

### 4.2. Những boundary không nên đọc nhầm

**VERIFIED:**

1. `await trader.place_trade()` / `await order.send()` không tự tạo thread hay tách background task. Các coroutine nối tiếp trong event loop của strategy, đến `_handler` mới có native offload. `Strategy.live_strategy()` không tạo một task giao dịch độc lập cho mỗi signal.
2. `Executor.run_strategy()` dùng inspect.iscoroutinefunction để chọn `asyncio.run` hoặc gọi sync (`executor.py:53–58`). `Executor.execute()` cũng submit functions trực tiếp; `run_function()` có định nghĩa ở 74–76 nhưng không phải method được execute dùng ở dòng 110.
3. `Bot.start()` là async nhưng gọi `self.executor.execute()` đồng bộ sau await initialize (`bot.py:159–163`). Trong demo sample_app_2, event loop ngoài của `asyncio.run(rs_bot())` không trở thành loop chung cho các strategy, và lời gọi execute giữ caller cho tới khi phần executor hoàn tất.
4. `Bot.init_strategies()` dùng gather để concurrent initialize trên startup loop; nhánh initialize_sync lặp tuần tự. Đây khác với các strategy runtime loops sau đó.
5. `MetaTrader._handler():68` await to_thread với native callable sync. order_send giữ kết quả qua await rồi mới trả về Order. Không thấy tạo fire-and-forget task cho native order_send. Cancel await trong submission không chứng minh native worker/broker request bị hủy; code phản ánh điều này bằng OrderSendAmbiguous.
6. `MetaTrader.__init__():46` tạo asyncio.Lock nhưng những đường `_handler`/order_send đã trace không dùng `async with self._lock`. Không có bằng chứng cho một global lock tuần tự hóa tất cả MT5 calls trong tuyến này. Thread-safety thực tế của package/native terminal là NOT VERIFIED.
7. `OpenPositionsTracker.track():85` dùng gather để quản lý nhiều position cùng chu kỳ. **Trong một OpenPosition**, `track():326–327` await từng PositionTracker theo rank; constructor PositionTracker chỉ đăng ký, không create_task.
8. Executor.exit (`executor.py:78–101`) polling sync; khi thoát nó đặt strategy.running=False, gọi task_queue.cancel, executor.shutdown(wait=False,...). Không có explicit await từng future hoặc explicit MetaTrader.shutdown ở hai Bot.execute/start đã trace. Không coi đây là bằng chứng mọi resource đã được đóng đúng khi chạy thật.

### 4.3. TaskQueue: tạo task ở loop nào, chờ ở đâu?

**VERIFIED — nhánh record, không phải đường order_send:**

| Vị trí | Hành vi và lifetime |
|---|---|
| `core/config.py:80` | Tạo một TaskQueue(mode='infinite') dùng chung. Default max_workers=None (`task_queue.py:60–71`). |
| `lib/bot.py:112 hoặc 132` | Đăng ký queue.run separate thread. Không await queue.run trong từng trade. |
| `core/task_queue.py:204–217` | run thiết lập thời gian, có thể thêm dummy task/workers, rồi await queue.join. Dummy task await sleep 1 giây (154–156) để duy trì infinite mode. |
| `core/task_queue.py:174–186` | add_workers gọi asyncio.create_task(self.worker(...)); references nằm trong worker_tasks. **Task thuộc running event loop của chính caller add_workers.** |
| `lib/trader.py:173–174` → `core/task_queue.py:82–96` | record_trade gọi queue.add ngay ở loop đang thực hiện trade. add put_nowait, rồi khi max_workers=None có thể gọi add_workers ngay tại đó. Vì vậy không thể khẳng định mọi worker chỉ chạy ở LQ: nếu tạo worker từ add trên L1 thì worker đó ở L1. Có tạo thêm hay không phụ thuộc qsize và worker_tasks. |
| `core/task_queue.py:98–141` | worker lấy item bằng get_nowait, await item(), task_done. Infinite worker có thể tiếp tục phục vụ nhiều item; không kết thúc ngay sau một lần save. |
| `core/task_queue.py:40–53` | QueueItem.__call__: coroutine function thì await trực tiếp; sync function thì await loop.run_in_executor(None, partial(...)). `Result.save` là async function nên được await trong loop của worker, không tự offload. |
| `lib/result.py:49–60` | Dù là async def, save dùng threading.Lock và gọi to_csv/to_json/to_sql sync, không có await/to_thread trong thân. I/O này diễn ra ở worker event-loop thread. |
| `core/task_queue.py:210–211,188–202` | Nếu queue_timeout truthy thì create_task(watch()). Không có explicit await riêng cho watch tại call site; run đang await queue.join. Default timeout=0 nên nhánh này không tự bật trong hai demo. |
| `core/task_queue.py:238–248` | cancel đặt stop, shutdown queue immediate và cancel worker tasks. Executor.exit gọi method sync này từ worker của exit. |

**PARTIALLY VERIFIED:** thấy toàn bộ các điểm tạo task, enqueue và await ở trên; chưa chạy để quan sát worker nào thực sự lấy Result item khi có nhiều loop. Trên các file đã trace không thấy `call_soon_threadsafe` hoặc `run_coroutine_threadsafe` làm bridge riêng cho các thao tác queue này. Không xác nhận an toàn cross-thread/cross-loop, thứ tự save hay save completion lúc shutdown bằng phân tích tĩnh này.

**VERIFIED — async không đồng nghĩa offload:** `State.acommit()` (`core/state.py:188–196`) gọi json/sqlite đồng bộ trong async body, không có await/to_thread. Trong tracker LP, autocommit được await nhưng không chuyển sang I/O thread riêng. `MetaTrader.shutdown()` (`core/meta_trader.py:135–137`) cũng gọi `_shutdown()` trực tiếp; không được áp quy tắc “mọi async method wrapper đều dùng to_thread” cho nó.

**VERIFIED — process boundary không nằm trong hai demo:** `Bot.process_pool()` (`lib/bot.py:75–81`) có ProcessPoolExecutor và submit callable được truyền vào, nhưng không được x_bot/rs_bot gọi. Không thêm process layer vào sơ đồ runtime chính.

## 5. Position/tracker continuation

### 5.1. Ai phát hiện position và ai bắt đầu quản lý?

**VERIFIED — nhánh sau DONE, với điều kiện position/state setup và các lời gọi tiếp theo không ném lỗi:**

| Bước / exact file:line | Caller → callee / vai trò |
|---|---|
| `examples/sample_app/traders/test_trader.py:28–31` | TestTrader đọc `res.retcode==10009`; await Positions.get_position_by_ticket(ticket=res.order); tự tạo OpenPosition với cùng Symbol, ticket, snapshot và flags đóng hedges/stacks. |
| `src/aiomql/lib/positions.py:40–43,23–37` | get_position_by_ticket → get_positions(ticket=...) → await MetaTrader.positions_get; bọc raw tuples thành TradePosition và đối chiếu ticket phần tử đầu. |
| `src/aiomql/core/meta_trader.py:393–398` | positions_get → _handler với `_positions_get` → to_thread → `MetaTrader5.positions_get`. Đây là query/poll, không có broker push callback trong tuyến đã trace. |
| `src/aiomql/contrib/trackers/open_position.py:77–87` | Dataclass gọi __post_init__: state.setdefault('tracked_positions',{}).setdefault(ticket,self); thêm default remove_closed rank 1 và check_pending_orders rank 2. Đăng ký không đồng nghĩa callback đã chạy. |
| `src/aiomql/contrib/trackers/position_trackers.py:25–48` | PositionTracker.__init__ → set_tracker → OpenPosition.add_tracker; giữ function/params và gán rank nếu thiếu. |
| `examples/sample_app/traders/test_trader.py:32–36` | Thêm hedge_position, track_hedges, close_after(duration=3600,start=...), exit_at_profit(tp=10,sl=-12) vào chính OpenPosition. |
| `examples/sample_app/traders/test_trader.py:37–44` | Await profit_to_price cho -8/+7, round_off; await hedge_order và stack_order. **Demo này còn đặt lệnh pending tiếp theo ngay sau market order**, không chỉ đăng ký tracker rồi quay về. |
| `src/aiomql/contrib/trackers/open_position.py:381–441` | hedge_order/stack_order tạo Order(action=PENDING,...), gọi _send_exposure_order → Order.send; DONE thì lưu PendingOrder vào pending_orders. Các kết quả bất thường được xử lý theo nhánh source; không giả định hai pending orders đều thành công. |
| `src/aiomql/contrib/trackers/open_position.py:345–379` | _send_exposure_order chốt unresolved_hedge/stack trước await, giữ request/result/error cho lần gửi; chặn lặp cùng kind khi chưa resolved. Chỉ cần biết guard này ảnh hưởng khả năng callback gửi tiếp; không mở rộng sang hệ thống recovery/reconciliation. |
| `examples/sample_app/traders/test_trader.py:45` | record_trade cho **market result res ban đầu**, nằm sau các bước trên. Không phải tự ghi riêng mỗi pending helper qua Trader.record_trade. |

**PARTIALLY VERIFIED:** source demo sử dụng `res.order` làm position ticket và truyền kết quả query vào OpenPosition; chưa xác minh broker/account thực tế có position tương ứng ngay lúc query. Không thay điều kiện này bằng khẳng định “gửi thành công thì chắc chắn đã tạo được manager”.

### 5.2. Vòng background và đường đóng position

**VERIFIED — call chain tiếp diễn:**

```text
x_bot():17 → Bot.add_coroutine(... separate_thread=True)
  → Executor.run_coroutine_task():69–71 → asyncio.run(OpenPositionsTracker.track())
  → position_trackers.py::OpenPositionsTracker.track():78–97
      connection = config.state.conn
      while not config.shutdown:
        await sleep(interval=10 mặc định)
        state.get('tracked_positions', {})
        await gather(pos.track() cho các position đã đăng ký)
          → open_position.py::OpenPosition.track():323–331
            → trackers property:90–93 [sort rank]
            → await PositionTracker.__call__():35–44 từng callback
              → await function(open_position, **params)
        autocommit=True trong x_bot → await state.acommit(conn, close=False)
```

Tracker tổng không tự động biến tất cả position của tài khoản thành OpenPosition. `track()` đọc mapping được đăng ký. `remove_closed_positions()` (`position_trackers.py:99–103`) có query toàn bộ positions để lọc mapping khi `auto_remove_closed=True`; default False trong demo. `track()` hiện đọc literal `"tracked_positions"` ở dòng 84; không giả định mọi truy cập đều lấy từ option state_key.

**VERIFIED — một callback đóng BUY theo profit:**

```text
PositionTracker.__call__()
 → contrib/trackers/position_tracking_functions.py::exit_at_profit():10–21
   → await OpenPosition.update_position():150–165
     → Positions.get_position_by_ticket → MetaTrader.positions_get → MT5.positions_get
   → profit >= tp hoặc profit <= sl
   → await OpenPosition.close_position():230–258
     → lib/positions.py::Positions.close_position():78–91
       request = DEAL, position=ticket, type=position.type.opposite,
                 volume=position.volume, price=position.price_current, symbol=...
       → Order.send_order(request=req):71–79 [classmethod trực tiếp]
         → MetaTrader.order_send():341–385 [vẫn có final native check]
           → to_thread(_order_send) → MetaTrader5.order_send
     → nếu ok: is_open=False; closures theo flags; remove_from_state()
```

Đường close này **không đi qua Trader.send_order, Order.send hoặc Order.check**; nó vẫn qua kiểm tra cuối trong MetaTrader.order_send. Vì thế không dùng một sơ đồ mở order duy nhất cho tất cả request execution.

**VERIFIED — callback khác trực tiếp được demo gắn:**

- `examples/sample_app/trackers/track.py:10–20::close_after()` update_position, so thời lượng rồi close_position.
- `track.py:23–34::hedge_position()` update position, nếu đủ điều kiện thì gọi OpenPosition.hedge_position (`open_position.py:447–484`) → `_send_exposure_order` → Order.send → wrapper/native. `track_hedges():37–50` update các hedge rồi có thể close_position.
- Default `OpenPosition.remove_closed():96–113` poll trạng thái, đóng pending/hedges/stacks theo flags rồi chuyển object từ tracked sang archived bằng `remove_from_state():222–228`.
- Default `check_pending_orders():312–321` gather từng `check_pending_order():288–309`; query theo pending result.order, khi tìm được position thì tạo OpenPosition con và bỏ pending entry tương ứng.
- `extend_take_profit()` (`position_tracking_functions.py:24–38`) là extension callback đã đọc: update_position → có thể modify_stops → Order(action=SLTP).send (`open_position.py:167–220`). **Không thấy demo chính đăng ký callback này**; không vẽ nó như tác vụ chắc chắn đang chạy.

**VERIFIED — Strategy tiếp tục gì?** Sau place_trade hoàn tất, EMAXOver chỉ delay rồi lặp tiếp; không giữ OpenPosition reference để tự quản lý trong trade. Logic quản lý position đã được demo giao cho State + background tracker. `Strategy.tracker` chỉ giữ tín hiệu/snooze; `PositionTracker` là callback quản lý position; `OpenPositionsTracker` là vòng tổng chạy chúng.

**NOT VERIFIED:** việc polling/commit state/serialize OpenPosition và các callback thực sự hoạt động đến hết trên cấu hình mặc định hoặc account của người dùng. Đây là điểm kết thúc bằng chứng source, không phải xác nhận demo đã chạy thành công. Không audit/sửa persistence trong lượt này.

## 6. Execution file map

**VERIFIED — bản đồ theo vai trò của tuyến đã trace; không phải yêu cầu đọc tất cả file trong một buổi:**

| Nhóm | File chính xác | Phần tham gia execution |
|---|---|---|
| App composition | `examples/sample_app/bot.py` | x_bot, tạo/đăng ký strategy và tracker, gọi execute. |
| Signal | `examples/sample_app/emaxover.py` | EMAXOver construction, find_entry, trade. |
| Custom orchestration | `examples/sample_app/traders/test_trader.py` | Chuẩn bị/check/send market order, tạo manager và đăng ký callbacks/pending. Đây là example dù tên là TestTrader, không phải test được chạy trong phiên này. |
| Startup | `src/aiomql/lib/bot.py` | Bot, initialize/start, chuyển sang Executor. |
| Scheduling | `src/aiomql/lib/executor.py` | Thread pool, per-runner event loop, background registration, exit. |
| Strategy lifecycle | `src/aiomql/lib/strategy.py` | run_strategy/live_strategy, sessions, sleep/delay, trade extension. |
| Order preparation | `src/aiomql/lib/trader.py` | Mutable Order, volume, check/send, record. |
| Request façade | `src/aiomql/lib/order.py` | request property, check/send/send_order, model conversion. |
| Async/native boundary | `src/aiomql/core/meta_trader.py` | initialize/login, market queries, final preflight, to_thread, ambiguous outcome. |
| Native binding | `src/aiomql/core/_core.py` | MetaBase/MetaCore và mapping `_name` → MetaTrader5.name. |
| Position manager | `src/aiomql/contrib/trackers/open_position.py` | Register manager/default callbacks, track/update/close và pending helpers. |
| Tracker dispatch | `src/aiomql/contrib/trackers/position_trackers.py` | PositionTracker adapter; OpenPositionsTracker polling/gather. |
| Data/limits support | `src/aiomql/lib/symbol.py`; `src/aiomql/contrib/symbols/forex_symbol.py`; `src/aiomql/core/base.py`; `src/aiomql/core/models.py`; `src/aiomql/core/volume.py` | Symbol initialization/tick/candles, BaseMeta dependencies, request/result/position models và validation; mở theo call site khi cần. |
| Runtime support | `src/aiomql/lib/sessions.py`; `src/aiomql/core/config.py`; `src/aiomql/core/task_queue.py`; `src/aiomql/core/state.py`; `src/aiomql/lib/result.py` | Session gate, shared resources/flags, queue record, state registration/commit và Result.save. Dừng ở ranh giới cần cho execution, không nghiên cứu DB business. |
| Callback support | `src/aiomql/contrib/trackers/position_tracking_functions.py`; `examples/sample_app/trackers/track.py`; `src/aiomql/core/utils.py` | exit_at_profit, close_after/hedge/track_hedges, sleep. |
| Signal state support | `src/aiomql/contrib/utils/strategy_tracker.py` | Tracker alias giữ order_type/snooze, không quản lý vị thế. |
| Variant trong IDE | `examples/sample_app_2/bot.py`; `examples/sample_app_2/strategies/ribbon_scalper.py`; `examples/sample_app_2/traders/rs_trader.py` | Async startup, Ribbon signal, risk-based sizing và send/record/reset. |
| Variant contrib | `src/aiomql/contrib/strategies/chaos.py`; `src/aiomql/contrib/traders/scalp_trader.py` | Random direction signal; no-stops trader có explicit check. |

**VERIFIED — ranh giới sync riêng:** repo có `src/aiomql/core/sync/meta_trader.py` với sync `_handler` gọi `func(*args, **kwargs)` trực tiếp ở dòng 53–62; export là MetaTraderSync (`core/sync/__init__.py:1`). BaseMeta chọn wrapper đó khi lớp có mode sync. Tuyến examples đang dùng Strategy/Order/ForexSymbol async, dù entry dùng Bot.execute sync. Nhánh OrderSync/StrategySync không được trace toàn bộ; **PARTIALLY VERIFIED** đối với flow sync độc lập.

### Notes / Out of Scope

**VERIFIED về phạm vi phiên làm việc:** chỉ đọc điểm gọi State/Result/Store cần giải thích execution. Không nghiên cứu Deal Ledger, Deal Ingestion, billing, recovery/reconciliation, Phase 3, dashboard hoặc licensing. Những từ xuất hiện trong comment/exception của execution không làm mở rộng phạm vi. Không chuyển các nhận xét về request/check/queue thành audit bug hoặc kế hoạch sửa code.

## 7. My reading path

**INFERENCE — lộ trình 12 file, dựa trên quan hệ VERIFIED ở phần 2–6.** Đây là thứ tự mở IDE cho các buổi đọc sau; không phải buổi walkthrough chi tiết đã bắt đầu thay người đọc. Những file support chỉ cần nhảy tới method được dẫn khi đang đọc, không thêm thành 20–30 bài bắt buộc.

```text
lib/bot.py → examples/sample_app/bot.py → lib/executor.py → lib/strategy.py
 → examples/sample_app/emaxover.py → examples/sample_app/traders/test_trader.py
 → lib/trader.py → lib/order.py → core/meta_trader.py → core/_core.py
 → contrib/trackers/open_position.py → contrib/trackers/position_trackers.py
```

Path viết tắt trong sơ đồ tương ứng exact path dưới đây.

### File 1 — `src/aiomql/lib/bot.py`

- **Tại sao đọc:** cửa nối ngắn giữa initialize và runtime, giúp định vị toàn tuyến.
- **Class trước:** Bot.
- **Methods theo thứ tự:** execute:153 → __init__:66 → add_strategies:169/add_strategy:165 → initialize_sync:123 → start_terminal_sync:93 → init_strategies_sync:198/init_strategy_sync:191 → start:159 và initialize:103 để so nhánh async.
- **Chú ý:** Bot giữ instance đã được app tạo; initialized/login khác với strategy.running; execute/start đều đi tới sync executor.execute.
- **Sau file này phải hiểu:** điều kiện strategy được đưa vào Executor và những gì chạy trước đó.
- **File tiếp theo nối vì:** example bot cho thấy ai tạo instance và gọi các API vừa đọc.

### File 2 — `examples/sample_app/bot.py`

- **Tại sao đọc:** entry nhỏ, thấy composition thực của một app.
- **Class trước:** không có class; đọc module guard và x_bot.
- **Methods/functions theo thứ tự:** guard:22–23 → x_bot:10–19; dừng ở construction/registration, chưa nhảy sang mọi helper.
- **Chú ý:** symbol → strategy → trader/order được tạo trước Bot; add_coroutine truyền bound callable track, không phải task đã chạy.
- **Sau file này phải hiểu:** nguồn gốc năm strategy instances và nơi bật background tracker.
- **File tiếp theo nối vì:** bot.execute cuối cùng gọi Executor.execute để chạy những thứ vừa đăng ký.

### File 3 — `src/aiomql/lib/executor.py`

- **Tại sao đọc:** hiểu thread/event-loop ownership trước khi theo await chain.
- **Class trước:** Executor.
- **Methods theo thứ tự:** execute:103 → run_strategy:53 → run_coroutine_task:69 → run_coroutine_tasks:60 → add_strategy:48/add_coroutine:36 → exit:78.
- **Chú ý:** ThreadPoolExecutor là một lớp khác với TaskQueue workers; mỗi asyncio.run tạo phạm vi loop riêng. execute submit hàm trực tiếp, không dùng run_function tại call site đó.
- **Sau file này phải hiểu:** strategy và tracker chạy từ đâu, caller Bot bị giữ ở đâu, exit quan sát cờ nào.
- **File tiếp theo nối vì:** run_strategy gọi strategy.run_strategy, method thực nằm ở Strategy base.

### File 4 — `src/aiomql/lib/strategy.py`

- **Tại sao đọc:** loop nền mà mọi subclass trong report dùng.
- **Class trước:** Strategy.
- **Methods theo thứ tự:** run_strategy:128 → live_strategy:132 → __aenter__:88/__aexit__:94 → initialize:105/initialize_sync:109 → __init__:60 → sleep:120/delay:124 → trade:158.
- **Chú ý:** dynamic dispatch self.trade; session check trước trade; OrderSendAmbiguous dừng runner; đọc thân method thay vì suy từ docstring.
- **Sau file này phải hiểu:** ai gọi trade lặp lại và điều kiện chưa tới trader hoặc thoát loop.
- **File tiếp theo nối vì:** EMAXOver cung cấp đúng trade mà base gọi.

### File 5 — `examples/sample_app/emaxover.py`

- **Tại sao đọc:** bridge từ market data/signal sang trader cụ thể.
- **Class trước:** EMAXOver.
- **Methods theo thứ tự:** __init__:19 → trade:52 → find_entry:26.
- **Chú ý:** tracker ở đây là StrategyTracker alias; điều kiện source dùng above/below ở nến cuối, không tự thay nó bằng một định nghĩa tín hiệu khác theo mô tả comment.
- **Sau file này phải hiểu:** lúc nào BUY được gán, lúc nào place_trade được gọi và parameters nào được truyền.
- **File tiếp theo nối vì:** constructor chọn TestTrader và trade gọi place_trade của lớp đó.

### File 6 — `examples/sample_app/traders/test_trader.py`

- **Tại sao đọc:** orchestration cụ thể trước và sau native send.
- **Class trước:** TestTrader.
- **Methods theo thứ tự:** __init__:12 → place_trade:18; chia hai khối 21–27 (gửi) và 28–45 (continuation).
- **Chú ý:** explicit check trước comment; DONE gate; còn pending hedge/stack trước record; không return res cho Strategy; không reset_order tại đây.
- **Sau file này phải hiểu:** helper nào kế thừa và chính lớp này lắp position management ở đâu.
- **File tiếp theo nối vì:** create_order_no_stops/check_order/send_order/record_trade nằm ở Trader base.

### File 7 — `src/aiomql/lib/trader.py`

- **Tại sao đọc:** chuyển signal args thành mutable Order và xử lý send result.
- **Class trước:** Trader.
- **Methods theo thứ tự:** __init__:30 → create_order_no_stops:112 → _set_order_volume:38 → check_order:119 → send_order:134 → record_trade:155 → reset_order:178.
- **Chú ý:** Order được tạo sớm; check gate khác send retcode gate; record enqueue là nhánh sau send, không phải nơi gọi order_send.
- **Sau file này phải hiểu:** fields ai điền, check flag dùng ra sao, caller nào có quyền đọc result.
- **File tiếp theo nối vì:** Trader chỉ gọi Order.check/send; phải theo xuống lớp đó để thấy request/API.

### File 8 — `src/aiomql/lib/order.py`

- **Tại sao đọc:** request dict và các tầng check/send có tên gần nhau.
- **Class trước:** Order.
- **Methods theo thứ tự:** send:62 → check:54 → request:102 → send_order:71 → __init__:15; calc_profit:88/get_history_order_by_ticket:117 chỉ để hiểu record branch.
- **Chú ý:** send là instance method có check; send_order là classmethod nhận dict; BaseMeta thiết lập mt5 ở core/base.py:21–32; request model và dict không cùng object.
- **Sau file này phải hiểu:** snapshot nào rời lib, raw result được bọc ở đâu, direct-send caller khác đường thường ở điểm nào.
- **File tiếp theo nối vì:** lời gọi cuối của Order là cls.mt5.order_send/request check trên async wrapper.

### File 9 — `src/aiomql/core/meta_trader.py`

- **Tại sao đọc:** final preflight và điểm offload thật sự xuống package.
- **Class trước:** MetaTrader.
- **Methods theo thứ tự:** order_send:341 → _handler:59 → order_check:331 → symbol_info:179 → positions_get:393 → initialize:101/initialize_sync:118 và login:84/login_sync:92.
- **Chú ý:** copy/normalize/validate, retry_safe=False cho final check/send, ambiguous exception boundary; _lock tồn tại không chứng minh mọi call đã serialize.
- **Sau file này phải hiểu:** coroutine đợi native worker ở đâu và kết quả xác định/không xác định quay lên thế nào.
- **File tiếp theo nối vì:** self._order_send không có def Python tại đây; phải xem metaclass binding.

### File 10 — `src/aiomql/core/_core.py`

- **Tại sao đọc:** xác nhận cạnh cuối tới MetaTrader5, tránh dừng ở tên wrapper.
- **Class trước:** MetaBase, rồi MetaCore.
- **Methods/khối theo thứ tự:** MetaBase.__new__:299–308 → core_mt5_functions:247–280 → types:281–293 → MetaCore:311. Không đọc hàng trăm constants không cần cho tuyến.
- **Chú ý:** dictionary lấy từ module MetaTrader5; `_order_send` là reference native callable được gắn vào class khi tạo class, không phải wrapper method bị thiếu file.
- **Sau file này phải hiểu:** tại sao _handler(func=self._order_send) chính là native API call và chỗ nào vượt ngoài source repo.
- **File tiếp theo nối vì:** quay lên nhánh sau DONE trong TestTrader, mở manager OpenPosition để hiểu trade còn tiếp tục ra sao.

### File 11 — `src/aiomql/contrib/trackers/open_position.py`

- **Tại sao đọc:** manager dài hạn sau khi nhận send result.
- **Class trước:** OpenPosition; PendingOrder/ExposureAttempt chỉ đọc fields khi method tham chiếu.
- **Methods theo thứ tự:** __post_init__:77 → track:323 → trackers:90/add_tracker:84 → update_position:150 → remove_closed:96 → close_position:230/remove_from_state:222 → check_pending_orders:312/check_pending_order:288. hedge_order:381/stack_order:412 và _send_exposure_order:345 đọc sau phần manager cơ bản.
- **Chú ý:** class này không tự có vòng background riêng; state giữ reference; một manager await callback theo rank; gọi close có thể xuống Order.send_order qua Positions.
- **Sau file này phải hiểu:** registration khác scheduling, TradePosition snapshot khác manager, callback có thể tạo request execution mới.
- **File tiếp theo nối vì:** PositionTracker định nghĩa cách gọi callback; OpenPositionsTracker là vòng thật sự gọi manager.track.

### File 12 — `src/aiomql/contrib/trackers/position_trackers.py`

- **Tại sao đọc:** hoàn tất graph background và nối lại app.add_coroutine.
- **Class trước:** OpenPositionsTracker để thấy vòng tổng, sau đó PositionTracker.
- **Methods theo thứ tự:** OpenPositionsTracker.track:78 → __init__:70/__new__:57 → PositionTracker.__call__:35 → __init__:25/set_tracker:46 → remove_closed_positions:99 nếu cần option đó.
- **Chú ý:** gather giữa managers, await tuần tự callback trong manager; polling chỉ trên tracked mapping; callback exit_at_profit ở file đang mở trong IDE là lần nhảy bổ trợ ngắn.
- **Sau file này phải hiểu:** ai làm tracker chạy, lifetime của background loop và đường callback xuống order_send.
- **File tiếp theo nối vì:** đã xong tuyến chính; buổi mở rộng có thể so `examples/sample_app_2/traders/rs_trader.py` với TestTrader, hoặc xem `position_tracking_functions.py::exit_at_profit` để trace một close. Không tự bắt đầu hai buổi đó ở phiên này.

## 8. Best starting points

### A. Điểm tốt nhất để HỌC code

**INFERENCE:** `src/aiomql/lib/bot.py`, class **Bot**, method **execute() dòng 153**. Method ngắn cho thấy thứ tự bắt buộc initialize_sync → shutdown gate → Executor.execute. Sau đó mới đọc construction và caller demo, để có khung gắn các class vào. README đã đặt Current Reading Position tại đây; chưa đánh dấu bạn đã đọc riêng Bot/Executor/Strategy.

### B. Điểm tốt nhất để TRACE một trade

**INFERENCE — các vị trí đặt breakpoint/log thủ công ở một buổi sau, không thêm log trong phiên này:**

| Muốn quan sát | Vị trí nên bắt đầu, dựa trên call site VERIFIED |
|---|---|
| BUY decision và args | `examples/sample_app/emaxover.py:46` và `:58`, EMAXOver.find_entry/trade. Nếu dùng Ribbon demo: `ribbon_scalper.py:36,52`. |
| Điểm vào orchestration một order | `examples/sample_app/traders/test_trader.py:23–27`, TestTrader.place_trade. Với app_2: `rs_trader.py:24–28`. Đây là breakpoint đầu tiên hữu ích nếu signal đã biết. |
| Fields/volume và check cờ | `src/aiomql/lib/trader.py:119,139–140`, Trader.check_order/send_order. |
| Request snapshot và thêm check | `src/aiomql/lib/order.py:64–68,76`, Order.send/send_order. |
| Request thật sau normalize | `src/aiomql/core/meta_trader.py:366–378`, MetaTrader.order_send. Phân biệt request của caller và final dict ở wrapper. |
| Async/native boundary | `src/aiomql/core/meta_trader.py:68`, MetaTrader._handler; quan sát func identity/args, không nhầm các symbol_info/check calls với _order_send. |
| Result đọc bởi custom code | `examples/sample_app/traders/test_trader.py:28–31`; raw result trước model conversion ở `lib/order.py:76–79`. |
| Continuation sau send | `position_trackers.py:85`, `open_position.py:326–327`, `position_tracking_functions.py:15–16`. Đây là loop khác với strategy. |

### C. Điểm tốt nhất để SAU NÀY chỉnh execution behavior

**INFERENCE — chỉ xác định trách nhiệm/extension points, không có implementation hay thay đổi trong lượt này:**

- Signal, thời điểm vào lệnh và nhịp gọi: subclass `Strategy.trade()/find_entry()` — EMAXOver/RibbonScalper/Chaos.
- Cách chuẩn bị request và orchestration trước/sau trade: subclass `Trader.place_trade()` — TestTrader/RSTrader/ScalpTrader; helper chung ở Trader.
- Request-level behavior chung cho instance order: `Order.request/check/send`; direct dict callers đi qua Order.send_order cần được nhận diện khi đọc.
- Quy tắc ngay trước native submission và xử lý raw outcome: `MetaTrader.order_send()`; điểm offload chung: `_handler()`. Đây là tầng ảnh hưởng nhiều caller, không chỉ một strategy.
- Lifecycle startup/registration: Bot; bố trí worker/loop: Executor.
- Quản lý sau fill: callback PositionTracker và methods OpenPosition; bật scheduling bằng app đăng ký OpenPositionsTracker.track.

## 9. Những điểm execution chưa xác minh được

| Nhãn | Điều đã biết / giới hạn |
|---|---|
| NOT VERIFIED | Không biết launch command, terminal path, credentials, broker limits, account mode hoặc config thật người dùng đang dùng. Không mở dữ liệu nhạy cảm để suy đoán. |
| NOT FOUND | Không thấy production launcher riêng trong src/examples hoặc console entry ở pyproject. Không kết luận không có orchestration ngoài repo. |
| NOT VERIFIED | Không xác minh các demo chạy thành công end-to-end; không kiểm tra broker có khớp BUY, có trả position ngay hay signal có đúng trên dữ liệu live. |
| PARTIALLY VERIFIED | Native binding từ MetaBase tới MetaTrader5 đã thấy trực tiếp. Thân implementation compiled của package, IPC terminal và broker matching nằm ngoài source đã đọc. Dừng trace tại callable package. |
| PARTIALLY VERIFIED | Demo query position bằng res.order đã trace. Tính tương ứng ticket/order/deal/position trong mọi kiểu account và tình huống fill chưa được xác minh. |
| PARTIALLY VERIFIED | TaskQueue workers có thể được tạo từ caller loop khác với loop queue.run. Thấy tạo/enqueue/await trong source, chưa xác minh scheduling, cross-loop safety và shutdown completion thực tế. |
| NOT VERIFIED | State persistence/serialization/reload graph OpenPosition và callback; commit có thể ảnh hưởng khả năng đi tiếp, nhưng không chạy để kiểm tra và không audit/sửa cơ chế đó. |
| NOT VERIFIED | Thread-safety/serialization nội bộ MetaTrader5 và thứ tự xử lý nhiều native calls; wrapper lock không được dùng ở path đã trace không chứng minh native layer xử lý thế nào. |
| PARTIALLY VERIFIED | Executor.exit đặt flags và cancel queue đã trace; một strategy dừng không đồng nghĩa mọi background loop dừng. Không thấy explicit MetaTrader.shutdown trong Bot execute/start path; chưa xác minh full termination ở runtime. |
| PARTIALLY VERIFIED | Có sync-only wrappers và Executor hỗ trợ runner sync. Báo cáo chỉ đối chiếu nhận diện sync boundary; không trace toàn bộ StrategySync/TraderSync/OrderSync lifecycle. |

## 10. Skills used

Đã rà danh mục skills được expose trong môi trường trước khi phân tích source; không đọc toàn bộ hàng trăm SKILL.md chỉ vì chúng tồn tại. Không thấy skill riêng chuyên Python call-chain tutoring trong danh mục; các skill liên quan đã được đánh giá theo mục tiêu đọc code.

| Skill | Dùng ở đâu / quyết định |
|---|---|
| **Đã dùng: codebase-orientation** — `C:/Users/dquooc/.codex/skills/codex-proflead-codex-skills-library-skills-foundation-codebase-orientation-skill-md/SKILL.md` | Áp dụng bước tìm entry point/runtime paths, map modules có giới hạn, dẫn concrete paths/call sites, chọn reading path và điểm học đầu tiên. Các yêu cầu skill về chạy/test/debug local và suggested change được giới hạn bởi prompt: chỉ đọc, không chạy và không đề xuất implementation. |
| Đã đọc để đánh giá, **không áp dụng: architecture-review** — `C:/Users/dquooc/.codex/skills/codex-proflead-codex-skills-library-skills-architecture-architecture-review-skill-md/SKILL.md` | Mục tiêu skill là critique scalability/reliability/bottleneck và đề xuất cải tiến. Không phù hợp với execution tutoring read-only; không mở một architecture audit. |
| Đã đọc để đánh giá, **không áp dụng: debugging-checklist** — `C:/Users/dquooc/.codex/skills/codex-proflead-codex-skills-library-skills-foundation-debugging-checklist-skill-md/SKILL.md` | Workflow reproduce issue và thêm logs/breakpoints; không có bug report để reproduce và prompt cấm chạy/sửa. Chỉ cung cấp vị trí breakpoint tương lai theo yêu cầu người dùng, không thực hiện workflow debugging. |
| Có vẻ liên quan nhưng không dùng: diagnosing-bugs, bug-triage, code-review, codebase-design | Trọng tâm là chẩn đoán/review/design, không phải xác minh execution call chain hiện tại. Không đọc/apply thêm để tránh mở rộng phạm vi. |
| Không dùng: frontend/browser/MT5 runtime integrations, data/research skills | Không giúp bằng chứng source của nhiệm vụ này; không browse web, điều khiển terminal MT5 hay gọi API live. |

Không dùng sub-agent; task thực hiện bằng đọc/search trực tiếp. Không có skill nào được dùng làm lý do yêu cầu approval hoặc bỏ dở phần tài liệu.

## 11. Commands/searches đã dùng

Các command dưới là đọc/search; các path tương đối chạy từ `E:\BLC\Dev_AI_MT5`. Dấu `...` trong ví dụ vòng lặp chỉ thay danh sách file/range đã liệt kê, không phải đã chạy thêm một script runtime. Không có pytest, import aiomql, formatter, bot launch, MT5 calls, git add/commit/reset/restore/checkout/clean/stash/switch.

### 11.1. Đọc yêu cầu, skills và inventory

```powershell
Get-Content -LiteralPath 'C:\Users\dquooc\.codex\attachments\5fabc9cb-e85e-4ac5-8794-19ed7c3004b6\Pasted text.txt' -Raw
Get-Location
Get-ChildItem -Force -Name
Get-Item 'AGENTS.md','E:\BLC\AGENTS.md','E:\AGENTS.md' -ErrorAction SilentlyContinue
rg --files -g AGENTS.md -g '!node_modules' -g '!venv' -g '!.venv'
rg --files src examples docs .agents .codex -g AGENTS.md -g '!tmp*'
rg --files src examples docs .github -g AGENTS.md
rg --files src/aiomql examples | Select-Object -First 160
Get-ChildItem -LiteralPath docs/code-reading -ErrorAction SilentlyContinue
Test-Path -LiteralPath docs/code-reading/01-execution-flow-overview.md
Test-Path -LiteralPath docs/code-reading/README.md
rg -n 'AGENTS.md' .gitignore
```

Đọc ba SKILL.md bằng `Get-Content -LiteralPath '<exact path trong mục 10>' -Raw`. Không tìm thấy AGENTS.md trong root/ancestors được kiểm tra hoặc các cây source/example/docs/.github đã search. `.agents`, `.codex` không tồn tại trong workspace. Lần inventory rộng đầu tiên gặp Access denied ở các thư mục `tmp*` có sẵn; các lần search sau dùng thư mục mục tiêu. Không thay quyền và không mở rộng vào các thư mục đó.

### 11.2. Symbol/reference searches

Các searches thực hiện (các danh sách target đầy đủ được nhóm theo mục đích để dễ tái sử dụng):

```powershell
rg -n 'Bot\(|\.execute\(|\.start\(|if __name__|project.scripts' examples src/aiomql/lib/bot.py pyproject.toml README.md
rg -n 'Bot\(|bot\.start\(|bot\.execute\(|process_pool\(' src examples --glob '*.py' --glob '!ta_libs/**'
rg -n '\[project\.scripts\]|\[project\.entry-points' pyproject.toml
rg -n 'TradeResult|OrderRequest|class Position\b|Chaos\(' src/aiomql/lib src/aiomql/core src/aiomql/contrib examples README.md
rg -n 'class Tracker|Tracker' src/aiomql/contrib/utils
rg --files src/aiomql/contrib/utils
rg -n '^core_mt5_functions|^class Candles|^    def __init__|^    def rename|^    def ta_lib|^    def ta\b' src/aiomql/core/_core.py src/aiomql/lib/candle.py
rg -n '^class MetaTrader|^    def _handler|func\(\*args|^    def order_send|retry_safe=False' src/aiomql/core/sync/meta_trader.py
rg -n '^class OrderSendAmbiguous|^class OrderError|^    def __init__|10009|DONE_PARTIAL|TIMEOUT|CONNECTION' src/aiomql/core/exceptions.py src/aiomql/core/constants.py
```

Thêm các truy vấn `rg -n` theo nhóm sau:

- Pattern `^class |^    (async )?def |MetaTrader5|to_thread|create_task|Lock|_order_send|_handler|submission` trên `core/meta_trader.py`, `_core.py`, `base.py`, `config.py`, `task_queue.py`, `models.py`, `state.py`.
- Pattern `^class |^    (async )?def |create_task|gather|task_queue|State|Store` trên `contrib/trackers/open_position.py`; lần thử target `contrib/trackers/*.py` không được rg mở rộng trên Windows, đã dùng đọc file cụ thể thay thế.
- Pattern `^class |^    (async )?def |to_thread|create_task|gather|MetaTrader|order_send` trên `lib/symbol.py`, `contrib/symbols/forex_symbol.py`, `lib/sessions.py`, `lib/result.py`, `core/state.py`, `core/utils.py`, `utils/utils.py`, `contrib/traders/scalp_trader.py`, `core/volume.py`. Lần đoán path `contrib/utils/tracker.py` không tồn tại; đã tìm được alias trong `contrib/utils/__init__.py` và class ở `strategy_tracker.py`.
- Pattern `asyncio\.(create_task|run|to_thread)|run_in_executor|call_soon_threadsafe|run_coroutine_threadsafe|threading|ThreadPoolExecutor|ProcessPoolExecutor` trên Bot, Executor, Strategy, Trader, Order, core MetaTrader, TaskQueue, thư mục contrib/trackers và hai thư mục demo.
- Pattern `^class |^    (async )?def ` trên `core/sync/meta_trader.py`, `lib/sync/order.py` để nhận diện nhánh sync; không chạy chúng.
- Pattern `^def |^async def ` kết hợp class/Tracker/sleep/error_handler để tìm utility/volume symbols đã dẫn.

### 11.3. Source reads và line numbers

Đọc bằng `Get-Content -LiteralPath`, có lệnh đánh số dòng, không import module:

```powershell
$n=0
Get-Content -LiteralPath $p | ForEach-Object { $n++; '{0,4}: {1}' -f $n,$_ }

$lines=Get-Content -LiteralPath $p
for($n=$start;$n -le $end;$n++) { '{0,4}: {1}' -f $n,$lines[$n-1] }
```

File đọc toàn bộ hoặc các đoạn liên quan:

- Hai entry examples; EMAXOver/TestTrader và example trackers; RibbonScalper/RSTrader.
- `lib/bot.py`, `executor.py`, `strategy.py`, `trader.py`, `order.py`, `positions.py`, `ram.py`, `account.py`.
- `contrib/strategies/chaos.py`, `contrib/traders/scalp_trader.py`, `contrib/symbols/forex_symbol.py`, `contrib/utils/strategy_tracker.py`.
- `contrib/trackers/position_trackers.py`, `position_tracking_functions.py`; `open_position.py` các đoạn 1–114,150–259,288–442,447–523.
- `core/meta_trader.py` 1–148,243–251,331–398; `_core.py` 1–20,250–315; `core/base.py`, `config.py`, `task_queue.py`, `volume.py`, `exceptions.py`, `utils.py`.
- `core/models.py` 249–362; `core/state.py` 1–51,68–111,173–195; `lib/symbol.py` 1–113,135–145,181–187; `lib/sessions.py` 28–52,71–83,124–148,155–222; `lib/result.py` 1–74; `utils/utils.py` 45–65.
- Các exports `src/aiomql/__init__.py`, `core/__init__.py`, `core/sync/__init__.py`, `lib/__init__.py`, `lib/sync/__init__.py`, `contrib/__init__.py`, `contrib/strategies/__init__.py`, `contrib/trackers/__init__.py`, `contrib/utils/__init__.py`, hai init của sample_app/traders và sample_app/trackers.
- `Get-Content -LiteralPath pyproject.toml -TotalCount 160`; README chỉ search caller/example references, không dùng thay cho source.

### 11.4. Git và ghi tài liệu

```powershell
git status --short
git rev-parse HEAD
git status --short --untracked-files=no
git diff --stat
```

Đầu phiên đã có 6 tracked files modified và 2 test files untracked. `git diff --stat` trước ghi tài liệu: 6 files changed, 301 insertions(+), 22 deletions(-). Không đọc nội dung ledger/test diff để mở rộng phân tích. Warnings CRLF và inaccessible tmp directories là output đọc Git/search, không phải thao tác sửa line endings hoặc filesystem.

Tạo/cập nhật tài liệu bằng `apply_patch`, chỉ hai path được ủy quyền: `docs/code-reading/01-execution-flow-overview.md` và `docs/code-reading/README.md`. Kiểm tra sau ghi bằng đọc Markdown, search headings, đối chiếu line references và Git status/diff stat. Không chạy test để kiểm tra tài liệu.

## Next Reading Session

**INFERENCE — kế hoạch bắt đầu phiên học tiếp theo; các vị trí method đã VERIFIED trong source:**

1. **File đầu tiên:** `E:\BLC\Dev_AI_MT5\src\aiomql\lib\bot.py`.
2. **Class đầu tiên:** `Bot` (class declaration dòng 18).
3. **Method đầu tiên:** `Bot.execute()` (dòng 153–157).
4. **Vì sao bắt đầu ở đây:** nhìn được initialize_sync chạy trước, shutdown gate ở giữa, executor.execute chạy sau; đây là khung ngắn nhất để gắn startup và runtime vào đúng chỗ.
5. **Trong cùng file đọc tiếp:** `__init__:66–73` → `add_strategies:169–171`/`add_strategy:165–167` → `initialize_sync:123–141` → `start_terminal_sync:93–101` → `init_strategies_sync:198–200`/`init_strategy_sync:191–196`. Cuối cùng so `start:159–163`, `initialize:103–121`, `init_strategy:179–184`, `init_strategies:186–189`. Chưa cần process_pool hoặc toàn bộ helper khác.
6. **File tiếp theo:** `E:\BLC\Dev_AI_MT5\examples\sample_app\bot.py`, function `x_bot():10–19`, xem guard ở 22–23. File này cho caller cụ thể của Bot; sau đó tới `src/aiomql/lib/executor.py::Executor.execute():103` như reading path.
7. **Điều phải hiểu trước khi chuyển file:** ai tạo Bot khác với ai tạo Strategy; add_strategies chỉ lưu object; initialization thành công mới đăng ký runner; Bot.execute chưa trực tiếp gọi Strategy.trade; vì sao “entry sync” vẫn chạy strategy async sau khi vào Executor. Có thể tự vẽ `app → Bot.execute → initialize_sync → init_strategy_sync → Executor.execute`, kèm chỗ terminal/symbol gọi native API trước runtime.

Dừng phiên hiện tại sau khi lưu report và README. Chưa bắt đầu buổi giải thích chi tiết Bot.execute thay người đọc.
