# autoUpdate.py
import asyncio
import random
import math  # 导入用于计算距离


from util import process_message
from prompt_builder import generate_world_narrative
from memory_manager import (
    add_memory,
    list_roles, 
    update_rest_states, 
    update_time_memory, 
    handle_npc_response,
    rest_manager
)
from time_manager import get_accelerated_time
from room import get_room

def calculate_distance(p1, p2):
    """计算两个坐标点之间的距离"""
    return math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)

async def update_all_roles_time_memory(time_info: dict):
    """为所有角色更新时间记忆（每10分钟调用）"""
    try:
        virtual_time = time_info["virtual_time"]
        roles = list_roles()
        for role in roles:
            await asyncio.to_thread(update_time_memory, role, time_info)
        print(f"为 {len(roles)} 个角色更新时间记忆: {virtual_time.isoformat()}")
    except Exception as e:
        print(f"更新角色时间记忆失败: {e}")

async def broadcast_time_updates(sio):
    """定期广播时间并触发 NPC 自主决策（含主动找附近的人聊天）"""
    last_minute_check = None
    
    while True:
        try:
            time_info = get_accelerated_time()
            current_virtual_time = time_info["virtual_time"]
            
            # 每 10 虚拟分钟逻辑检查
            current_minute = current_virtual_time.minute
            check_minute_interval = current_minute // 10 
            
            if last_minute_check != check_minute_interval:
                await update_all_roles_time_memory(time_info)
                await asyncio.to_thread(update_rest_states)
                
                roles_names = list_roles()
                room_obj = get_room()

                for role_name in roles_names:
                    if role_name.lower() == 'user': continue
                    if rest_manager.is_resting(role_name): continue

                    # --- 自主決策觸發 (例如 30% 概率) ---
                    if random.random() < 0.3:
                        role_obj = next((r for r in room_obj.roles if r.name == role_name), None)
                        if not role_obj: continue

                        print(f"--- [NPC自主行動] {role_name} 正在思考... ---")
                        
                        # 調用 AI 獲取回覆和指令
                        reply, action_status, cmd = await handle_npc_response(
                            role=role_obj,
                            user_message="", # 自主行動時 user_message 為空
                            room=room_obj
                        )
                        
                        # 使用您之前定義好的 Python 版 process_message 清洗文本
                        reply = process_message(reply)
                        
                        if reply:
                            # 1. 為了防止循環導入，在函數內部 import
                            import app
                            
                            # 2. 封裝 Payload 並調用空間對話邏輯
                            payload = app.DistanceChatPayload(
                                sender=role_name,
                                message=reply,
                                x=role_obj.x,
                                y=role_obj.y
                            )
                            
                            await app.internal_distance_chat(
                                room_name='main',
                                req=payload
                            )
                            
                            # --- 🔥 核心修改：一旦有人觸發並成功發言，立刻退出循環 ---
                            print(f"--- [NPC自主行動] {role_name} 已觸發行動，停止本次輪詢 ---")
                            break
                                

                # 3. 🔥 原有的神视角旁白逻辑
                # if random.random() < 0.2: 
                #     for role_name in roles_names:
                #         if role_name.lower() == 'user': continue
                #         narrative = await asyncio.to_thread(generate_world_narrative, role_name)
                #         if narrative:
                #             await sio.emit('chat_message', {
                #                 "sender": "世界线",
                #                 "message": narrative,
                #                 "type": "narrative",
                #                 "role": role_name,
                #                 "time": current_virtual_time.strftime("%H:%M")
                #             })

                last_minute_check = check_minute_interval
            
            await sio.emit('accelerated_time', {'time': time_info["timestamp"]})
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"Error in auto-update loop: {e}")
            await asyncio.sleep(1)