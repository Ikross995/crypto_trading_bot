#!/usr/bin/env python3
"""
Диагностика подключения к Binance API
"""

import os
import sys
from dotenv import load_dotenv

def diagnose_binance_connection():
    """Диагностирует проблемы с Binance API подключением"""
    print("🔍 ДИАГНОСТИКА BINANCE API ПОДКЛЮЧЕНИЯ")
    print("=" * 50)
    
    # Загружаем .env.testnet
    env_file = ".env.testnet"
    if os.path.exists(env_file):
        load_dotenv(env_file)
        print(f"✅ Загружен файл: {env_file}")
    else:
        print(f"❌ Файл не найден: {env_file}")
        return
    
    # Проверяем переменные окружения
    print("\n📋 КОНФИГУРАЦИЯ:")
    api_key = os.getenv('BINANCE_API_KEY', '')
    secret_key = os.getenv('BINANCE_SECRET_KEY', '')
    testnet = os.getenv('BINANCE_TESTNET', 'false')
    enable_real = os.getenv('ENABLE_REAL_API', 'false')
    
    print(f"BINANCE_API_KEY: {'✅ Установлен' if api_key else '❌ Пустой'} ({len(api_key)} символов)")
    print(f"BINANCE_SECRET_KEY: {'✅ Установлен' if secret_key else '❌ Пустой'} ({len(secret_key)} символов)")
    print(f"BINANCE_TESTNET: {testnet} {'✅' if testnet.lower() == 'true' else '❌ Должно быть true'}")
    print(f"ENABLE_REAL_API: {enable_real} {'✅' if enable_real.lower() == 'true' else '❌ Должно быть true'}")
    
    # Проверяем формат ключей
    print("\n🔑 АНАЛИЗ API КЛЮЧЕЙ:")
    if api_key:
        if len(api_key) == 64:
            print("✅ API Key: Правильная длина (64 символа)")
        else:
            print(f"❌ API Key: Неправильная длина ({len(api_key)} вместо 64)")
            
        if api_key.isalnum():
            print("✅ API Key: Содержит только буквы и цифры")
        else:
            print("❌ API Key: Содержит недопустимые символы")
            
        if ' ' in api_key:
            print("❌ API Key: Содержит пробелы!")
        else:
            print("✅ API Key: Без пробелов")
    
    if secret_key:
        if len(secret_key) == 64:
            print("✅ Secret Key: Правильная длина (64 символа)")
        else:
            print(f"❌ Secret Key: Неправильная длина ({len(secret_key)} вместо 64)")
            
        if ' ' in secret_key:
            print("❌ Secret Key: Содержит пробелы!")
        else:
            print("✅ Secret Key: Без пробелов")
    
    # Тестируем подключение
    print("\n🌐 ТЕСТ ПОДКЛЮЧЕНИЯ:")
    try:
        from binance.client import Client
        from binance.exceptions import BinanceAPIException
        
        if not api_key or not secret_key:
            print("❌ Нет API ключей для тестирования")
            return
            
        print("📡 Подключаемся к Binance Testnet...")
        
        client = Client(
            api_key=api_key,
            api_secret=secret_key,
            testnet=True  # Testnet
        )
        
        # Тестируем подключение
        account_info = client.get_account()
        print("✅ УСПЕШНОЕ ПОДКЛЮЧЕНИЕ К BINANCE TESTNET!")
        
        # Показываем баланс
        for balance in account_info['balances']:
            if balance['asset'] == 'USDT' and float(balance['free']) > 0:
                print(f"💰 Testnet баланс: {balance['free']} USDT")
                break
        
        # Тестируем получение цены
        price = client.get_symbol_ticker(symbol="BTCUSDT")
        print(f"📊 Текущая цена BTCUSDT: {price['price']}")
        
        print("\n🎉 ВСЕ РАБОТАЕТ! API ключи корректные.")
        return True
        
    except BinanceAPIException as e:
        print(f"❌ Ошибка Binance API: {e}")
        if e.code == -2015:
            print("💡 РЕШЕНИЕ: API ключи неправильные или неактивные")
            print("   1. Проверьте что ключи от testnet.binance.vision")
            print("   2. Убедитесь что ключи активны")
            print("   3. Проверьте разрешения (permissions)")
        elif e.code == -1021:
            print("💡 РЕШЕНИЕ: Проблема с временными метками")
            print("   Синхронизируйте время на компьютере")
        
    except ImportError:
        print("❌ Модуль python-binance не установлен")
        print("💡 РЕШЕНИЕ: pip install python-binance")
        
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        
    return False

def show_testnet_guide():
    """Показать инструкции по получению Testnet ключей"""
    print("\n" + "="*50)
    print("📝 КАК ПОЛУЧИТЬ ПРАВИЛЬНЫЕ TESTNET API КЛЮЧИ:")
    print("="*50)
    print()
    print("1. Перейдите на: https://testnet.binance.vision/")
    print("2. Войдите через GitHub аккаунт")  
    print("3. Нажмите 'Generate HMAC_SHA256 Key'")
    print("4. Скопируйте API Key и Secret Key")
    print("5. Обновите .env.testnet файл:")
    print()
    print("BINANCE_API_KEY=ваш_64_символьный_api_key")
    print("BINANCE_SECRET_KEY=ваш_64_символьный_secret_key")
    print("BINANCE_TESTNET=true")
    print("ENABLE_REAL_API=true")
    print()
    print("⚠️  ВАЖНО: Используйте ТОЛЬКО testnet ключи!")
    print("    НЕ используйте ключи от основной биржи binance.com")

if __name__ == "__main__":
    success = diagnose_binance_connection()
    if not success:
        show_testnet_guide()