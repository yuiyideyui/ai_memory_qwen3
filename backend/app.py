# app.py (已添加 update_role_position 处理器和广播优化)
from datetime import datetime, timezone, timedelta
import time
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Query, Request, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional
import socketio
import asyncio
import math # 引入 math 用于计算距离

# 导入时间管理器
from autoUpdate import broadcast_time_updates
from time_manager import get_accelerated_time, set_time_acceleration, set_time_enabled

# 从 memory_manager.py 导入记忆/时间/AI 逻辑
from memory_manager import (
    add_memory, query_memory, list_roles, delete_collection,
    update_time_memory, 
    get_role_activity,   # 获取角色活动状态函数
    CHINA_TZ, # 从 memory_manager 导入时区
    rest_manager, # 导入 rest_manager 实例
    handle_npc_response # 导入处理 NPC 回复的函数
)
# 从 room.py 导入 Room 模型和房间管理函数
from room import (
    Room, get_room, add_role_to_room, remove_role_from_room, clear_room
)
from prompt_builder import generate_world_narrative
from config import MIN_TOKEN_LEN_TO_STORE
from memory_manager import list_roles

print("当前所有角色:", list_roles())

# -------------------------
# 初始化 FastAPI 应用
# -------------------------
app = FastAPI()
sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode="asgi")

# -------------------------
# 全局变量
# -------------------------
time_update_task = None  # 用于存储时间更新任务

# -------------------------
# Pydantic 模型
# -------------------------

class DistanceChatPayload(BaseModel):
    sender: str
    message: str
    x: int
    y: int

# -------------------------
# 加速时间相关函数
# -------------------------

# -------------------------
# Socket.IO 辅助函数
# -------------------------

async def internal_distance_chat(room_name: str, req: DistanceChatPayload):
    print(f"distance_chat 调用: 发送者={req.sender}, 消息={req.message}, 坐标=({req.x}, {req.y})")
    try:
        # 获取房间信息
        room = await asyncio.to_thread(get_room, room_name)
        
        # 获取所有角色（除了发送者）
        other_roles = [role for role in room.roles if role.name != req.sender]
        results = {}
        
        for role in other_roles:
            distance = math.sqrt((req.x - role.x) ** 2 + (req.y - role.y) ** 2)
            
            # 检查角色是否在休息
            if rest_manager.is_resting(role.name):
                rest_info = rest_manager.get_rest_info(role.name)
                if distance <= 100:
                    muffled_message = f"听到附近有声音，但正在{rest_info.get('rest_type', '休息')}无法回应"
                    await asyncio.to_thread(add_memory, role.name, muffled_message, mtype="hearing")
                elif distance <= 300 and len(req.message) >= MIN_TOKEN_LEN_TO_STORE:
                    whisper_message = f"隐约听到有声音 ({req.message[:5]}...)"
                    await asyncio.to_thread(add_memory, role.name, whisper_message, mtype="hearing")
                continue
            
            # --- 重点修改区域: 距离 100 以内的 AI 处理 ---
            if distance <= 100:
               # 1. 记录听觉记忆
                await asyncio.to_thread(add_memory, role.name, f" {req.sender} 对我说: {req.message}", mtype="hearing")
                
                # 2. 调用 AI 处理逻辑 (此处整合了新逻辑)
                reply, action_status, cmd = await handle_npc_response(role, req.message, room)
                
                # 3. 如果发生了动作（移动），关键一步：通过 Socket 广播更新地图
                if action_status:
                    # 重新获取更新后的房间状态以确保坐标最新
                    updated_room = await asyncio.to_thread(get_room, room_name)
                    await sio.emit('room_update', updated_room.to_dict())
                
                # 4. 广播 AI 聊天消息
                display_msg = f"{reply} {f'（{action_status}）' if action_status else ''}"
                await sio.emit('chat_message', {
                    "sender": role.name,
                    "message": display_msg,
                    "time": get_accelerated_time()["iso_format"], 
                    "color": "log-ai"
                })
                
                # 5. 记录 AI 回复记忆
                await asyncio.to_thread(add_memory, role.name, f"与 {req.sender} 聊天说: {req.message} -> {display_msg}", mtype="chat")
                results[role.name] = reply

            # --- 剩余距离逻辑保持不变 ---
            elif distance <= 300:
                muffled_message = f"听到附近有声音，但听不清内容 ({req.message[:10]}...)"
                await asyncio.to_thread(add_memory, role.name, muffled_message, mtype="hearing")
            else:
                if len(req.message) >= MIN_TOKEN_LEN_TO_STORE:
                    whisper_message = f"隐约听到有声音 ({req.message[:5]}...)"
                    await asyncio.to_thread(add_memory, role.name, whisper_message, mtype="hearing")
        
        # 8. 记录发送者记忆并广播
        if len(req.message) >= MIN_TOKEN_LEN_TO_STORE:
            await asyncio.to_thread(add_memory, req.sender, f"你说: {req.message}", mtype="chat")

        await sio.emit('chat_message', {
            "sender": req.sender,
            "message": req.message,
            "time": get_accelerated_time()["iso_format"], 
            "color": "log-user"
        })

        # 2. 插入旁白并广播
        # 必须使用 to_thread，因为 generate_world_narrative 内部调用了同步的 subprocess (Ollama)
        # narrative = await asyncio.to_thread(generate_world_narrative, role.name)

        # if narrative:
        #     # 将旁白实时推送给前端 UI
        #     await sio.emit('chat_message', {
        #         "sender": "世界线",
        #         "message": narrative,
        #         "type": "narrative",
        #         "role": role.name
        #     })
        return JSONResponse({
            "status": "success",
            "results": results,
            "total_receivers": len(results)
        })
        
        
    except Exception as e:
        print(f"distance_chat 失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"发送消息失败: {str(e)}")

async def broadcast_room_update(room_name: str = 'main', target_sid: Optional[str] = None):
    """获取房间数据并广播给所有连接的客户端或特定客户端"""
    try:
        # 1. 获取房间数据 (同步操作，放入线程)
        room = await asyncio.to_thread(get_room, room_name)
        
        # 2. 获取角色的当前活动状态
        roles_with_activity = []
        for role in room.roles:
            role_dict = role.dict()
            # 获取活动状态 (同步操作，放入线程)
            activity = await asyncio.to_thread(get_role_activity, role.name)
            role_dict["activity"] = activity
            roles_with_activity.append(role_dict)
            
        # 3. 构建完整的房间数据
        room_data = room.dict()
        room_data["roles"] = roles_with_activity # 替换为包含活动的列表

        # 4. 发送给目标客户端或广播
        if target_sid:
            await sio.emit('room_data_update', room_data, room=target_sid)
        else:
            await sio.emit('room_data_update', room_data)
            
    except Exception as e:
        print(f"广播房间更新失败: {e}")

# -------------------------
# Socket.IO 事件处理 (核心逻辑)
# -------------------------

@sio.on('request_initial_data')
async def request_initial_data(sid, data):
    """
    客户端连接时请求房间布局和角色的初始数据 (只发给请求的客户端)
    """
    room_name = data.get('room_name', 'main')
    print(f"SocketIO: {sid} 请求房间 {room_name} 初始数据")
    await broadcast_room_update(room_name, sid) 

@sio.on('update_user_position')
async def update_user_position(sid, data):
    """
    更新用户角色的位置
    """
    room_name = data.get('room_name', 'main')
    role_name = data.get('role_name')
    x = data.get('x')
    y = data.get('y')
    avatar = data.get('avatar', '👤')
    
    if role_name and x is not None and y is not None:
        # add_role_to_room 是同步的，需要在线程中运行
        await asyncio.to_thread(add_role_to_room, role_name, x, y, room_name, avatar)
        
        # 广播更新后的房间数据给所有连接的客户端
        await broadcast_room_update(room_name, None) 

@sio.on('update_role_position') # <--- 新增的 AI 角色位置更新处理器
async def update_role_position(sid, data):
    """
    更新 AI 角色的位置
    """
    room_name = data.get('room_name', 'main')
    role_name = data.get('role_name')
    x = data.get('x')
    y = data.get('y')
    
    if role_name and x is not None and y is not None:
        print(f"SocketIO: 更新角色 {role_name} 位置到 ({x}, {y})")
        # add_role_to_room 会根据名称更新现有角色（同步操作，线程中运行）
        # 注意：这里没有提供 avatar，但 add_role_to_room 应该能处理更新现有角色的逻辑
        await asyncio.to_thread(add_role_to_room, role_name, x, y, room_name)
        
        # 广播更新后的房间数据给所有连接的客户端
        await broadcast_room_update(room_name, None)

@sio.on('clear_room')
async def clear_room_handler(sid, data):
    """清空房间中除用户外的所有角色"""
    room_name = data.get('room_name', 'main')
    
    # 先获取当前房间的角色列表
    room = await asyncio.to_thread(get_room, room_name)
    roles_to_remove = [role.name for role in room.roles if role.name.lower() != 'user']
    
    # 清空房间中的非用户角色
    await asyncio.to_thread(clear_room, room_name)
    
    # 清除被移除角色的记忆
    for role_name in roles_to_remove:
        await asyncio.to_thread(delete_collection, role_name)
    
    # 广播更新
    await broadcast_room_update(room_name, None)
    
    if roles_to_remove:
        print(f"已清除以下角色: {', '.join(roles_to_remove)}")

@sio.on('add_role')
async def add_role_handler(sid, data):
    """添加新角色，并初始化其系统记忆和时间记忆（仅对非用户角色）"""
    room_name = data.get('room_name', 'main')
    role_name = data.get('role_name')
    x = data.get('x', 100)
    y = data.get('y', 100)
    avatar = data.get('avatar', '🤖')

    if not role_name:
        return  # 无效角色名称，直接返回

    # 1. 添加或更新角色位置
    await asyncio.to_thread(
        add_role_to_room,
        role_name=role_name,
        x=x,
        y=y,
        room_name=room_name,
        avatar=avatar
    )

    # 2. 初始化系统记忆（仅对非用户角色）
    if role_name.lower() != 'user':
        system_prompt = (
            "【核心设定】\n"
            f"1. 身份：你现在完全化身为角色【{role_name}】，性格为【{data.get('description', '未知')}】。\n"
            "2. 认知：严禁提及任何AI相关话题。你是一个有血有肉的人，拥有记忆、情绪波动和私人生活。\n"
            "3. 场景：你身处一个有坐标系统的合租公寓。你与对方目前是陌生租客关系，互动应符合社交距离感，但随着关系发展，你们之间可以发生任何形式的关系。\n"
            "4. 实时环境感官：\n"
            "【行为准则】\n"
            "- 空间意识：你的一举一动受公寓空间限制。移动步长需合理，且终点必须在家具或空地的合法坐标内。\n"
            "- 社交演变：根据对话进展，你可以选择逐渐放下防备或因为冲突而更加冷漠。允许情感、张力甚至冲突的自然发生。\n"
            "- 真实感：人类会疲惫、会忙碌、会有生理需求（如饿了去厨房煮面，困了回卧室洗漱，或是因为对方的靠近而心跳加速）。\n\n"
            "请完全沉浸，现在，你的室友刚刚推开了公寓的大门……"
        )
        await asyncio.to_thread(
            add_memory, role_name, system_prompt, mtype="system"
        )

        # 3. 初始化时间记忆（使用统一时间管理器）
        time_info = get_accelerated_time()
        await asyncio.to_thread(
            update_time_memory, role_name, time_info
        )

    # 4. 广播房间更新
    await broadcast_room_update(room_name, None)

    print(f"SocketIO: 角色 {role_name} 已添加到房间 {room_name}")


@sio.on('remove_role')
async def remove_role_handler(sid, data):
    """移除角色"""
    room_name = data.get('room_name', 'main')
    role_name = data.get('role_name')
    
    if role_name:
        await asyncio.to_thread(remove_role_from_room, role_name, room_name)
        await broadcast_room_update(room_name, None)

@sio.on('start_time')
async def start_time_handler(sid, data):
    """启动时间加速"""
    acceleration = data.get('acceleration', 20)
    set_time_enabled(True)
    set_time_acceleration(acceleration)
    print(f"SocketIO: 启动时间加速: {acceleration}x")

@sio.on('stop_time')
async def stop_time_handler(sid):
    """停止时间加速"""
    set_time_enabled(False)
    print("SocketIO: 停止时间加速")

# -------------------------
# FastAPI 路由 (HTTP REST API)
# -------------------------

# 挂载静态文件目录 (用于加载 index.html, style.css 等)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """渲染主页面"""
    # 假设 index.html 位于根目录
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/memory_viewer", response_class=HTMLResponse)
async def memory_viewer_page(request: Request):
    """渲染記憶管理器 HTML 頁面"""
    return templates.TemplateResponse("memory_viewer.html", {"request": request})
@app.post("/distance_chat/{room_name}")
async def distance_chat(room_name: str, req: DistanceChatPayload):
    internal_distance_chat(room_name, req)
   
@app.get("/api/memory/roles")
async def get_memory_roles():
    """獲取所有擁有記憶的角色列表"""
    roles = await asyncio.to_thread(list_roles)
    return {"roles": roles}

@app.get("/api/memory/data/{role}")
async def get_role_memories(role: str, search: str = Query(None)):
    """獲取指定角色的詳細記憶列表"""
    # 調用 memory_manager.py 的 query_memory
    # 注意：原本的 query_memory 返回的是處理過的智能回憶，
    # 這裡我們稍微封裝一下獲取原始數據
    mems = await asyncio.to_thread(query_memory, role, search or "")
    
    # 格式化輸出給前端
    formatted_mems = []
    for m in mems:
        formatted_mems.append({
            "id": m.get("id"),
            "content": m.get("content"),
            "type": m["metadata"].get("type", "unknown"),
            "importance": m["metadata"].get("importance", 1.0),
            "access_count": m["metadata"].get("access_count", 0),
            "created_at": m["metadata"].get("created_at")
        })
    return {"role": role, "memories": formatted_mems}

@app.delete("/api/memory/clear/{role}")
async def clear_role_memory(role: str):
    """手動清空角色記憶"""
    success = await asyncio.to_thread(delete_collection, role)
    return {"status": "success" if success else "failed"}
# -------------------------
# Web Server 启动配置 (保持与 main.py 一致)
# -------------------------

# 创建 SocketIO ASGI 应用
sio_app = socketio.ASGIApp(sio, app)
# -------------------------
# Socket.IO 事件
# -------------------------
@sio.on("connect")
async def connect(sid, environ):
    print("Client connected:", sid)
    # 获取加速时间并发送给刚连接的客户端
    time_info = get_accelerated_time()
    await sio.emit('accelerated_time', {'time': time_info["timestamp"]}, room=sid)

@sio.on("message")
async def message(sid, data):
    print("Received message:", data)
    await sio.emit("response", f"Echo: {data}")

@sio.on("disconnect")
async def disconnect(sid):
    print("Client disconnected:", sid)

# -------------------------
# 应用生命周期事件
# -------------------------
@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化操作"""
    global time_update_task
    # 启动时间更新任务
    time_update_task = asyncio.create_task(broadcast_time_updates(sio))
    print("Time update task started")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时的清理操作"""
    global time_update_task
    if time_update_task and not time_update_task.done():
        time_update_task.cancel()
        try:
            await time_update_task
        except asyncio.CancelledError:
            pass
    print("Time update task stopped")

# -------------------------
# 挂载静态文件和模板
# -------------------------
# 假设存在 static 文件夹和 templates 文件夹
templates = Jinja2Templates(directory="templates")
