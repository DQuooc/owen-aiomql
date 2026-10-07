# 1. Executive Summary

Kết luận bắt buộc: **B. Repo phù hợp làm TRADING CORE, nhưng phải xây thêm infrastructure/backend/billing bên ngoài và harden một số phần lõi trước khi chạy tiền thật.**

Đánh giá tổng thể: **khoảng 36% nhu cầu sản phẩm**.

Các câu trả lời quan trọng nhất:

- Repo **có thể lấy Deal thực tế** từ MT5 qua `history_deals_get()` và model `TradeDeal` có đủ `ticket`, `order`, `position_id`, `volume`, `price`, `time`, `entry`, `type`, `magic`, `comment`... tại [TradeDeal](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:363) và [MetaTrader.history_deals_get](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:398).
- Repo **chưa có billing-per-deal**. `ResultDB` lưu một dòng theo `order`, không lưu immutable ledger cho từng Deal; `deal` không unique và không có account/server tại [ResultDB](E:/BLC/Dev_AI_MT5/src/aiomql/lib/result_db.py:10).
- Partial fill hiện bị xử lý sai: `DONE_PARTIAL` tồn tại nhưng mọi `retcode != 10009` bị coi là thất bại, và `record_trade()` bỏ qua tại [Trader.send_order](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trader.py:114).
- Không an toàn để chạy nhiều account trong cùng process: API MT5 được bind từ module global, trong khi `Config`, `Account`, `State`, `TaskQueue` là shared/singleton và không có khóa account-session hiệu lực.
- Không có restart recovery/reconciliation đáng tin cậy.
- Không thể dùng client API hiện tại để tự trừ trực tiếp MT5 trading balance của khách.
- Không nên chạy live như hiện tại.

Phạm vi xác minh:

- Không sửa, không tạo file và không chạy lệnh giao dịch.
- Không chạy test vì fixture tự động đăng nhập MT5 thật và teardown đóng toàn bộ position hiện tại tại [tests/live/conftest.py:25](E:/BLC/Dev_AI_MT5/tests/live/conftest.py:25) và [tests/live/conftest.py:46](E:/BLC/Dev_AI_MT5/tests/live/conftest.py:46).
- Codex Security deep-scan plugin không được cài; phần security dưới đây là static source audit.
- Thread-safety bên trong native extension `MetaTrader5` và hành vi broker cụ thể là **CHƯA XÁC MINH** từ repository này.

# 2. Architecture thực tế

## Sơ đồ đã hiệu chỉnh

```text
Application / Example
  ├─ tạo Symbol
  ├─ tạo concrete Strategy
  │    └─ tự chọn concrete Trader
  └─ tạo Bot
       ├─ Config singleton
       │    ├─ State singleton -> JSON blob trong SQLite
       │    ├─ Store -> SQLite key/value
       │    └─ TaskQueue singleton
       ├─ MetaTrader facade
       ├─ Executor
       └─ strategies[]

Bot.initialize()
  ├─ MetaTrader.initialize()
  ├─ MetaTrader.login()
  ├─ initialize Symbols/Strategies
  ├─ đăng ký TaskQueue.run
  └─ đăng ký Executor.exit

Executor ThreadPoolExecutor
  ├─ Strategy thread 1
  │    └─ asyncio.run(strategy.run_strategy())
  ├─ Strategy thread 2
  │    └─ asyncio.run(strategy.run_strategy())
  ├─ TaskQueue thread
  │    └─ asyncio.run(TaskQueue.run())
  ├─ optional Tracker thread
  │    └─ asyncio.run(OpenPositionsTracker.track())
  ├─ auxiliary coroutine thread
  └─ exit-monitor thread

Strategy event loop
  └─ Sessions.check()
       └─ Strategy.trade()
            └─ concrete Trader
                 ├─ RAM (tùy đường tạo order)
                 ├─ Symbol lot calculation
                 └─ Order.check()/Order.send()
                      └─ MetaTrader._handler()
                           └─ asyncio.to_thread()
                                └─ MetaTrader5 module function
                                     └─ MT5 terminal

Response:
MT5 OrderSendResult
  → aiomql OrderSendResult
  → chỉ khi concrete Trader gọi record_trade()
  → Result
  → TaskQueue hoặc save trực tiếp
  → CSV / JSON / ResultDB SQLite

TradeRecords:
job thủ công riêng
  → history_deals_get()
  → cập nhật trạng thái đóng của Result cũ
```

## Kiểm tra các mũi tên ban đầu

- `Application → Bot`: đúng, ví dụ tại [sample_app/bot.py:10](E:/BLC/Dev_AI_MT5/examples/sample_app/bot.py:10).
- `Bot → Config/Executor`: đúng tại [Bot.__init__](E:/BLC/Dev_AI_MT5/src/aiomql/lib/bot.py:66).
- `Bot → State/Store/TaskQueue`: đúng gián tiếp; các thành phần này thuộc `Config`, không phải pipeline tuần tự của Bot, tại [Config.__new__](E:/BLC/Dev_AI_MT5/src/aiomql/core/config.py:74) và [Config.init_state](E:/BLC/Dev_AI_MT5/src/aiomql/core/config.py:214).
- `Bot → initialize/login MT5`: đúng tại [Bot.start_terminal](E:/BLC/Dev_AI_MT5/src/aiomql/lib/bot.py:83).
- `Bot → initialize Symbols`: đúng thông qua `Strategy.initialize()` tại [Bot.init_strategies](E:/BLC/Dev_AI_MT5/src/aiomql/lib/bot.py:179).
- `Executor → Strategy thread → asyncio.run()`: đúng cho async Strategy tại [Executor.run_strategy](E:/BLC/Dev_AI_MT5/src/aiomql/lib/executor.py:52).
- `Strategy Loop → Sessions → trade()`: đúng tại [Strategy.live_strategy](E:/BLC/Dev_AI_MT5/src/aiomql/lib/strategy.py:129).
- `trade() → Trader → RAM`: không bắt buộc. Concrete Strategy tự chọn Trader; RAM chỉ tham gia những đường position-sizing theo risk. `create_order_no_stops()` không dùng RAM tại [Trader.create_order_no_stops](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trader.py:95).
- `Order.check() → Order.send()`: không luôn đúng. `RSTrader` gửi thẳng mà không check tại [RSTrader.place_trade](E:/BLC/Dev_AI_MT5/examples/sample_app_2/traders/rs_trader.py:20).
- `MetaTrader._handler() → asyncio.to_thread()`: đúng với phần lớn async MT5 calls tại [MetaTrader._handler](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:56). Sync wrapper gọi native API trực tiếp.
- `MT5 Result → TaskQueue → persistence`: chỉ đúng khi concrete Trader chủ động gọi `record_trade()`. `SimpleTrader` không gọi; `ScalpTrader` có gọi tại [scalp_trader.py:13](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/traders/scalp_trader.py:13).

## Vai trò các thành phần

| Thành phần | Vai trò thực tế |
|---|---|
| `Bot` | Orchestrator: kết nối terminal, khởi tạo Strategy, đăng ký queue và chạy Executor. [Bot.initialize](E:/BLC/Dev_AI_MT5/src/aiomql/lib/bot.py:103) |
| `Config` | Singleton/service locator toàn process cho credentials, DB, shutdown flags, Bot, State, Store, TaskQueue. [Config.__new__](E:/BLC/Dev_AI_MT5/src/aiomql/core/config.py:74) |
| `State` | Singleton dict trong RAM, persist toàn bộ dưới một JSON blob trong SQLite. [State.load](E:/BLC/Dev_AI_MT5/src/aiomql/core/state.py:124) |
| `Store` | SQLite key/value mapping; không phải execution ledger. [Store](E:/BLC/Dev_AI_MT5/src/aiomql/core/store.py:15) |
| `Executor` | Một `ThreadPoolExecutor` điều phối strategy, queue, tracker, function. [Executor.execute](E:/BLC/Dev_AI_MT5/src/aiomql/lib/executor.py:103) |
| `Strategy` | Template cho vòng lặp session-gated và abstract `trade()`. [Strategy.live_strategy](E:/BLC/Dev_AI_MT5/src/aiomql/lib/strategy.py:129) |
| `Sessions` | Chọn phiên UTC, sleep tới phiên tiếp theo và chạy hook đóng vị thế. [Sessions.check](E:/BLC/Dev_AI_MT5/src/aiomql/lib/sessions.py:192) |
| `Trader` | Chuẩn bị Order, gọi sizing, check/send và tùy chọn ghi Result. [Trader](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trader.py:20) |
| `RAM` | Tính số tiền risk từ free margin và chứa các primitive limit; các limit không được Trader tự động enforce. [RAM.get_amount](E:/BLC/Dev_AI_MT5/src/aiomql/lib/ram.py:44) |
| `Order` | Trade request builder và adapter cho order check/send/history/pending order. [Order](E:/BLC/Dev_AI_MT5/src/aiomql/lib/order.py:14) |
| `MetaTrader` | Async facade bọc các hàm module-level `MetaTrader5`; chủ yếu đưa call blocking sang `to_thread`. [MetaTrader](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:31) |
| `TaskQueue` | Priority queue in-memory cho tác vụ best-effort. Không durable, không retry/DLQ. [TaskQueue](E:/BLC/Dev_AI_MT5/src/aiomql/core/task_queue.py:55) |
| `Result` | Persistence DTO của một `OrderSendResult`, không phải Deal ledger. [Result.get_data](E:/BLC/Dev_AI_MT5/src/aiomql/lib/result.py:43) |
| `ResultDB` | SQLite model một row/order; `order` là primary key. [ResultDB](E:/BLC/Dev_AI_MT5/src/aiomql/lib/result_db.py:10) |
| `TradeRecords` | Utility chạy riêng để cập nhật profit/closed từ closing deals. Không được Bot tự chạy. [TradeRecords.update_sql_records](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trade_records.py:37) |
| `Symbol` | Broker symbol metadata, tick, candles, order book và interface sizing. [Symbol.initialize](E:/BLC/Dev_AI_MT5/src/aiomql/lib/symbol.py:62) |

# 3. Trade Flow

Concrete flow rõ nhất là `RibbonScalper`:

1. `RibbonScalper.find_entry()` tải candle, tính EMA, xác định BUY/SELL và SL tại [ribbon_scalper.py:25](E:/BLC/Dev_AI_MT5/examples/sample_app_2/strategies/ribbon_scalper.py:25).
2. `RibbonScalper.trade()` gọi `RSTrader.place_trade()` tại [ribbon_scalper.py:48](E:/BLC/Dev_AI_MT5/examples/sample_app_2/strategies/ribbon_scalper.py:48).
3. `RSTrader.create_order()` gọi `RAM.get_amount()` tại [rs_trader.py:8](E:/BLC/Dev_AI_MT5/examples/sample_app_2/traders/rs_trader.py:8).
4. `RAM.get_amount()` refresh account rồi tính:

   ```text
   amount_to_risk = margin_free × risk_percent / 100
   ```

   tại [ram.py:44](E:/BLC/Dev_AI_MT5/src/aiomql/lib/ram.py:44).

5. Lot không do RAM trực tiếp tính. `ForexSymbol.compute_volume_sl()` tính:

   ```text
   volume = amount / (abs(entry_price - sl) × trade_contract_size)
   ```

   tại [forex_symbol.py:24](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/symbols/forex_symbol.py:24).

6. Giá lấy từ tick; SL đến từ Strategy; TP được Trader tính và gán cùng volume/price vào `Order`.
7. `Order.request` lọc các field khớp native `TradeRequest` tại [Order.request](E:/BLC/Dev_AI_MT5/src/aiomql/lib/order.py:98).
8. `Trader.send_order()` gọi `Order.send()` tại [trader.py:114](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trader.py:114).
9. `Order.send_order()` gọi `MetaTrader.order_send()` và wrap native result thành `aiomql.core.models.OrderSendResult` tại [order.py:68](E:/BLC/Dev_AI_MT5/src/aiomql/lib/order.py:68).
10. `MetaTrader.order_send()` gọi `_handler()` tại [meta_trader.py:335](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:335).
11. `_handler()` chạy `MetaTrader5.order_send` trong worker thread qua `asyncio.to_thread()` tại [meta_trader.py:56](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:56).
12. Native callable được lấy trực tiếp từ module `MetaTrader5` bởi `MetaBase` tại [_core.py:296](E:/BLC/Dev_AI_MT5/src/aiomql/core/_core.py:296).

## Request và response

| Dữ liệu | Nằm ở đâu |
|---|---|
| Requested volume | `TradeRequest.volume`; [models.py:249](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:249) |
| SL/TP | Trader tính rồi gán vào Order; [trader.py:68](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trader.py:68) |
| Request gửi MT5 | `Order.request`; [order.py:98](E:/BLC/Dev_AI_MT5/src/aiomql/lib/order.py:98) |
| Check API | Native `MetaTrader5.order_check`; [meta_trader.py:325](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:325) |
| Send API | Native `MetaTrader5.order_send`; [meta_trader.py:335](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:335) |
| Send response | `OrderSendResult`: `deal`, `order`, `volume`, `price`, request ID... [models.py:305](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:305) |
| Position ID | Không có field trực tiếp trong `OrderSendResult`; code thường giả định `result.order` là position ticket |
| Historical position mapping | `TradeOrder.position_id`, `TradeDeal.position_id`; [models.py:221](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:221), [models.py:363](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:363) |

## Các lỗi đã xác minh trong trade flow

- `RSTrader` không gọi `Order.check()` trước send.
- `Trader.check_order()` chỉ log khi `retcode != 0` nhưng vẫn trả object truthy; mẫu `if not await check_order()` không chặn invalid check tại [Trader.check_order](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trader.py:102).
- `Trader.create_order_with_stops()` thiếu `await` trước async `compute_volume_sl()`, có thể gán coroutine vào `volume`, tại [trader.py:57](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trader.py:57).
- `RSTrader` cộng TP lên trên entry cho cả BUY và SELL tại [rs_trader.py:15](E:/BLC/Dev_AI_MT5/examples/sample_app_2/traders/rs_trader.py:15).
- `RAM.check_open_positions()` và `check_losing_positions()` tồn tại nhưng không được base/concrete Trader tự động enforce.
- `Symbol.check_volume()` tồn tại nhưng các đường sizing không bắt buộc gọi nó; volume min/max không được enforce nhất quán.

# 4. Concurrency Model

```text
PROCESS P0
│
├─ Main/caller thread
│   ├─ optional caller EVENT LOOP
│   └─ Bot.initialize()
│        └─ asyncio.to_thread() → MT5 worker thread
│
└─ Executor ThreadPoolExecutor
    ├─ THREAD Strategy A
    │    └─ EVENT LOOP A via asyncio.run()
    │         └─ Strategy coroutine
    │              └─ asyncio.to_thread()
    │                   └─ default-executor WORKER THREAD
    │                        └─ MetaTrader5 global module API
    │
    ├─ THREAD Strategy B
    │    └─ EVENT LOOP B → to_thread workers → same MT5 module API
    │
    ├─ THREAD TaskQueue
    │    └─ EVENT LOOP Q → asyncio Tasks
    │
    ├─ optional THREAD OpenPositionsTracker
    │    └─ EVENT LOOP T → tracker coroutine → to_thread workers
    │
    ├─ THREAD auxiliary coroutines
    │    └─ EVENT LOOP C
    │
    └─ THREAD exit monitor

Optional only:
Parent → ProcessPoolExecutor → child process → its own Bot
```

## Trả lời trực tiếp

1. **Mỗi Strategy có thread riêng không?**  
   Có. Mỗi strategy được submit thành một long-running ThreadPool job tại [Executor.execute](E:/BLC/Dev_AI_MT5/src/aiomql/lib/executor.py:103).

2. **Mỗi async Strategy có event loop riêng qua `asyncio.run()` không?**  
   Có, tại [Executor.run_strategy](E:/BLC/Dev_AI_MT5/src/aiomql/lib/executor.py:52).

3. **TaskQueue chạy ở đâu?**  
   Bot đăng ký nó với `on_separate_thread=True`, nên có Executor thread và event loop riêng tại [Bot.initialize](E:/BLC/Dev_AI_MT5/src/aiomql/lib/bot.py:103).

4. **Tracker chạy ở đâu?**  
   `StrategyTracker` chỉ là dataclass, không có loop. `OpenPositionsTracker` không tự chạy; example đăng ký nó vào thread riêng tại [sample_app/bot.py:17](E:/BLC/Dev_AI_MT5/examples/sample_app/bot.py:17).

5. **Tracker có event loop riêng không?**  
   Chỉ khi được đăng ký `on_separate_thread=True`. Nếu không, nó chia sẻ auxiliary coroutine loop.

6. **Có shared mutable state giữa threads không?**  
   Có: `Config`, shutdown flags, credentials, TaskQueue, `State._data`, Store connection/cursor, singleton `Account`, class-level MT5 facade.

7. **MT5 API gọi trực tiếp hay qua `to_thread()`?**  
   Async wrapper chủ yếu qua `to_thread`; sync wrapper gọi trực tiếp. Async `shutdown()` là ngoại lệ, gọi `_shutdown()` trực tiếp tại [meta_trader.py:129](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:129).

8. **Có lock/semaphore/thread-safety mechanism không?**  
   Có vài lock cục bộ nhưng không bảo vệ account/session/API MT5:

   - `MetaTrader._lock` được tạo nhưng không dùng: [meta_trader.py:40](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:40).
   - `Result.lock` chỉ serialize save: [result.py:17](E:/BLC/Dev_AI_MT5/src/aiomql/lib/result.py:17).
   - `State._lock` chủ yếu chỉ dùng trong init.
   - `Store.lock` chỉ dùng ở `commit`, không bảo vệ mọi cursor operation.
   - Không có semaphore/rate limit/account-bound lock quanh `login/order_send`.

## Rủi ro queue/event-loop

`TaskQueue.add()` được gọi từ Strategy thread nhưng có thể tự gọi `asyncio.create_task()` trên loop của Strategy, dù queue runner thuộc loop Q tại [TaskQueue.add_workers](E:/BLC/Dev_AI_MT5/src/aiomql/core/task_queue.py:174). Do đó worker, queue và `worker_tasks` có thể bị dùng xuyên thread/loop mà không có `call_soon_threadsafe()`.

`asyncio.Queue` không phải cơ chế handoff cross-thread. Đây là rủi ro race/lifecycle thực tế.

# 5. Order / Deal / Position

| Khái niệm | Nghĩa trong repo | Field quan trọng |
|---|---|---|
| `Order` | Yêu cầu/lệnh broker; có thể pending, filled, canceled... | ticket, state, volume_initial/current, position_id |
| `Deal` | Một execution thực tế do broker khớp | ticket, order, position_id, volume, price, entry, time |
| `Position` | Exposure hiện tại sau một hoặc nhiều Deal | ticket, identifier, current volume, price, P/L |

Source models: [TradeOrder](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:221), [TradeDeal](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:363), [TradePosition](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:340).

## API wrapper map

| MT5 API | Wrapper |
|---|---|
| `order_check` | `MetaTrader.order_check()` → `Order.check()` |
| `order_send` | `MetaTrader.order_send()` → `Order.send_order()` |
| `orders_get` | `MetaTrader.orders_get()` → `Order.get_pending_orders()` |
| `positions_get` | `MetaTrader.positions_get()` → `Positions.get_positions()` |
| `history_orders_get` | `MetaTrader.history_orders_get()` → `History.get_orders()` |
| `history_deals_get` | `MetaTrader.history_deals_get()` → `History.get_deals()` |

Các wrapper nằm tại [meta_trader.py:283](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:283) đến [meta_trader.py:416](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:416).

Tài liệu chính thức xác nhận `history_deals_get(ticket=...)` lọc theo **order ticket/DEAL_ORDER** và trả các Deal liên quan: [MetaQuotes history_deals_get](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py).

Có defect trong helper `History.get_deal_by_ticket()`:

- Nó gọi `history_deals_get(ticket=ticket)`, vốn nhận order ticket.
- Sau đó lại kiểm tra `deal.ticket == ticket`, tức coi input là deal ticket.
- Source: [History.get_deal_by_ticket](E:/BLC/Dev_AI_MT5/src/aiomql/lib/history.py:73).

Không nên dùng helper này làm nền tảng idempotency.

## Edge cases

| Case | Raw API/model | Xử lý hiện tại |
|---|---|---|
| Partial fill | Có `DONE_PARTIAL`, Deal volume | Bị coi là thất bại và không record |
| Một Order → nhiều Deal | API có thể trả tuple Deal theo order | ResultDB chỉ một row/order |
| Partial close | Low-level close cho phép truyền volume | Tracker/reconciliation không tổng hợp đúng |
| Scale in | Có `stack_position`/`stack_order` | Không có Deal ledger |
| Scale out | Có thể dùng generic close volume nhỏ | `TradeRecords` có thể mark closed quá sớm |
| Reverse | Có `DEAL_ENTRY_INOUT` | Không có processing |
| Close-by | Có `DEAL_ENTRY_OUT_BY` | Không có processing |
| Hedging | Có helper hedge/tracked child positions | Không kiểm tra account mode |
| Netting | Model có margin mode | Không có branch logic; nhiều giả định ticket không an toàn |

`TradeRecords` làm mất multi-deal vì tạo `{position_id: deal}`, khiến các Deal cùng position overwrite nhau tại [trade_records.py:44](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trade_records.py:44). Nó cũng đặt `closed=True` sau một `OUT`, kể cả partial close.

# 6. Capability Matrix

| Capability | Status | Source Evidence | Ghi chú |
|---|---|---|---|
| MT5 initialize | ✅ Có và tương đối hoàn chỉnh | [MetaTrader.initialize](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:95) | Có path/login/server/timeout |
| MT5 login | ✅ Có và tương đối hoàn chỉnh | [MetaTrader.login](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:78) | Nhưng session global |
| Shutdown | ⚠️ Có nhưng cần nâng cấp | [MetaTrader.shutdown](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:129) | Bot/Executor không gọi trong normal exit |
| Reconnect | ⚠️ Có nhưng cần nâng cấp | [MetaTrader._handler](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:56) | Có nguy cơ resend order |
| Retry | ⚠️ Có nhưng cần nâng cấp | [Order.send_order](E:/BLC/Dev_AI_MT5/src/aiomql/lib/order.py:68) | Không idempotent |
| Error handling | ⚠️ Có nhưng cần nâng cấp | [errors.py](E:/BLC/Dev_AI_MT5/src/aiomql/core/errors.py:4) | Nhiều nơi catch/log rồi bỏ qua |
| Symbol info | ✅ Có và tương đối hoàn chỉnh | [Symbol.initialize](E:/BLC/Dev_AI_MT5/src/aiomql/lib/symbol.py:62) | Metadata/tick/order book |
| Ticks | ✅ Có và tương đối hoàn chỉnh | [Symbol.copy_ticks_from](E:/BLC/Dev_AI_MT5/src/aiomql/lib/symbol.py:199) | From/range |
| Candles/rates | ✅ Có và tương đối hoàn chỉnh | [Symbol.copy_rates_from](E:/BLC/Dev_AI_MT5/src/aiomql/lib/symbol.py:174) | From/pos/range |
| Strategy engine | ⚠️ Có nhưng cần nâng cấp | [Strategy](E:/BLC/Dev_AI_MT5/src/aiomql/lib/strategy.py:18) | Thread-per-strategy, shared MT5 |
| Strategy loop | ⚠️ Có nhưng cần nâng cấp | [Strategy.live_strategy](E:/BLC/Dev_AI_MT5/src/aiomql/lib/strategy.py:129) | Một exception dừng strategy |
| Sessions | ✅ Có và tương đối hoàn chỉnh | [Sessions.check](E:/BLC/Dev_AI_MT5/src/aiomql/lib/sessions.py:192) | UTC session hooks |
| Scheduling | ⚠️ Có nhưng cần nâng cấp | [Sessions.find_next](E:/BLC/Dev_AI_MT5/src/aiomql/lib/sessions.py:171) | Không durable scheduler |
| Risk management | ⚠️ Có nhưng cần nâng cấp | [RAM](E:/BLC/Dev_AI_MT5/src/aiomql/lib/ram.py:7) | Primitive, chưa enforce |
| Position sizing | ⚠️ Có nhưng cần nâng cấp | [RAM.get_amount](E:/BLC/Dev_AI_MT5/src/aiomql/lib/ram.py:44) | Dựa trên free margin |
| Lot calculation | ⚠️ Có nhưng cần nâng cấp | [ForexSymbol.compute_volume_sl](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/symbols/forex_symbol.py:24) | Thiếu kiểm soát min/max nhất quán |
| Market order | ✅ Có và tương đối hoàn chỉnh | [Order.__init__](E:/BLC/Dev_AI_MT5/src/aiomql/lib/order.py:16) | Default `TRADE_ACTION_DEAL` |
| Pending order | ⚠️ Có nhưng cần nâng cấp | [OpenPosition.hedge_order](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/trackers/open_position.py:291) | Tracking có assumption ticket |
| Order check | ⚠️ Có nhưng cần nâng cấp | [Order.check](E:/BLC/Dev_AI_MT5/src/aiomql/lib/order.py:55) | Trader không chặn retcode lỗi |
| Order send | ⚠️ Có nhưng cần nâng cấp | [Order.send_order](E:/BLC/Dev_AI_MT5/src/aiomql/lib/order.py:68) | Ambiguous retry/partial fill |
| Stop loss | ⚠️ Có nhưng cần nâng cấp | [Trader.create_order_with_sl](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trader.py:68) | Có lỗi ở một số alternate paths |
| Take profit | ⚠️ Có nhưng cần nâng cấp | [Trader.set_trade_stop_levels_pips](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trader.py:35) | Sample SELL TP có lỗi |
| Modify pending order | ⚠️ Có nhưng cần nâng cấp | [TradeAction.MODIFY](E:/BLC/Dev_AI_MT5/src/aiomql/core/constants.py:19) | Generic action, thiếu high-level workflow |
| Modify position | ⚠️ Có nhưng cần nâng cấp | [OpenPosition.modify_stops](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/trackers/open_position.py:139) | Có lỗi `is_short()` |
| Close position | ⚠️ Có nhưng cần nâng cấp | [Positions.close_position](E:/BLC/Dev_AI_MT5/src/aiomql/lib/positions.py:74) | Assumption history/ticket |
| Open-position tracking | ⚠️ Có nhưng cần nâng cấp | [OpenPositionsTracker.track](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/trackers/position_trackers.py:75) | Optional, state không recover tốt |
| Pending-order tracking | ⚠️ Có nhưng cần nâng cấp | [OpenPosition.check_pending_orders](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/trackers/open_position.py:261) | Poll position bằng order ticket |
| Deal tracking | ⚠️ Có nhưng cần nâng cấp | [History.get_deals](E:/BLC/Dev_AI_MT5/src/aiomql/lib/history.py:47) | Retrieval có, durable ledger không |
| Order history | ✅ Có và tương đối hoàn chỉnh | [History.get_orders](E:/BLC/Dev_AI_MT5/src/aiomql/lib/history.py:52) | Có time/order/position query |
| Deal history | ✅ Có và tương đối hoàn chỉnh | [MetaTrader.history_deals_get](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:398) | Có đủ raw Deal fields |
| General persistence | ⚠️ Có nhưng cần nâng cấp | [State.commit](E:/BLC/Dev_AI_MT5/src/aiomql/core/state.py:173) | Không phải execution ledger |
| CSV | ⚠️ Có nhưng cần nâng cấp | [Result.to_csv](E:/BLC/Dev_AI_MT5/src/aiomql/lib/result.py:75) | Rewrite toàn file |
| JSON | ⚠️ Có nhưng cần nâng cấp | [Result.to_json](E:/BLC/Dev_AI_MT5/src/aiomql/lib/result.py:108) | Append/rewrite, không atomic |
| SQLite | ⚠️ Có nhưng cần nâng cấp | [ResultDB](E:/BLC/Dev_AI_MT5/src/aiomql/lib/result_db.py:10) | Schema one-row-per-order |
| Logging | ⚠️ Có nhưng cần nâng cấp | [executor.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/executor.py:14) | Không structured/correlation/metrics |
| Backtesting | ❌ Không có | [Strategy.test](E:/BLC/Dev_AI_MT5/src/aiomql/lib/strategy.py:155) | Chỉ gọi `trade()` một lần |
| Demo trading | ⚠️ Có nhưng cần nâng cấp | [AccountInfo.trade_mode](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:33) | Theo credentials, không demo guard |
| Live trading | ⚠️ Có nhưng cần nâng cấp | [Bot.start_terminal](E:/BLC/Dev_AI_MT5/src/aiomql/lib/bot.py:83) | Có khả năng gửi lệnh thật nhưng chưa safe |
| Restart recovery | 🆕 Cần xây thêm | — | Không execution-intent/deal/billing recovery |
| Reconciliation | ⚠️ Có nhưng cần nâng cấp | [TradeRecords](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trade_records.py:18) | Chỉ utility hạn chế, không startup sync |
| Process isolation | ⚠️ Có nhưng cần nâng cấp | [Bot.process_pool](E:/BLC/Dev_AI_MT5/src/aiomql/lib/bot.py:75) | Generic primitive, không supervisor |
| Safe multi-account | 🆕 Cần xây thêm | — | Không an toàn trong cùng process |
| User/API backend | 🆕 Cần xây thêm | — | Không có tenant/auth/API |

# 7. Billing-per-lot Readiness

## Kết luận

Repo có đủ **raw data** để xây billing theo Deal, nhưng implementation billing hiện tại chưa đủ dùng production.

Luồng đúng nên là:

```text
MT5 account worker
  → history_deals_get() với overlap window
  → từng TradeDeal
  → INSERT Deal Ledger
       UNIQUE(mt5_account_id, deal_ticket)
  → trong cùng transaction tạo Billing Event/Outbox
  → billing consumer
  → fee = deal.volume × fee_rate_snapshot
  → wallet / invoice / receivable
```

Với ví dụ:

```text
Order request = 2.0
Deal A = 0.7
Deal B = 0.8
Deal C = 0.5

fee = (0.7 + 0.8 + 0.5) × 1 USD = 2.0 USD
```

Không tạo thêm fee từ `TradeRequest.volume=2.0`.

## Deal có đủ field không?

Có. `TradeDeal` chứa:

- `ticket`
- `order`
- `position_id`
- `symbol`
- `volume`
- `price`
- `time`, `time_msc`
- `entry`
- `type`
- `magic`
- `comment`
- thêm `commission`, `swap`, `profit`, `fee`, `reason`, `external_id`

Source: [TradeDeal](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:363).

Lưu ý `TradeDeal.fee` là fee do broker trả về trong history, không phải mặc nhiên là phí SaaS của bạn.

## Những gì còn thiếu

- Deal ledger immutable.
- Unique constraint theo account + deal.
- Watermark và overlap-window sync.
- Startup reconciliation.
- Periodic reconciliation.
- Billing-event/outbox table.
- Rate version/snapshot.
- Retry/DLQ.
- Refund/correction handling.
- Audit trail.
- Tenant/account attribution.

Khóa đề xuất:

```text
UNIQUE(mt5_account_id, deal_ticket)
```

Trong đó `mt5_account_id` ánh xạ bất biến tới broker/company, server và login. Nếu chưa có internal ID:

```text
UNIQUE(broker, server, login, deal_ticket)
```

Không dùng `order_ticket` vì một Order có thể sinh nhiều Deal. Không dùng `position_id` vì nhiều Deal có thể thuộc cùng Position.

## Partial fill/close/scale/reverse

Billing dựa trên từng unique Deal vẫn hoạt động cho hedging và netting, nhưng phải định nghĩa policy:

- Charge cả entry và exit hay chỉ entry?
- `DEAL_ENTRY_INOUT` tính toàn bộ executed volume hay cần phân bổ?
- Có charge Deal do SL/TP/stop-out không?
- Xử lý `BUY_CANCELED`/`SELL_CANCELED` và broker corrections như thế nào?
- `OUT_BY` có tính phí không?

Đây là **business policy CHƯA XÁC MINH**, không phải giới hạn dữ liệu của MT5.

## Có thể tự trừ trực tiếp MT5 balance không?

**Không thể bằng repo và MetaTrader5 client trading API hiện tại.**

- Repo chỉ expose trading/history/account functions tại [_core.py:247](E:/BLC/Dev_AI_MT5/src/aiomql/core/_core.py:247).
- Trade actions chỉ gồm market, pending, SL/TP, modify, remove, close-by tại [TradeAction](E:/BLC/Dev_AI_MT5/src/aiomql/core/constants.py:19).
- Tài liệu MetaQuotes cũng không có client action “debit balance”: [official trade actions](https://www.mql5.com/en/docs/constants/tradingconstants/enum_trade_request_actions).

Phân biệt:

- **MT5 trading balance:** sổ cái do broker quản lý.
- **Broker commission:** broker cấu hình phía server.
- **IB rebate:** thỏa thuận/thanh toán giữa broker và IB.
- **External billing:** hệ thống của bạn tạo receivable/payment.
- **Prepaid wallet:** trừ số dư trong ledger của sản phẩm.
- **Monthly invoice:** tổng hợp billing events theo kỳ.

Muốn tạo balance adjustment trong MT5 cần quyền/dealer/admin/manager API hoặc cấu hình commission của broker; capability broker-specific này **CHƯA XÁC MINH** và nằm ngoài repo.

# 8. Multi-account Analysis

## Trả lời trực tiếp

1. **MetaTrader5 Python API được dùng như global API không?**  
   Có. `MetaBase` lấy callable trực tiếp từ module `MetaTrader5` tại [_core.py:296](E:/BLC/Dev_AI_MT5/src/aiomql/core/_core.py:296).

2. **`initialize()` ảnh hưởng object hay process/module connection?**  
   Wrapper không có session handle per object. Nó gọi module-level `MetaTrader5.initialize()`, được MetaQuotes mô tả là thiết lập kết nối tới terminal: [official initialize docs](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py).

3. **`login()` ảnh hưởng từng instance không?**  
   Không có bằng chứng về per-instance isolation. Official example gọi `login(A)` rồi `login(B)` trên cùng module và account hiện tại trở thành B: [official login docs](https://www.mql5.com/en/docs/python_metatrader5/mt5login_py).

4. **Có thể tạo hai `MetaTrader` object rồi login hai account an toàn cùng process không?**  
   Không thể kết luận an toàn. Các object không giữ native session handle riêng.

5. **Hai thread login khác account có thể ghi đè không?**  
   Có rủi ro P0. Repo không serialize login/send và không verify current login trước send.

6. **Strategy A có thể gửi nhầm sang account B không?**  
   Có thể. Source không có account binding tại Order/Strategy level.

7. **`Bot.process_pool()` làm gì?**  
   Chỉ submit các callable vào `ProcessPoolExecutor` tại [Bot.process_pool](E:/BLC/Dev_AI_MT5/src/aiomql/lib/bot.py:75). Không enforce một account/process, không monitor Future, không restart worker.

8. **Repo có process-isolation architecture hoàn chỉnh không?**  
   Không. Chỉ có primitive tùy chọn.

## Kịch bản crossover

```text
Thread A: login(Account A)  → current account A
Thread B: login(Account B)  → current account B
Thread A: order_send()      → có thể gửi vào B
```

Account chính xác phụ thuộc timing/native implementation nên **CHƯA XÁC MINH** bằng stress test. Tuy nhiên repo chắc chắn không có:

- account-scoped session handle;
- lock bao quanh `login → verify → send`;
- kiểm tra `account_info().login` trước send;
- account ID trong Order/Result;
- fail-closed account routing.

Ngoài ra:

- `Config` là singleton và gán cả class attributes tại [config.py:74](E:/BLC/Dev_AI_MT5/src/aiomql/core/config.py:74).
- `Account` là singleton tại [account.py:21](E:/BLC/Dev_AI_MT5/src/aiomql/lib/account.py:21).
- `State` dùng singleton/class data tại [state.py:19](E:/BLC/Dev_AI_MT5/src/aiomql/core/state.py:19).
- Nếu terminal path không tồn tại, wrapper chuyển path thành rỗng và để package tự tìm terminal tại [meta_trader.py:95](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:95).

Kết luận kiến trúc:

```text
1 MT5 Account
    ↓
1 terminal executable/data directory riêng
    ↓
1 Worker Process
    ↓
1 aiomql Bot
    ↓
Central DB / Reconciler / Billing Service
```

Không chạy hai account trong cùng worker process.

# 9. Persistence & Recovery

## Hiện repo lưu gì?

| Thành phần | Lưu gì | Hạn chế |
|---|---|---|
| Memory | Strategy state, Tracker, current History, Config | Mất khi crash |
| `State` | Một JSON blob trong SQLite | Shared singleton, không execution-specific |
| `Store` | SQLite key/value | Không được trade flow dùng làm ledger |
| CSV | `Result` từ `OrderSendResult` | Append/rewrite, không idempotent |
| JSON | `Result` list | Rewrite toàn file |
| SQLite `ResultDB` | Một row/order | Không one-order-many-deals |
| `History` | Deals/orders trong object RAM | Không persist |
| `TradeRecords` | Update closed/profit cho Result | Job thủ công, làm mất multi-deal |

`OpenPosition.__post_init__()` đặt object `OpenPosition` vào State tại [open_position.py:61](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/trackers/open_position.py:61), nhưng `State.commit()` dùng `json.dumps()` tại [state.py:173](E:/BLC/Dev_AI_MT5/src/aiomql/core/state.py:173). Object này không có JSON serializer tương ứng; recovery tracker không đáng tin cậy.

## Sau crash/restart

- Bot biết Order nào đã gửi chưa? **Chỉ nếu Result kịp lưu; không đầy đủ.**
- Biết Position nào mở không? **Có thể query lại `positions_get()`, nhưng Bot không tự reconstruct/reconcile.**
- Biết Deal nào đã xử lý chưa? **Không.**
- Biết Deal nào đã billing chưa? **Không.**
- Có reconcile history tự động không? **Không.**
- Có startup watermark không? **Không.**

## TaskQueue có phù hợp cho billing không?

**Không.**

- In-memory `asyncio.PriorityQueue`: [task_queue.py:60](E:/BLC/Dev_AI_MT5/src/aiomql/core/task_queue.py:60).
- Không durable enqueue/ack.
- `QueueItem` catch và nuốt exception tại [task_queue.py:40](E:/BLC/Dev_AI_MT5/src/aiomql/core/task_queue.py:40).
- Worker vẫn gọi `task_done()`, nên failed billing có thể bị coi là hoàn tất.
- Không retry/backoff/DLQ.
- QueueFull chỉ log.
- Shutdown immediate và cancel workers tại [task_queue.py:238](E:/BLC/Dev_AI_MT5/src/aiomql/core/task_queue.py:238).
- Producer/worker có thể nằm trên nhiều event loop khác nhau.

TaskQueue chỉ phù hợp cho best-effort analytics. Billing cần:

```text
DB transaction:
  INSERT deal
  INSERT billing_event/outbox

Committed outbox
  → durable consumer
  → idempotent billing
  → retry/DLQ
```

## Trường hợp broker execute nhưng Python mất response

Luồng hiện tại:

```text
order_send()
→ broker execute thành công
→ response/IPC bị timeout hoặc mất
→ _handler thấy connection error
→ initialize/login lại
→ resend cùng request
→ có thể tạo duplicate order
```

Source retry tại [MetaTrader._handler](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:56) và retry thứ hai tại [Order.send_order](E:/BLC/Dev_AI_MT5/src/aiomql/lib/order.py:68).

Sau restart, history có thể chứa Deal thật, nhưng repo không tự tìm và liên kết nó với intent cũ.

P0 cần:

1. Persist order intent trước send.
2. Gắn stable correlation ID/magic/comment.
3. Đưa attempt vào trạng thái `SENDING/AMBIGUOUS/CONFIRMED`.
4. Khi outcome mơ hồ, query order/deal/position history trước khi resend.
5. Không blind retry `order_send`.

# 10. Production Risks

## Execution/reliability

- Partial fill `10010` bị bỏ qua dù constant có tồn tại tại [TradeRetcode.DONE_PARTIAL](E:/BLC/Dev_AI_MT5/src/aiomql/core/constants.py:414).
- Blind retry có thể tạo duplicate order.
- Không timeout/circuit breaker quanh từng business operation.
- Không rate limiting MT5 calls.
- Không startup reconciliation.
- Không graceful queue drain đáng tin cậy.
- Normal Bot exit không gọi `MetaTrader.shutdown()`.
- `Executor.exit()` có thể gọi `os._exit(1)` tại [executor.py:78](E:/BLC/Dev_AI_MT5/src/aiomql/lib/executor.py:78).

## State/thread safety

- Config/State/Account singleton guards tạo một `Lock()` mới ở mỗi `__new__`, nên không phải global construction lock thực sự.
- State mutations và commits không được khóa đầy đủ.
- Store chia sẻ SQLite cursor/connection với `check_same_thread=False` nhưng ordinary operations không được serialize.
- MetaTrader `_lock` không dùng.
- `self.error` trong MetaTrader có thể bị các concurrent call ghi đè.

## Security

- Credentials được đọc plaintext từ JSON tại [Config.load_config](E:/BLC/Dev_AI_MT5/src/aiomql/core/config.py:148).
- Không secret manager, tenant authorization hay audit log.
- `DB.get/filter/update()` dựng điều kiện SQL bằng interpolation tại [db.py:159](E:/BLC/Dev_AI_MT5/src/aiomql/core/db.py:159); đây là latent injection risk nếu sau này nhận SaaS input.
- `Result.name` được dùng tạo filename CSV/JSON mà không sanitize tại [result.py:23](E:/BLC/Dev_AI_MT5/src/aiomql/lib/result.py:23); đây là latent path risk nếu name do user kiểm soát.

## Testing/operations

- Toàn bộ test nằm dưới `tests/live`.
- Package fixture tự động login MT5.
- Teardown đóng mọi position trên current account mà không lọc magic/demo.
- Không có test cho account crossover, partial fill, response-loss, restart, duplicate billing hay history replay.
- Static source cho thấy một số test đã lệch API hiện tại.
- Không có CI, health/readiness check, metrics, alerting, supervisor, DB migrations hay backup workflow.

Trạng thái test passing: **CHƯA XÁC MINH**; không chạy là quyết định an toàn trong audit này.

# 11. Gap Analysis

| Requirement | Repo hiện tại | Thiếu gì | Priority |
|---|---|---|---|
| Execution engine | Có core send/check | Ambiguous-outcome protocol, safe retry, account verification | P0 |
| Risk management | RAM primitive | Enforce limit, exposure/account/symbol risk, kill switch | P0 |
| Deal tracking | Có history API/model | Durable Deal ledger và continuous ingest | P0 |
| Position tracking | Optional tracker | Netting/hedging-aware reconciliation | P0 |
| Persistence | State/CSV/JSON/SQLite | Transactional execution schema | P0 |
| Recovery | Gần như không có | Intent recovery, queue recovery, worker restart | P0 |
| Reconciliation | TradeRecords hạn chế | Startup/periodic sync, watermark, overlap | P0 |
| Multi-account | Unsafe same-process globals | Account-worker ownership boundary | P0 |
| Process isolation | Generic ProcessPool | Supervisor, account affinity, terminal path isolation | P0 |
| Database | SQLite primitives | Central schema, migrations, constraints, backups | P0 |
| Billing per lot | Chỉ có raw Deal fields | Deal→Billing event pipeline | P0 |
| Idempotency | `order` PK trong ResultDB | Unique account/deal và idempotent billing | P0 |
| Partial fill/close | Constants/models có | DONE_PARTIAL, multi-deal aggregation, INOUT/OUT_BY | P0 |
| Duplicate-order prevention | Không có | Persisted command/intent protocol | P0 |
| Security | Plain config, no tenant layer | Secrets, encryption, RBAC, audit, validation | P0 |
| Safe tests | Live tests nguy hiểm | Offline unit suite, demo allowlist, fault injection | P0 |
| User management | Không có | Tenant/user/account ownership/auth | P1 |
| API backend | Không có | Control plane/API/webhooks | P1 |
| Monitoring | Basic logs | Metrics, lag, reconciliation alert, tracing | P1 |
| Deployment | Không có | Service manager/container/CI/CD/health checks | P1 |
| Backtesting | Không có | Historical engine, deterministic clock/slippage model | P2 |

# 12. Điểm đánh giá

| Hạng mục | Điểm |
|---|---:|
| Trading execution | 6/10 |
| Market data | 8/10 |
| Strategy engine | 6/10 |
| Risk management | 4/10 |
| Order management | 5/10 |
| Deal tracking | 3/10 |
| Position tracking | 4/10 |
| Persistence | 3/10 |
| Recovery | 1/10 |
| Multi-account | 1/10 |
| Billing readiness | 3/10 |
| Production readiness | 2/10 |
| SaaS readiness | 1/10 |

Tổng: `47/130 ≈ 36%`.

Cách tính dùng trọng số bằng nhau cho 13 nhóm. Nếu tăng trọng số cho recovery, account isolation, billing và idempotency — các phần P0 của sản phẩm — tỷ lệ thực dụng trước khi live còn thấp hơn.

# 13. Kết luận A/B/C/D

**B. Repo phù hợp làm TRADING CORE nhưng phải xây thêm infrastructure/backend/billing bên ngoài.**

Lý do:

- Có lớp wrapper MT5 khá rộng.
- Có market data, Strategy, session, Trader, Order, risk-sizing primitive.
- Có thể truy xuất Deal thực tế với executed volume.
- Có đủ primitive để dùng làm lõi cho một worker single-account.

Nhưng “phù hợp làm core” không có nghĩa “được chạy live như hiện tại”. Trước live vẫn phải sửa/harden các P0 ngay trong execution core: partial fill, ambiguous retry, account isolation, queue lifecycle, reconciliation và test safety.

# 14. Top 10 Risks

1. **Account crossover** do MT5 module state cùng `Config`/`Account` singleton.
2. **Duplicate order** sau timeout hoặc mất response vì blind resend.
3. **Partial fill không được record**, dẫn tới mất giao dịch và billing thiếu.
4. **Duplicate billing** vì không có unique Deal ledger/idempotency.
5. **Không recover sau crash**, dù Deal đã tồn tại tại broker.
6. **TaskQueue mất hoặc nuốt billing job**, đồng thời dùng queue xuyên event loop/thread.
7. **Netting/hedging/partial-close bị mô hình hóa sai**, đặc biệt giả định `result.order == position.ticket`.
8. **State và DB trộn giữa account/bot**, cùng các race trên singleton/shared SQLite state.
9. **Live test có thể mở lệnh và đóng toàn bộ position thật**.
10. **Thiếu security/observability/supervision/graceful shutdown**, khiến lỗi production khó phát hiện và phục hồi.

# 15. Source-code Learning Path

1. [examples/sample_app_2/bot.py](E:/BLC/Dev_AI_MT5/examples/sample_app_2/bot.py:7)
   - Class: không có; entry `rs_bot`.
   - Method quan trọng: `rs_bot()`.
   - File này làm gì: tạo Bot, Symbol và Strategy.
   - Tại sao cần đọc: thấy entry point tối thiểu.
   - Đọc tiếp: `src/aiomql/lib/bot.py`.

2. [src/aiomql/lib/bot.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/bot.py:18)
   - Class: `Bot`.
   - Method quan trọng: `start_terminal`, `initialize`, `start`, `execute`, `init_strategies`.
   - File này làm gì: điều phối terminal, strategy và executor.
   - Tại sao cần đọc: đây là lifecycle gốc.
   - Đọc tiếp: `core/config.py`, `lib/executor.py`.

3. [src/aiomql/core/config.py](E:/BLC/Dev_AI_MT5/src/aiomql/core/config.py:17)
   - Class: `Config`.
   - Method quan trọng: `__new__`, `load_config`, `init_state`, `init_store`.
   - File này làm gì: giữ global config/services.
   - Tại sao cần đọc: nguồn chính của shared-state và multi-account risk.
   - Đọc tiếp: `core/state.py`, `core/store.py`.

4. [src/aiomql/lib/executor.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/executor.py:17)
   - Class: `Executor`.
   - Method quan trọng: `execute`, `run_strategy`, `run_coroutine_task`, `exit`.
   - File này làm gì: tạo thread và event loop topology.
   - Tại sao cần đọc: hiểu concurrency thật.
   - Đọc tiếp: `lib/strategy.py`.

5. [src/aiomql/lib/strategy.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/strategy.py:18)
   - Class: `Strategy`.
   - Method quan trọng: `initialize`, `run_strategy`, `live_strategy`, `trade`.
   - File này làm gì: template vòng lặp strategy.
   - Tại sao cần đọc: nối Executor với business signal.
   - Đọc tiếp: `lib/sessions.py`, concrete Strategy.

6. [src/aiomql/lib/sessions.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/sessions.py:27)
   - Class: `Session`, `Sessions`.
   - Method quan trọng: `check`, `begin`, `close`, `action`.
   - File này làm gì: time-window scheduling.
   - Tại sao cần đọc: thấy khi nào `trade()` được phép chạy.
   - Đọc tiếp: `examples/.../ribbon_scalper.py`.

7. [examples/sample_app_2/strategies/ribbon_scalper.py](E:/BLC/Dev_AI_MT5/examples/sample_app_2/strategies/ribbon_scalper.py:4)
   - Class: `RibbonScalper`.
   - Method quan trọng: `find_entry`, `trade`.
   - File này làm gì: signal thực tế từ candle/EMA.
   - Tại sao cần đọc: thấy Strategy chuyển signal sang Trader.
   - Đọc tiếp: `examples/sample_app_2/traders/rs_trader.py`.

8. [examples/sample_app_2/traders/rs_trader.py](E:/BLC/Dev_AI_MT5/examples/sample_app_2/traders/rs_trader.py:7)
   - Class: `RSTrader`.
   - Method quan trọng: `create_order`, `place_trade`.
   - File này làm gì: nối risk/lot/order/send.
   - Tại sao cần đọc: concrete trade flow rõ nhất.
   - Đọc tiếp: `lib/trader.py`.

9. [src/aiomql/lib/trader.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trader.py:20)
   - Class: `Trader`.
   - Method quan trọng: `create_order_with_sl`, `check_order`, `send_order`, `record_trade`.
   - File này làm gì: orchestration cấp trade.
   - Tại sao cần đọc: biết lot, SL/TP và Result được tạo khi nào.
   - Đọc tiếp: `lib/ram.py`, `lib/order.py`.

10. [src/aiomql/lib/ram.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/ram.py:7)
    - Class: `RAM`.
    - Method quan trọng: `get_amount`, `check_open_positions`, `check_losing_positions`.
    - File này làm gì: tính risk amount và primitive limits.
    - Tại sao cần đọc: phân biệt risk amount với lot calculation.
    - Đọc tiếp: `contrib/symbols/forex_symbol.py`.

11. [src/aiomql/contrib/symbols/forex_symbol.py](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/symbols/forex_symbol.py:6)
    - Class: `ForexSymbol`.
    - Method quan trọng: `compute_volume_sl`, `compute_volume_points`.
    - File này làm gì: tính lot từ amount/distance/contract size.
    - Tại sao cần đọc: đây là nơi lot thực sự được quyết định.
    - Đọc tiếp: `lib/order.py`.

12. [src/aiomql/lib/order.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/order.py:14)
    - Class: `Order`.
    - Method quan trọng: `request`, `check`, `send`, `send_order`.
    - File này làm gì: tạo request và gọi MT5.
    - Tại sao cần đọc: ranh giới request/response.
    - Đọc tiếp: `core/meta_trader.py`.

13. [src/aiomql/core/meta_trader.py](E:/BLC/Dev_AI_MT5/src/aiomql/core/meta_trader.py:31)
    - Class: `MetaTrader`.
    - Method quan trọng: `_handler`, `initialize`, `login`, `order_send`, `history_deals_get`.
    - File này làm gì: async wrapper và reconnect/retry.
    - Tại sao cần đọc: nơi chạm native API và phát sinh duplicate risk.
    - Đọc tiếp: `core/_core.py`.

14. [src/aiomql/core/_core.py](E:/BLC/Dev_AI_MT5/src/aiomql/core/_core.py:247)
    - Class: `MetaBase`, `MetaCore`.
    - Method quan trọng: `MetaBase.__new__`.
    - File này làm gì: bind hàm/hằng/type từ module `MetaTrader5`.
    - Tại sao cần đọc: chứng minh wrapper không có per-object native session.
    - Đọc tiếp: `core/models.py`.

15. [src/aiomql/core/models.py](E:/BLC/Dev_AI_MT5/src/aiomql/core/models.py:221)
    - Class: `TradeOrder`, `TradeRequest`, `OrderSendResult`, `TradePosition`, `TradeDeal`.
    - Method quan trọng: constructors của result wrappers.
    - File này làm gì: định nghĩa domain/data contracts.
    - Tại sao cần đọc: hiểu ID, volume và billing fields.
    - Đọc tiếp: `lib/positions.py`, `lib/history.py`.

16. [src/aiomql/lib/positions.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/positions.py:17)
    - Class: `Positions`.
    - Method quan trọng: `get_positions`, `close`, `close_position`.
    - File này làm gì: query/close exposure hiện tại.
    - Tại sao cần đọc: hiểu position tracking và ticket assumptions.
    - Đọc tiếp: `contrib/trackers/open_position.py`.

17. [src/aiomql/contrib/trackers/open_position.py](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/trackers/open_position.py:27)
    - Class: `OpenPosition`, `PendingOrder`.
    - Method quan trọng: `track`, `update_position`, `modify_stops`, `hedge_position`, `stack_position`.
    - File này làm gì: quản lý position/pending/hedge/stack.
    - Tại sao cần đọc: thấy giới hạn hedging/netting/recovery.
    - Đọc tiếp: `position_trackers.py`.

18. [src/aiomql/contrib/trackers/position_trackers.py](E:/BLC/Dev_AI_MT5/src/aiomql/contrib/trackers/position_trackers.py:48)
    - Class: `OpenPositionsTracker`.
    - Method quan trọng: `track`, `remove_closed_positions`.
    - File này làm gì: polling toàn bộ tracked positions.
    - Tại sao cần đọc: hiểu tracker thread/event loop.
    - Đọc tiếp: `lib/history.py`.

19. [src/aiomql/lib/history.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/history.py:17)
    - Class: `History`.
    - Method quan trọng: `get_deals`, `get_orders`, `get_deals_by_position`.
    - File này làm gì: lấy Order/Deal history.
    - Tại sao cần đọc: điểm bắt đầu cho Deal ledger.
    - Đọc tiếp: `lib/trade_records.py`.

20. [src/aiomql/lib/trade_records.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/trade_records.py:18)
    - Class: `TradeRecords`.
    - Method quan trọng: `update_sql_records`, `update_rows`.
    - File này làm gì: cập nhật Result khi phát hiện closing Deal.
    - Tại sao cần đọc: thấy reconciliation hiện tại làm mất multi-deal.
    - Đọc tiếp: `core/task_queue.py`.

21. [src/aiomql/core/task_queue.py](E:/BLC/Dev_AI_MT5/src/aiomql/core/task_queue.py:55)
    - Class: `QueueItem`, `TaskQueue`.
    - Method quan trọng: `add`, `worker`, `run`, `cancel`.
    - File này làm gì: chạy persistence/background tasks.
    - Tại sao cần đọc: đánh giá durability và cross-loop risk.
    - Đọc tiếp: `lib/result.py`.

22. [src/aiomql/lib/result.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/result.py:17)
    - Class: `Result`.
    - Method quan trọng: `get_data`, `save`, `to_csv`, `to_json`, `to_sql`.
    - File này làm gì: persist `OrderSendResult`.
    - Tại sao cần đọc: chứng minh Result không phải Deal ledger.
    - Đọc tiếp: `lib/result_db.py`.

23. [src/aiomql/lib/result_db.py](E:/BLC/Dev_AI_MT5/src/aiomql/lib/result_db.py:10)
    - Class: `ResultDB`.
    - Method quan trọng: `__post_init__`, inherited `save`.
    - File này làm gì: schema SQLite one-row-per-order.
    - Tại sao cần đọc: thấy `order` PK và thiếu account/position/billing fields.
    - Đọc tiếp: `core/state.py`, `core/store.py`.

# 16. 5 việc nên làm tiếp theo

1. Chốt topology production: **một account + một terminal/data directory + một worker process**, verify `login/server` trước mọi send và fail closed nếu terminal path sai.

2. Thiết kế central Deal Ledger và reconciler: unique `(mt5_account_id, deal_ticket)`, overlap-window history sync, startup recovery và raw payload audit.

3. Hardening execution protocol: bỏ blind resend, persist intent trước send, xử lý `DONE_PARTIAL`, ambiguous outcome, one-order-many-deals và account correlation.

4. Xây billing ngoài MT5 bằng transactional outbox/idempotent consumer; snapshot `fee_per_lot` và định nghĩa rõ policy cho `IN/OUT/INOUT/OUT_BY`.

5. Tách offline unit/integration/live tests; thêm demo allowlist, fault-injection cho timeout/crash/partial fill, CI, secrets management, metrics, alerting và graceful shutdown.
