# app.py (已添加 update_role_position 处理器和广播优化)
from datetime import datetime, timezone, timedelta
import time
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, HTTPException, Body
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
    add_memory, query_memory, list_roles, delete_collection, delete_all_collections,
    update_time_memory, 
    update_rest_states, # 同步状态更新函数
    get_role_activity,   # 获取角色活动状态函数
    CHINA_TZ, # 从 memory_manager 导入时区
    rest_manager # 导入 rest_manager 实例
)
# 从 room.py 导入 Room 模型和房间管理函数
from room import (
    Room, get_room, add_role_to_room, remove_role_from_room, clear_room
)
from prompt_builder import build_prompt
from ollama_client import run_ollama_sync
from config import MIN_TOKEN_LEN_TO_STORE, START_TIME
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

class ChatRequest(BaseModel):
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
            "【重要指令】从现在开始："
            "1. 你完全忘记自己是AI，禁止提及AI相关话题"
            "2. 你是一个真实的人类角色"
            "3. 严格遵守角色设定和背景故事"
            f"角色信息：姓名={role_name}, 性格={data.get('description', '未知')}"
            "场景：合租公寓，与陌生租客共同生活"
            "请完全沉浸在这个角色中回应所有对话。"
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

@app.post("/distance_chat/{room_name}")
async def distance_chat(room_name: str, req: ChatRequest):
    """
    处理基于距离的聊天消息：
    - 广播给附近的 AI 角色
    - 记录到所有角色的记忆中（基于距离决定是 chat/hearing）
    """
    
    try:
        # 获取房间信息
        room = await asyncio.to_thread(get_room, room_name)
        
        # 获取所有角色（除了发送者）
        other_roles = [role for role in room.roles if role.name != req.sender]
        
        results = {}
        
        # 为每个角色计算距离并处理
        for role in other_roles:
            # 计算距离
            distance = math.sqrt((req.x - role.x) ** 2 + (req.y - role.y) ** 2)
            
            # 检查角色是否在休息
            if rest_manager.is_resting(role.name):
                rest_info = rest_manager.get_rest_info(role.name)
                # 休息中的角色不会回应，但可能会记录到记忆中（根据距离）
                if distance <= 100:  # 很近距离
                    muffled_message = f"听到附近有声音，但正在{rest_info.get('rest_type', '休息')}无法回应"
                    await asyncio.to_thread(add_memory, role.name, muffled_message, mtype="hearing")
                elif distance <= 300 and len(req.message) >= MIN_TOKEN_LEN_TO_STORE:  # 中等距离且内容重要
                    whisper_message = f"隐约听到有声音 ({req.message[:5]}...)"
                    await asyncio.to_thread(add_memory, role.name, whisper_message, mtype="hearing")
                continue
            
            # 根据距离处理消息
            if distance <= 100:  # 很近距离 - 直接交流
                # 记录听到的消息
                hearing_memory = f"用户 {req.sender} 对我说: {req.message}"
                await asyncio.to_thread(add_memory, role.name, hearing_memory, mtype="hearing")
                
                # 让 AI 思考并回复
                memories = await asyncio.to_thread(query_memory, role.name, req.message, top_k=5)
                prompt = build_prompt(
                    user_input=f"用户 {req.sender} 对你说: {req.message}",
                    memories=memories
                )
                
                # 调用 Ollama
                response_text = await asyncio.to_thread(run_ollama_sync, prompt)
                
                # 记录对话记忆
                await asyncio.to_thread(add_memory, role.name, f"与 {req.sender} 聊天: {req.message} -> {response_text}", mtype="chat")
                
                # 广播回复
                await sio.emit('chat_message', {
                    "sender": role.name,
                    "message": response_text,
                    "time": get_accelerated_time()["iso_format"], 
                    "color": "log-ai"
                })
                
                results[role.name] = response_text
                
            elif distance <= 300:  # 中等距离 - 模糊听到
                muffled_message = f"听到附近有声音，但听不清内容 ({req.message[:10]}...)"
                await asyncio.to_thread(add_memory, role.name, muffled_message, mtype="hearing")
                
            else:  # 远距离 - 只有重要内容才记录
                if len(req.message) >= MIN_TOKEN_LEN_TO_STORE:
                    whisper_message = f"隐约听到有声音 ({req.message[:5]}...)"
                    await asyncio.to_thread(add_memory, role.name, whisper_message, mtype="hearing")
        
        # 记录用户自身的记忆
        if len(req.message) >= MIN_TOKEN_LEN_TO_STORE:
            await asyncio.to_thread(add_memory, req.sender, f"对 AI 们说: {req.message}", mtype="chat")

        # 广播用户消息（让所有客户端显示用户消息）
        await sio.emit('chat_message', {
            "sender": req.sender,
            "message": req.message,
            "time": get_accelerated_time()["iso_format"], 
            "color": "log-user"
        })
        
        return JSONResponse({
            "status": "success",
            "message": "消息已发送",
            "results": results,
            "total_receivers": len(results)  # 只计算实际回复的角色数量
        })
        
    except Exception as e:
        print(f"distance_chat 失败: {e}")
        raise HTTPException(status_code=500, detail=f"发送消息失败: {str(e)}")


# -------------------------
# Web Server 启动配置 (保持与 main.py 一致)
# -------------------------

# 创建 SocketIO ASGI 应用
sio_app = socketio.ASGIApp(sio, app)

# -------------------------
# 请求模型
# -------------------------
class ChatRequest(BaseModel):
    user_input: str
    role: str
    autostore: bool = True

class ClearMemoryRequest(BaseModel):
    role: str

class RestStateRequest(BaseModel):
    role: str
    is_resting: bool
    rest_type: Optional[str] = "sleep"

class PositionUpdate(BaseModel):
    x: int
    y: int

class NewRole(BaseModel):
    name: str
    x: int
    y: int
    avatar: Optional[str] = "👤"
    description: Optional[str] = None # 用于系统提示
    type: Optional[str] = "ai"

class DistanceChatRequest(BaseModel):
    user_x: int
    user_y: int
    message: str
    role_name: str
    room_name: str = "main"

# -------------------------
# 存储判断逻辑
# -------------------------
def should_store(text: str) -> bool:
    """判断消息是否应该存储到记忆中"""
    # 假设 MIN_TOKEN_LEN_TO_STORE 来自 config.py
    return bool(text and len(text.strip()) >= MIN_TOKEN_LEN_TO_STORE)

# -------------------------
# 页面路由
# -------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """返回主页 HTML"""
    roles = list_roles()
    return templates.TemplateResponse("index.html", {"request": request, "roles": roles})

@app.get("/chromadb", response_class=HTMLResponse)
def chromadb_viewer(request: Request):
    """ChromaDB 查看器页面"""
    roles = list_roles()
    return templates.TemplateResponse("chromadb_viewer.html", {"request": request, "roles": roles})


# -------------------------
# 记忆、休息状态和统计 API 路由
# -------------------------

@app.post("/chat")
async def chat(req: ChatRequest):
    """通用聊天接口（非基于距离）"""
    # 🔥 检查角色是否在休息状态
    if rest_manager.is_resting(req.role):
        rest_info = rest_manager.get_rest_info(req.role)
        return JSONResponse({
            "reply": f"【休息中】{req.role}正在{rest_info.get('rest_type', '休息')}，暂时无法回应。",
            "stored": False,
            "is_resting": True,
            "rest_type": rest_info.get('rest_type')
        })
    
    # 异步调用同步函数
    mems = await asyncio.to_thread(query_memory, req.role, req.user_input, top_k=100000)
    
    prompt = build_prompt(req.user_input, mems)
    
    # 异步调用同步函数
    reply = await asyncio.to_thread(run_ollama_sync, prompt)

    stored = False
    if req.autostore and should_store(req.user_input):
        # add_memory 可能涉及同步 I/O
        await asyncio.to_thread(add_memory, req.role, req.user_input, mtype="conversation")
        stored = True
    
    # 存储角色的回复
    await asyncio.to_thread(add_memory, req.role, reply, mtype="response")

    return JSONResponse({
        "reply": reply, 
        "stored": stored,
        "is_resting": False
    })

@app.get("/api/roles")
def api_get_roles():
    """获取所有角色列表"""
    return {"roles": list_roles()}

@app.post("/api/time/toggle")
def api_toggle_time():
    """切换时间加速状态"""
    set_time_enabled(not ACCELERATED_TIME_ENABLED)
    message = "时间加速已开启" if ACCELERATED_TIME_ENABLED else "时间加速已暂停"
    return JSONResponse({"status": "success", "message": message, "enabled": ACCELERATED_TIME_ENABLED})

@app.get("/api/time/status")
def api_get_time_status():
    """获取当前时间状态"""
    time_info = get_accelerated_time()
    return JSONResponse({
        "timestamp": time_info["timestamp"],
        "iso_format": time_info["iso_format"],
        "multiplier": time_info["multiplier"]
    })

@app.post("/api/rest_state")
def api_set_rest_state(req: RestStateRequest):
    """手动设置角色休息状态"""
    rest_manager.set_rest_state(req.role, req.is_resting, req.rest_type)
    return {"msg": f"角色 {req.role} 休息状态已更新"}

@app.get("/api/rest_state/{role_name}")
def api_get_rest_state(role_name: str):
    """获取角色休息状态"""
    rest_info = rest_manager.get_rest_info(role_name)
    return JSONResponse(rest_info)

@app.post("/api/update_rest_states")
async def api_update_all_rest_states():
    """更新所有角色的休息状态"""
    await asyncio.to_thread(update_rest_states)
    return {"msg": "所有角色休息状态已更新"}

@app.get("/api/role/{role_name}/memories")
async def api_get_role_memories(role_name: str):
    """获取指定角色的所有记忆"""
    try:
        # 查询角色的所有记忆 (同步 I/O)
        memories = await asyncio.to_thread(query_memory, role_name, "", top_k=100000)
        
        # 格式化记忆数据
        formatted_memories = []
        for mem in memories:
            formatted_memories.append({
                "content": mem["content"],
                "type": mem["metadata"]["type"],
                "length": len(mem["content"])
            })
        
        return JSONResponse({
            "role": role_name,
            "memories": formatted_memories,
            "count": len(formatted_memories)
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取记忆失败: {str(e)}")

@app.delete("/api/role/{role_name}/memories")
def api_clear_role_memories(role_name: str):
    """清空指定角色的记忆"""
    try:
        # delete_collection 是同步的
        if delete_collection(role_name):
            return JSONResponse({"status": "success", "message": f"角色 {role_name} 的记忆已清空"})
        else:
            raise HTTPException(status_code=500, detail="清除记忆失败")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清除记忆失败: {str(e)}")

@app.post("/api/clear_all_memories")
def api_clear_all_memories():
    """删除所有角色的记忆 collection"""
    if not delete_all_collections():
        raise HTTPException(status_code=500, detail="清除所有角色记忆失败")

    return JSONResponse({"status": "success", "message": "所有角色记忆已清除"})

@app.get("/api/stats")
async def api_get_stats():
    """获取 ChromaDB 统计信息"""
    try:
        roles = list_roles()
        stats = []
        total_memories = 0
        
        for role_name in roles:
            try:
                # query_memory 是同步的
                memories = await asyncio.to_thread(query_memory, role_name, "", top_k=100000)
                count = len(memories)
                stats.append({
                    "role": role_name,
                    "count": count
                })
                total_memories += count
            except:
                stats.append({
                    "role": role_name,
                    "count": 0
                })
        
        return JSONResponse({
            "total_roles": len(roles),
            "total_memories": total_memories,
            "roles_stats": stats
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


# ------------------------
# 房间和角色管理 API 路由
# ------------------------

@app.get("/api/room/{room_name}", response_model=Room)
async def api_get_room(room_name: str):
    """
    获取指定房间的完整数据，包括布局和所有角色。
    """
    try:
        # get_room 是同步的
        room = await asyncio.to_thread(get_room, room_name)
        # 确保所有角色的 activity 字段是新的
        for role in room.roles:
            # get_role_activity 是同步的
            role.activity = await asyncio.to_thread(get_role_activity, role.name)
        return room
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取房间数据失败: {str(e)}")


@app.post("/api/room/{room_name}/clear")
async def api_clear_room(room_name: str):
    """
    清空指定房间中的所有非用户角色。
    """
    try:
        await asyncio.to_thread(clear_room, room_name)
        # 通知所有客户端房间已更新
        room = await asyncio.to_thread(get_room, room_name)
        await sio.emit('room_update', room.model_dump())
        return JSONResponse({"status": "success", "message": f"房间 {room_name} 已清空"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清空房间失败: {str(e)}")


@app.post("/api/room/{room_name}/role")
async def api_add_role(room_name: str, new_role: NewRole):
    """
    新增角色到房间，并初始化其系统记忆和时间记忆。
    """
    try:
        # 1. 添加或更新角色位置
        await asyncio.to_thread(
            add_role_to_room, 
            role_name=new_role.name, 
            x=new_role.x, 
            y=new_role.y, 
            room_name=room_name, 
            avatar=new_role.avatar
        )
        
        # 2. 初始化系统记忆 (仅 AI 角色)
        if new_role.name.lower() != 'user':
            system_prompt = (
                "【重要指令】从现在开始："
                "1. 你完全忘记自己是AI，禁止提及AI相关话题"
                "2. 你是一个真实的人类角色"
                "3. 严格遵守角色设定和背景故事"
                f"角色信息：姓名={new_role.name}, 性格={new_role.description}"
                "场景：合租公寓，与陌生租客共同生活"
                "请完全沉浸在这个角色中回应所有对话。"
            )
            await asyncio.to_thread(add_memory, new_role.name, system_prompt, mtype="system")

            # 3. 初始化时间记忆 - 使用统一的时间信息
            time_info = get_accelerated_time()
            await asyncio.to_thread(update_time_memory, new_role.name, time_info)
        
        # 4. 通知所有客户端房间已更新
        room = await asyncio.to_thread(get_room, room_name)
        await sio.emit('room_update', room.model_dump())
        
        return JSONResponse({"status": "success", "message": f"角色 {new_role.name} 已添加到房间，记忆已初始化"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"新增角色失败: {str(e)}")


@app.put("/api/room/{room_name}/role/{role_name}/position")
async def api_update_role_position(room_name: str, role_name: str, position: PositionUpdate):
    """
    更新指定角色在房间中的位置。
    """
    try:
        # 更新角色位置
        await asyncio.to_thread(
            add_role_to_room, 
            role_name=role_name, 
            x=position.x, 
            y=position.y, 
            room_name=room_name
            # avatar 保持不变
        )
        
        # 如果是 user 移动，需要更新 rest_states
        if role_name.lower() == 'user':
             await asyncio.to_thread(update_rest_states)
        
        # 通知所有客户端房间已更新
        room = await asyncio.to_thread(get_room, room_name)
        await sio.emit('room_update', room.model_dump())
        
        return JSONResponse({"status": "success", "message": f"角色 {role_name} 位置已更新"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新角色位置失败: {str(e)}")


@app.delete("/api/room/{room_name}/role/{role_name}")
async def api_remove_role(room_name: str, role_name: str):
    """
    从房间中移除指定角色，并清除其记忆。
    """
    try:
        # 1. 从房间中移除角色
        await asyncio.to_thread(remove_role_from_room, role_name, room_name)
        
        # 2. 删除角色的记忆集合 (同步 I/O)
        if not await asyncio.to_thread(delete_collection, role_name):
            # 如果删除记忆失败，记录日志但不中断操作
            print(f"警告: 删除角色 {role_name} 的记忆失败")
        
        # 3. 通知所有客户端房间已更新
        room = await asyncio.to_thread(get_room, room_name)
        await sio.emit('room_update', room.model_dump())
        
        return JSONResponse({"status": "success", "message": f"角色 {role_name} 已从房间 {room_name} 中移除，记忆已清除"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"移除角色失败: {str(e)}")

# ------------------------
# 基于距离的聊天路由
# ------------------------
@app.get("/nearby_roles/{room_name}")
async def get_nearby_roles(room_name: str, user_x: int, user_y: int, max_distance: int = 300):
    """获取附近的角色"""
    try:
        # get_room 是同步的
        room = await asyncio.to_thread(get_room, room_name)
        # 假设 room.get_nearby_roles 是存在的 Room 方法
        nearby_roles = await asyncio.to_thread(room.get_nearby_roles, user_x, user_y, max_distance)
        
        # 确保 activity 字段被填充
        for role in nearby_roles:
            role["activity"] = await asyncio.to_thread(get_role_activity, role["name"])
            
        return JSONResponse({
            "room_name": room_name,
            "user_position": {"x": user_x, "y": user_y},
            "nearby_roles": nearby_roles,
            "count": len(nearby_roles)
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取附近角色失败: {str(e)}")

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
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
