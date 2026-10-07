import logging

from aiomql import Bot, ForexSymbol, auto_commit, OpenPositionsTracker

from .emaxover import EMAXOver

logging.basicConfig(level=logging.INFO)


def x_bot():
    """Khởi chạy chương trình giao dịch giao dịch đồng bộ mẫu; phối hợp với `Bot`."""
    syms = ["LTCUSD", "ETHUSD", "SOLUSD", "BTCUSD", "ADAUSD"]
    symbols = [ForexSymbol(name=sym) for sym in syms]
    strategies = [EMAXOver(symbol=symbol) for symbol in symbols]
    bot = Bot()
    bot.add_strategies(strategies=strategies)
    bot.add_coroutine(coroutine=OpenPositionsTracker(autocommit=True).track, on_separate_thread=True)
    # bot.add_coroutine(coroutine=auto_commit, on_separate_thread=True)
    bot.execute()


if __name__ == '__main__':
    x_bot()
