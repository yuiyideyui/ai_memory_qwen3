
import asyncio
from memory_manager import list_roles, update_rest_states, update_time_memory
from time_manager import get_accelerated_time


async def update_all_roles_time_memory(time_info: dict):
    """为所有角色更新时间记忆（每10分钟调用）"""
    try:
        virtual_time = time_info["virtual_time"]
        roles = list_roles()
        
        # 统一使用时间信息字典传递给 update_time_memory
        for role in roles:
            await asyncio.to_thread(update_time_memory, role, time_info)
        
        print(f"为 {len(roles)} 个角色更新时间记忆: {virtual_time.isoformat()}")
        
    except Exception as e:
        print(f"更新角色时间记忆失败: {e}")

async def broadcast_time_updates(sio):
    """定期向所有客户端广播时间更新，并管理时间和休息状态"""
    last_minute_check = None
    
    while True:
        try:
            time_info = get_accelerated_time()
            current_virtual_time = time_info["virtual_time"]
            
            # 🔥 每10个虚拟分钟更新时间记忆（在 20 倍速下，实际是每 30 秒）
            # T*20 / 60 = 10 -> T = 30s
            current_minute = current_virtual_time.minute
            check_minute_interval = current_minute // 10  # 每10分钟一个区间
            
            if last_minute_check != check_minute_interval:
                # 时间间隔发生变化，更新时间记忆
                await update_all_roles_time_memory(time_info)
                
                # 🔥 同时更新休息状态 (必须使用 asyncio.to_thread)
                await asyncio.to_thread(update_rest_states) 
                
                last_minute_check = check_minute_interval
            
            # 广播给所有连接的客户端
            await sio.emit('accelerated_time', {'time': time_info["timestamp"]})
            await asyncio.sleep(1)  # 每秒更新一次
            
        except Exception as e:
            print(f"Error in time broadcast: {e}")
            await asyncio.sleep(1)
