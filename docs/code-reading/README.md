# AIOMQL Code Reading

## Execution Flow Progress

- [x] Execution overview
- [ ] Bot / startup
- [ ] Executor
- [ ] Strategy
- [ ] Trader
- [ ] Order
- [ ] MetaTrader
- [ ] Position / tracker

Overview là bản đồ đã được agent trace tĩnh từ source. Các mục chưa chọn là những phiên người đọc sẽ học tiếp, không có nghĩa source chưa được dùng làm bằng chứng cho overview.

## Current Reading Position

Current file:
`src/aiomql/lib/bot.py`

Absolute path:
`E:\BLC\Dev_AI_MT5\src\aiomql\lib\bot.py`

Current class:
`Bot`

Current method:
`execute()` — dòng 153–157 tại snapshot 2026-10-18.

Why start here:
Method ngắn nối `initialize_sync()` với `Executor.execute()` qua điều kiện `config.shutdown is False`. Đây là điểm bắt đầu học được đề xuất (INFERENCE) từ call sites đã xác minh trong report; chưa bắt đầu walkthrough chi tiết hoặc đánh dấu người dùng đã đọc Bot.

Trong cùng file, đọc tiếp:
`__init__ → add_strategies/add_strategy → initialize_sync → start_terminal_sync → init_strategies_sync/init_strategy_sync`; sau đó so sánh `start/initialize` với nhánh sync. Xem chính xác line và mục tiêu ở phần **Next Reading Session** của report.

## Next

Next file:
`examples/sample_app/bot.py`

Absolute path:
`E:\BLC\Dev_AI_MT5\examples\sample_app\bot.py`

Next class:
Không có class trong file; caller ở cấp module tạo `Bot`, `ForexSymbol`, `EMAXOver`, `OpenPositionsTracker`.

Next method:
`x_bot()` — dòng 10–19; xem module guard dòng 22–23.

Reason:
Sau khi hiểu Bot là coordinator, xem app tạo và đăng ký instances thế nào rồi gọi `bot.execute()`. Tiếp theo mở `src/aiomql/lib/executor.py::Executor.execute()` để hiểu mỗi strategy đi vào thread/event loop nào.

Trước khi chuyển file, cần tự giải thích được:

- `add_strategies()` chưa chạy trade.
- Startup terminal và symbol xảy ra trước runtime scheduler.
- Strategy initialize thành công mới trở thành runner.
- Bot entry sync vẫn có thể chạy strategy async thông qua Executor.

## Documents

- [01-execution-flow-overview.md](01-execution-flow-overview.md) — call chain, data flow, BUY lifecycle, concurrency, tracker continuation và reading path 12 file.

## Continuity Notes

- Repository: `E:\BLC\Dev_AI_MT5`; ngày trace 2026-10-18, HEAD `431e133e85bcea44dd8bbc9d192c40f8c0cd3155` cộng working tree lúc đọc.
- Tuyến trace chính: `examples/sample_app/bot.py::x_bot → EMAXOver → TestTrader`; tuyến đối chiếu: `sample_app_2 → RibbonScalper → RSTrader` và `Chaos → ScalpTrader`.
- Chưa chạy bot, test hoặc kết nối MT5. VERIFIED trong report có nghĩa đã thấy source/call site, không phải xác nhận runtime thành công.
- Nếu source đã thay đổi ở phiên sau, xác minh lại line/method đang học; không cần trace lại toàn repo trước khi tiếp tục.
- Chỉ cập nhật checkbox/vị trí học theo tiến độ thực tế của người đọc. Không tự coi việc agent đã đọc source để lập overview là người dùng đã học xong từng lớp.
