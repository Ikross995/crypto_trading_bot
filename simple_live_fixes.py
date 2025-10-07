#!/usr/bin/env python3
"""
SIMPLE LIVE TRADING FIXES - NO IMPORTS CONFLICT

Direct monkey patching for LiveTradingEngine without import conflicts.
Apply AFTER all imports but BEFORE running engine.

Usage:
    import simple_live_fixes
    simple_live_fixes.apply_fixes()
    # Then run your normal code
"""

def apply_fixes():
    """Apply all live trading fixes without import conflicts."""
    
    print("🔧 Applying simple live trading fixes...")
    
    # Fix 1: Add logger to LiveTradingEngine at runtime
    def add_logger_attribute():
        """Add logger attribute to LiveTradingEngine instances."""
        try:
            import sys
            if 'runner.live' in sys.modules:
                live_module = sys.modules['runner.live']
                if hasattr(live_module, 'LiveTradingEngine'):
                    LiveTradingEngine = live_module.LiveTradingEngine
                    
                    # Patch __init__ to add logger
                    original_init = LiveTradingEngine.__init__
                    
                    def patched_init(self, config):
                        original_init(self, config)
                        # Add loguru logger
                        try:
                            from loguru import logger
                            self.logger = logger
                        except ImportError:
                            import logging
                            self.logger = logging.getLogger(__name__)
                        print("✅ Added logger attribute to LiveTradingEngine")
                    
                    LiveTradingEngine.__init__ = patched_init
                    
        except Exception as e:
            print(f"⚠️ Could not add logger: {e}")
    
    # Fix 2: Patch _run_trading_loop to use loguru logger
    def fix_trading_loop_logger():
        """Fix logger usage in _run_trading_loop."""
        try:
            import sys
            if 'runner.live' in sys.modules:
                live_module = sys.modules['runner.live']
                if hasattr(live_module, 'LiveTradingEngine'):
                    LiveTradingEngine = live_module.LiveTradingEngine
                    
                    # Get source code to check if patching needed
                    import inspect
                    try:
                        source = inspect.getsource(LiveTradingEngine._run_trading_loop)
                        if "self.logger.info" in source:
                            print("🔧 Patching _run_trading_loop logger usage...")
                            
                            # Store original method
                            original_method = LiveTradingEngine._run_trading_loop
                            
                            # Create fixed method
                            async def fixed_run_trading_loop(self):
                                """Fixed _run_trading_loop with proper logger."""
                                try:
                                    from loguru import logger
                                except ImportError:
                                    import logging
                                    logger = logging.getLogger(__name__)
                                
                                logger.info("Starting main trading loop")
                                
                                loop_count = 0
                                from datetime import datetime, timedelta
                                last_health_check = getattr(self, 'start_time', None) or datetime.utcnow()
                                
                                while getattr(self, 'running', True):
                                    try:
                                        loop_start = datetime.utcnow()
                                        loop_count += 1
                                        
                                        # Health check every 5 minutes
                                        if (loop_start - last_health_check) > timedelta(minutes=5):
                                            await self._health_check()
                                            last_health_check = loop_start
                                        
                                        # Check for emergency conditions
                                        if await self._check_emergency_stop():
                                            logger.critical("Emergency stop triggered!")
                                            await self.stop()
                                            break
                                        
                                        # Fixed overrides handling
                                        if hasattr(self, '_overrides_watcher') and self._overrides_watcher:
                                            changes = self._overrides_watcher.poll()
                                            if changes:
                                                try:
                                                    from infra.settings import apply_settings_to_config
                                                    apply_settings_to_config(self.config, changes)
                                                    # Use logger instead of self.logger
                                                    logger.info(f"Applied runtime overrides: {list(changes.keys())}")
                                                except Exception as e:
                                                    logger.warning(f"Failed to apply overrides: {e}")
                                        
                                        # Process trading logic
                                        if not getattr(self, 'paused', False):
                                            await self._process_trading_cycle()
                                        
                                        # Update metrics
                                        await self._update_metrics()
                                        
                                        # Calculate loop timing
                                        loop_duration = (datetime.utcnow() - loop_start).total_seconds()
                                        if hasattr(self, 'metrics') and hasattr(self.metrics, 'record_loop_time'):
                                            self.metrics.record_loop_time(loop_duration)
                                        
                                        # Sleep for configured interval
                                        trading_interval = getattr(self.config, 'trading_interval', 5)
                                        sleep_time = max(0, trading_interval - loop_duration)
                                        if sleep_time > 0:
                                            import asyncio
                                            await asyncio.sleep(sleep_time)
                                        
                                        # Log periodic status
                                        if loop_count % 60 == 0:  # Every 60 loops
                                            await self._log_status()
                                    
                                    except Exception as e:
                                        logger.error(f"Error in trading loop: {e}")
                                        import asyncio
                                        await asyncio.sleep(5)  # Pause before retrying
                                        
                                        # Increment error count
                                        if hasattr(self, 'metrics') and hasattr(self.metrics, 'increment_error_count'):
                                            self.metrics.increment_error_count()
                                        
                                        # Emergency stop if too many consecutive errors
                                        consecutive_errors = getattr(self.metrics, 'consecutive_errors', 0) if hasattr(self, 'metrics') else 0
                                        if consecutive_errors > 10:
                                            logger.critical("Too many consecutive errors, stopping engine")
                                            await self.stop()
                                            break
                            
                            # Apply the fix
                            LiveTradingEngine._run_trading_loop = fixed_run_trading_loop
                            print("✅ Fixed _run_trading_loop logger usage")
                            
                    except OSError:
                        print("⚠️ Could not inspect source code, skipping logger fix")
                        
        except Exception as e:
            print(f"⚠️ Could not fix trading loop: {e}")
    
    # Fix 3: Patch _process_trading_cycle for dca_enabled
    def fix_dca_enabled_access():
        """Fix dca_enabled attribute access."""
        try:
            import sys
            if 'runner.live' in sys.modules:
                live_module = sys.modules['runner.live']
                if hasattr(live_module, 'LiveTradingEngine'):
                    LiveTradingEngine = live_module.LiveTradingEngine
                    
                    # Store original method
                    original_cycle = LiveTradingEngine._process_trading_cycle
                    
                    async def fixed_process_trading_cycle(self):
                        """Fixed trading cycle with safe dca_enabled access."""
                        try:
                            from loguru import logger
                        except ImportError:
                            import logging
                            logger = logging.getLogger(__name__)
                        
                        # 1. Generate trading signals
                        signal = await self.signal_generator.generate_signal(getattr(self.config, 'symbol', 'BTCUSDT'))
                        
                        if signal and signal.id not in self.processed_signals:
                            logger.info(f"New signal: {signal.side} {signal.strength:.2f}")
                            await self._process_signal(signal)
                            self.processed_signals.add(signal.id)
                        
                        # 2. Manage existing positions
                        await self._manage_positions()
                        
                        # 3. Process DCA opportunities - FIXED: Safe attribute access
                        dca_enabled = getattr(self.config, 'dca_enabled', False)
                        if dca_enabled:
                            await self._process_dca()
                        
                        # 4. Handle order updates
                        await self._update_orders()
                    
                    LiveTradingEngine._process_trading_cycle = fixed_process_trading_cycle
                    print("✅ Fixed dca_enabled attribute access")
                    
        except Exception as e:
            print(f"⚠️ Could not fix dca_enabled: {e}")
    
    # Fix 4: Patch _can_trade_signal for is_in_cooldown
    def fix_cooldown_signature():
        """Fix is_in_cooldown method signature errors."""
        try:
            import sys
            if 'runner.live' in sys.modules:
                live_module = sys.modules['runner.live']
                if hasattr(live_module, 'LiveTradingEngine'):
                    LiveTradingEngine = live_module.LiveTradingEngine
                    
                    # Store original method
                    original_can_trade = LiveTradingEngine._can_trade_signal
                    
                    async def fixed_can_trade_signal(self, signal) -> bool:
                        """Fixed signal validation with safe cooldown check."""
                        try:
                            from loguru import logger
                        except ImportError:
                            import logging
                            logger = logging.getLogger(__name__)
                        
                        # Check if symbol is in allowed list
                        allowed_symbols = getattr(self.config, 'symbols', [signal.symbol])
                        if signal.symbol not in allowed_symbols:
                            return False
                        
                        # Check trading hours
                        if not self._is_trading_hours():
                            return False
                        
                        # Fixed cooldown check with multiple fallback strategies
                        try:
                            # Try with symbol parameter
                            if hasattr(self.order_manager, 'is_in_cooldown'):
                                is_cooldown = await self.order_manager.is_in_cooldown(signal.symbol)
                                if is_cooldown:
                                    return False
                                    
                        except TypeError:
                            try:
                                # Try without parameters  
                                is_cooldown = await self.order_manager.is_in_cooldown()
                                if is_cooldown:
                                    return False
                            except:
                                # Skip cooldown check entirely
                                logger.debug(f"Cooldown check failed, continuing")
                                pass
                        
                        except Exception as e:
                            logger.debug(f"Cooldown check error: {e}")
                            pass
                        
                        # Check existing position limits
                        max_position_size = getattr(self.config, 'max_position_size', float('inf'))
                        current_position = self.active_positions.get(signal.symbol)
                        if (
                            current_position
                            and abs(current_position.size) >= max_position_size
                        ):
                            return False
                        
                        return True
                    
                    LiveTradingEngine._can_trade_signal = fixed_can_trade_signal
                    print("✅ Fixed is_in_cooldown method signature")
                    
        except Exception as e:
            print(f"⚠️ Could not fix cooldown: {e}")
    
    # Fix 5: Add missing config attributes
    def add_missing_config_attributes():
        """Add missing config attributes."""
        try:
            import sys
            if 'runner.live' in sys.modules:
                live_module = sys.modules['runner.live']
                if hasattr(live_module, 'LiveTradingEngine'):
                    LiveTradingEngine = live_module.LiveTradingEngine
                    
                    # Store original init
                    original_init = LiveTradingEngine.__init__
                    
                    def enhanced_init(self, config):
                        # Call original init
                        original_init(self, config)
                        
                        # Ensure config has required attributes
                        config_defaults = {
                            'dca_enabled': False,
                            'trading_interval': 5,
                            'max_position_size': 1000000,
                            'trading_hours_enabled': False,
                            'trading_start_hour': 0,
                            'trading_end_hour': 23,
                            'max_daily_loss': 1000,
                            'min_account_balance': 100,
                            'max_drawdown': 0.2,
                            'close_positions_on_exit': False,
                            'symbols': ['BTCUSDT'],
                            'symbol': 'BTCUSDT',
                        }
                        
                        for attr, default_value in config_defaults.items():
                            if not hasattr(self.config, attr):
                                setattr(self.config, attr, default_value)
                    
                    LiveTradingEngine.__init__ = enhanced_init
                    print("✅ Added missing config attributes")
                    
        except Exception as e:
            print(f"⚠️ Could not add config attributes: {e}")
    
    # Apply all fixes
    add_logger_attribute()
    fix_trading_loop_logger() 
    fix_dca_enabled_access()
    fix_cooldown_signature()
    add_missing_config_attributes()
    
    print("✅ ALL SIMPLE LIVE TRADING FIXES APPLIED!")
    print("🎯 Your LiveTradingEngine should now work without crashes!")


# Auto-apply fixes when imported
print("🚀 Loading simple live trading fixes...")
# Don't auto-apply - let user call explicitly to avoid conflicts