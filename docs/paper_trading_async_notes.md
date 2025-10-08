# Бумажный движок: что произошло

## Контекст
- Ранее `PaperTradingEngine.start()` был синхронным и внутри вызывал `asyncio.run(...)` для асинхронных инициализаций компонентов.
- Когда запускали CLI через `asyncio.run(run_paper_trading(...))`, внутри уже была активная event loop. Повторный `asyncio.run(...)` создавал `RuntimeError: asyncio.run() cannot be called from a running event loop`.

## Что поменяли
1. `PaperTradingEngine.start()` и `_initialize_components()` переписаны как `async def`. Теперь они возвращают корутину, которую нужно `await`.
2. Все места, где запускали движок (`run_paper_trading`, живой раннер и т.п.), обновлены чтобы делать `await engine.start()`.
3. CLI теперь запускает `run_paper_trading` через `asyncio.run(...)`, внутри которого компоненты корректно инициализируются без вложенных `asyncio.run`.

## Итог
- Инициализация бумажного движка больше не падает из-за конфликтов event loop.
- Юнит-тесты проходят: `pytest`.
- При запуске `python cli_integrated.py paper --no-verbose --symbols BTCUSDT --timeframe 1m --testnet --dry-run` движок стартует (сетевые 403 от Binance в тестовом режиме — ожидаемое поведение).

## Что делать, если видите ошибку
- Убедитесь, что место запуска вызывает `await engine.start()`.
- Если код вне асинхронного контекста, оберните в `asyncio.run(...)` один раз на верхнем уровне.
