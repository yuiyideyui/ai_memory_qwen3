
import asyncio
from prompt_builder import generate_world_narrative
from memory_manager import list_roles, update_rest_states, update_time_memory
from time_manager import get_accelerated_time
import random

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
    """定期向所有客户端广播时间更新，管理状态并触发神视角旁白"""
    last_minute_check = None
    
    while True:
        try:
            time_info = get_accelerated_time()
            current_virtual_time = time_info["virtual_time"]
            
            # 每10个虚拟分钟执行一次状态逻辑（约实际30秒）
            current_minute = current_virtual_time.minute
            check_minute_interval = current_minute // 10 
            
            if last_minute_check != check_minute_interval:
                # 1. 更新所有角色的时间记忆
                await update_all_roles_time_memory(time_info)
                
                # 2. 更新生理休息状态
                await asyncio.to_thread(update_rest_states)
                
                # 3. 🔥 神视角 AI 触发逻辑
                # 因为是本地 AI，这里建议对每个角色独立判断或生成一个全局旁白
                if random.random() < 0.3:  # 30% 概率触发
                    roles = list_roles()
                    for role_name in roles:
                        # 排除掉 'user'，只给 NPC 生成旁白感知
                        if role_name.lower() == 'user':
                            continue
                            
                        # 调用生成旁白的函数（需在 memory_manager 中实现）
                        narrative = await asyncio.to_thread(generate_world_narrative, role_name)
                        
                        if narrative:
                            # 广播给前端，用于 UI 展示
                            await sio.emit('chat_message', {
                                "sender": "世界线",
                                "message": narrative,
                                "type": "narrative",
                                "role": role_name,
                                "time": current_virtual_time.strftime("%H:%M")
                            })
                            print(f"已为 {role_name} 插入神视角旁白")

                last_minute_check = check_minute_interval
            
            # 基础广播：同步虚拟时间戳给前端
            await sio.emit('accelerated_time', {'time': time_info["timestamp"]})
            
            # 每秒轮询一次
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"Error in time broadcast: {e}")
            await asyncio.sleep(1)