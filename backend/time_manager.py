# time_manager.py
from datetime import datetime, timedelta
import time
from config import START_TIME, CHINA_TZ

# 全局变量
TIME_ACCELERATION_MULTIPLIER = 20  # 默认加速倍数
ACCELERATED_TIME_ENABLED = True    # 默认开启加速

# 使用全局变量来跟踪时间偏移，以实现平滑加速
current_time_offset = timedelta(seconds=0)
last_real_time = time.time()

def set_time_acceleration(multiplier: int):
    """设置时间加速倍数"""
    global TIME_ACCELERATION_MULTIPLIER
    TIME_ACCELERATION_MULTIPLIER = multiplier

def set_time_enabled(enabled: bool):
    """设置时间是否启用加速"""
    global ACCELERATED_TIME_ENABLED
    ACCELERATED_TIME_ENABLED = enabled

def get_current_virtual_time() -> datetime:
    """
    计算当前虚拟时间
    """
    global current_time_offset, last_real_time
    now = time.time()
    
    # 确保 START_TIME 有时区信息
    start_time_tz = START_TIME.replace(tzinfo=CHINA_TZ) if START_TIME.tzinfo is None else START_TIME
    
    if ACCELERATED_TIME_ENABLED:
        delta_real = now - last_real_time
        current_time_offset += timedelta(seconds=delta_real * TIME_ACCELERATION_MULTIPLIER)
    last_real_time = now
    
    return start_time_tz + current_time_offset

def get_accelerated_time() -> dict:
    """获取加速后的虚拟时间信息"""
    vt = get_current_virtual_time()
    return {
        "timestamp": vt.timestamp(),  # Unix 时间戳
        "iso_format": vt.isoformat(),  # ISO 格式
        "virtual_time": vt,
        "multiplier": TIME_ACCELERATION_MULTIPLIER if ACCELERATED_TIME_ENABLED else 0
    }
