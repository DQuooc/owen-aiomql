# Diagram Guide

Đối chiếu source hiện tại ngày **2026-10-08**. Các sơ đồ mô tả phần Deal Ledger sau Phase 2.2C; source Python là nguồn quyết định khi thiết kế cũ hoặc prompt khác implementation.

## 01 ERD

[01_erd.puml](01_erd.puml) mô tả đủ 40 column của ba bảng SQLite:

- `ledger_accounts` (6 columns) có 0..n `deals` (27 columns).
- Mỗi `deals` có 0..n `deal_observations` (7 columns).
- Mỗi child thuộc một parent trong dữ liệu hợp lệ do repository ghi.

PK, FK, ba UNIQUE constraints và hai index tường minh đều lấy từ `_initialize_schema()` trong [sqlite.py](../../src/aiomql/ledger/sqlite.py). Dấu `*` biểu thị `NOT NULL` được khai báo trực tiếp trong SQLite DDL. Riêng `TEXT PRIMARY KEY` không có `NOT NULL` tường minh trong ordinary rowid table; model/repository cung cấp UUID không null. Đây là điểm khác với PK trong SQL Server.

**Order / Deal / Position:** Order là lệnh, Deal là một execution trong history, Position là vị thế liên quan. `order_ticket` và `position_id` là data fields có index, không phải PK, UNIQUE hay FK trong ledger. Nhiều Deal có thể cùng order/position; không có bảng ledger Order hoặc Position để vẽ thêm FK.

`NormalizedDeal.raw_payload_json` được lưu vào column `raw_payload`. Payload đầu tiên nằm trong `deals`; chỉ biến thể có hash khác được thêm vào `deal_observations`. `broker_fee` lấy từ SDK `fee`, không phải phí SaaS.

## 02 Activity

[02_activity.puml](02_activity.puml) mô tả một invocation của `DealIngestor.ingest_range()` theo đúng thứ tự source:

1. Validate account/range/ingestion ID; đổi range sang UTC.
2. Guard namespace cấu hình cùng session login/server trước fetch.
3. Fetch và kiểm tra batch; gán `retrieved`.
4. Guard lần hai, **kể cả khi batch rỗng**.
5. Với mỗi record: `_asdict()` nếu có, normalizer tạo snapshot, repository ghi transaction riêng, cộng counter.
6. Trả report theo trạng thái thực tế.

| Tình huống | Kết quả hiện tại |
|---|---|
| Input sai kiểu / naive datetime / range đảo / ID rỗng | Raise `TypeError` hoặc `ValueError` trước I/O; không có report |
| Namespace/account sai hoặc account unavailable trước fetch | `FAILED`, stage `ACCOUNT_BEFORE_FETCH`; không fetch/ghi |
| `None`, exception, collection sai hoặc phần tử không phải record | `FAILED`, stage `FETCH`; không ghi |
| Account sai/unavailable sau fetch | `FAILED`, stage `ACCOUNT_AFTER_FETCH`; giữ retrieved, không ghi batch |
| Batch rỗng và cả hai guard thành công | `SUCCESS_EMPTY` |
| Tất cả record xử lý được | `SUCCESS`, kể cả khi có `CONFLICT` đã được lưu |
| Normalize lỗi xen kẽ record hợp lệ | Tiếp tục record sau; `PARTIAL` khi có normalized record |
| Tất cả record normalize lỗi | `FAILED` |
| Repository hoặc xử lý outcome lỗi | Dừng batch, `FAILED`; các commit/counters đã hoàn tất trước đó được giữ |
| Cancellation | Propagate; không chuyển thành report thành công hoặc thất bại |

Một collection hợp lệ nhưng thiếu/sai field của Deal sẽ đi vào lỗi normalization theo record. `_asdict()` chỉ lấy mapping; deep snapshot/canonicalization nằm trong `normalize_deal()`. Không có snapshot sâu ở constructor của `DealHistoryBatch`.

## 03 Sequence

[03_sequence.puml](03_sequence.puml) chỉ ra các lời gọi giữa Application, DealIngestor, source adapter, MetaTrader, SDK MetaTrader5, normalizer, repository và SQLite.

`Application` là caller bên ngoài có thể gọi API hiện hữu. Search source/examples cho thấy chưa có production/example caller tự động gọi ingestor; các caller cụ thể hiện ở `tests/offline/test_deal_ingestion.py`. Sơ đồ không khẳng định bot tự chạy ingestion.

Caller truyền repository và source đã cấu hình; account mapping phải được register trước khi ghi Deal. Repository kiểm tra mapping khi ingest, không tự register account. `current_account()` kiểm tra session, không thay thế kiểm tra mapping trong repository.

`MetaTrader.account_info()` và `history_deals_get()` đi qua `_handler()` và `asyncio.to_thread()` tới SDK. `_handler(retries=3, retry_safe=True)` hiện có thể initialize/login rồi retry khi nhận `None` do lỗi connection. Ingestor không có vòng retry riêng. Double guard không thể phát hiện session đổi `A -> B -> A` trong fetch, kể cả khi reconnect bên dưới đã đổi session. Namespace là cấu hình tin cậy từ ứng dụng, không được MT5 xác thực trực tiếp.

Trading execution vẫn là flow riêng: `Trader.send_order()` → `Order.send()` → `MetaTrader.order_send()`. `Order.send()` kiểm tra retcode trước khi gửi; `MetaTrader.order_send()` dùng `retry_safe=False`, validate volume và raise `OrderSendAmbiguous` khi outcome không xác định. `Trader` phân biệt `DONE_PARTIAL` với `DONE`. `OrderSendResult` không tự trở thành Deal trong pipeline này. `record_trade()` còn sử dụng cơ chế `Result` cũ, có tùy chọn TaskQueue; điều đó không nằm trong ingestion.

## 04 Database SSMS

[04_database_ssms.sql](04_database_ssms.sql) là **VISUALIZATION MIRROR FOR SQL SERVER / SSMS**: ba bảng cùng PK/FK/UNIQUE và đúng hai index tường minh trong source. Script chỉ tạo cấu trúc trong database test do bạn chọn, không tạo/xóa database hoặc chèn dữ liệu.

**Ứng dụng local/production hiện vẫn dùng SQLite. SQL Server schema này chỉ phục vụ visualization; không phải migration hoặc backend mới.**

### SQLite → SQL Server

| SQLite / ý nghĩa | SQL Server mirror | Lý do / giới hạn |
|---|---|---|
| UUID `TEXT` | `VARCHAR(36)` | Giữ biểu diễn UUID bằng text |
| login/ticket/position/magic `TEXT` | `VARCHAR(128)` | Giữ số nguyên ở dạng text, không qua float |
| broker_namespace/server `TEXT` | `NVARCHAR(128)` | Unicode, chiều dài hữu hạn để tạo composite unique index |
| Decimal `TEXT` | `NVARCHAR(MAX)` | Giữ giá trị text lossless, không đổi sang REAL/DECIMAL |
| raw_payload `TEXT` | `NVARCHAR(MAX)` | JSON Unicode, không thêm JSON CHECK constraint |
| payload_hash `TEXT` | `VARCHAR(64)` | SHA256 hex do normalizer tạo |
| first_seen_at/observed_at `TEXT` | `NVARCHAR(64)` | Giữ ISO UTC text, không đổi sang kiểu datetime của SQL Server |
| Các column `INTEGER` | `BIGINT` | Bao gồm thời gian broker, enum codes, normalizer_version |
| Text còn lại | `NVARCHAR(MAX)` | Giữ comment, symbol, external_id, ingestion_id, metadata |

Các độ dài 36/64/128 là lựa chọn giới hạn cho mirror, **không phải giới hạn đang được SQLite/model enforce**. Key dùng `Latin1_General_100_BIN2` để giữ phân biệt hoa/thường gần với SQLite BINARY; so sánh trailing spaces giữa hai engine vẫn có thể khác. Không dùng mirror để kiểm chứng tương đương dữ liệu giữa hai database.

SQL Server PK bắt buộc NOT NULL. SQLite source có bare `TEXT PRIMARY KEY`; ứng dụng ghi UUID không null. Foreign keys trong SQLite chỉ được bật bởi `PRAGMA foreign_keys=ON` trên từng repository connection. Các kết nối ngoài repository cần tự bật. SQL Server mirror có FK enabled và `NO ACTION`; source không có cascade. Không thêm index cho observation ngoài PK/UNIQUE hoặc FK giả cho order/position.

### Render PlantUML

1. Mở một file `.puml` và copy toàn bộ nội dung, gồm `@startuml` và `@enduml`.
2. Paste vào PlantUML web renderer bạn sử dụng và chọn render.
3. Lặp lại cho ERD, activity và sequence; có thể xuất SVG để phóng to.

Các file tự chứa, không có remote include, credentials hoặc dữ liệu giao dịch. Có thể dùng renderer PlantUML local nếu muốn giữ tài liệu hoàn toàn offline.

### Xem trong SSMS

1. Tạo một **EMPTY TEST DATABASE** riêng.
2. Chọn database đó trong query window của SSMS.
3. Mở và chạy `04_database_ssms.sql`. Script từ chối system database hoặc database đã có user tables; không xóa bảng để chạy lại.
4. Refresh Object Explorer. Mở **Database Diagrams → New Database Diagram**; cho phép tạo diagram-support objects nếu SSMS yêu cầu và tài khoản có quyền phù hợp.
5. Thêm `ledger_accounts`, `deals`, `deal_observations`, rồi sắp xếp và lưu diagram. Nếu môi trường không hỗ trợ Database Diagrams, dùng công cụ xem table relationships.

Chạy script trước khi SSMS thêm diagram-support objects để đáp ứng điều kiện empty database. Script không chọn SQL Server instance hay chứa chuỗi kết nối.

## Trace nguồn và khác biệt với flow phác thảo

| Source đã đọc | Nội dung dùng để vẽ |
|---|---|
| [ledger/models.py](../../src/aiomql/ledger/models.py) | AccountRef, NormalizedDeal, optional fields |
| [ledger/normalize.py](../../src/aiomql/ledger/normalize.py) | Snapshot, UUID5, Decimal, raw JSON/hash, SDK fee mapping |
| [ledger/repository.py](../../src/aiomql/ledger/repository.py) | Repository contract, outcomes, observations |
| [ledger/sqlite.py](../../src/aiomql/ledger/sqlite.py) | DDL, indexes, PRAGMA, per-call transactions, immutable originals |
| [ledger/source.py](../../src/aiomql/ledger/source.py) | Adapter, batch validation, UTC conversion, namespace boundary |
| [ledger/ingestion.py](../../src/aiomql/ledger/ingestion.py) | Guard order, counters, report/error semantics |
| [ledger/__init__.py](../../src/aiomql/ledger/__init__.py) | Public exports |
| [lib/order.py](../../src/aiomql/lib/order.py), [lib/trader.py](../../src/aiomql/lib/trader.py) | Execution flow and legacy result recording are separate |
| [core/meta_trader.py](../../src/aiomql/core/meta_trader.py), [core/_core.py](../../src/aiomql/core/_core.py) | SDK binding, async wrapper, existing read retry behavior |
| [core/models.py](../../src/aiomql/core/models.py) | OrderSendResult / TradeOrder / TradeDeal / TradePosition distinctions |
| [lib/history.py](../../src/aiomql/lib/history.py) | Old History wrapper is not used by new pipeline |
| [test_deal_ingestion.py](../../tests/offline/test_deal_ingestion.py), [test_deal_repository.py](../../tests/offline/test_deal_repository.py), [test_deal_normalizer.py](../../tests/offline/test_deal_normalizer.py) | Actual offline callers and regression cases |

Các điểm source thắng flow phác thảo: post-fetch guard chạy trước nhánh empty; input errors raise thay vì trả FAILED report; mixed normalization errors tiếp tục; storage errors dừng batch nhưng không rollback commit trước đó; CONFLICT có thể nằm trong SUCCESS report; adapter chấp nhận tuple hoặc list từ SDK rồi tạo tuple; read retries tồn tại ở MetaTrader dù ingestor chỉ chạy một lần.

`ingestion_id` do caller truyền hoặc tạo một lần bằng UUID4 mỗi invocation. `observed_at` cũng dùng chung trong batch có record. Replay không đổi Deal identity và giữ first_seen/ingestion ID của Deal gốc; changed variant được lưu observation idempotent. Không có bảng ingestion report/batch trong SQLite.

## Verification và phạm vi

Schema được kiểm tra từ các DDL constant trong `sqlite.py`, không lấy từ prompt. Các sơ đồ chỉ có ba bảng ledger thực tế; không có scheduler, watermark/checkpoint, startup recovery, reconciliation, billing hoặc multi-account process isolation.

Kết quả kiểm tra offline trong task documentation:

- Trích xuất DDL constants bằng AST từ `sqlite.py`, tạo schema SQLite chỉ trong memory rồi đối chiếu: **3 bảng, 40 columns, PK/FK/UNIQUE, nullability, type mapping và 2 index tường minh khớp source**. Không import application hoặc SDK.
- **T-SQL ScriptDom 160: 0 syntax errors**. Parser local được dùng mà không kết nối SQL Server.
- Kiểm tra cặp mở/đóng các block PlantUML và các link local trong README; đủ đúng 5 file yêu cầu.
- SHA256 tổng hợp của **302 file Python trong src/tests không đổi** trước/sau task.

PlantUML chưa render và SQL chưa chạy trong SSMS ở môi trường này; kiểm tra cấu trúc block không thay thế renderer. Cần mở bằng renderer/SSMS của bạn để kiểm tra bố cục và môi trường cụ thể. Không chạy lại business tests cho thay đổi chỉ gồm documentation; không gọi MT5 live.
