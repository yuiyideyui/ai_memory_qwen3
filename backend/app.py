# app.py
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

# 从 memory_manager.py 导入记忆/时间/AI 逻辑
# 注意：update_rest_states 是同步的，需要在 app.py 中用 asyncio.to_thread 调用
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

# -------------------------
# 初始化 FastAPI 应用
# -------------------------
app = FastAPI()
sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode="asgi")
# 绑定 Socket.IO
sio_app = socketio.ASGIApp(sio, app)

# -------------------------
# 全局变量
# -------------------------
time_update_task = None  # 用于存储时间更新任务
TIME_ACCELERATION_MULTIPLIER = 20 # 默认加速倍数
ACCELERATED_TIME_ENABLED = True # 默认开启加速，与用户逻辑保持一致


# -------------------------
# 加速时间相关函数
# -------------------------
# 使用全局变量来跟踪时间偏移，以实现平滑加速
current_time_offset = timedelta(seconds=0)
last_real_time = time.time()

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

async def update_all_roles_time_memory(time_info: dict):
    """为所有角色更新时间记忆（每10分钟调用）"""
    try:
        virtual_time = time_info["virtual_time"]
        roles = list_roles()
        
        # update_time_memory 可能涉及同步的 ChromaDB I/O，使用 to_thread
        await asyncio.to_thread(
            lambda: [update_time_memory(role, time_info) for role in roles]
        )
        
        print(f"为 {len(roles)} 个角色更新时间记忆: {virtual_time.isoformat()}")
        
    except Exception as e:
        print(f"更新角色时间记忆失败: {e}")

async def broadcast_time_updates():
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
            
            if ACCELERATED_TIME_ENABLED and last_minute_check != check_minute_interval:
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
    time_update_task = asyncio.create_task(broadcast_time_updates())
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
    global ACCELERATED_TIME_ENABLED
    ACCELERATED_TIME_ENABLED = not ACCELERATED_TIME_ENABLED
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

            # 3. 初始化时间记忆
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

@app.post("/distance_chat")
async def distance_chat(req: DistanceChatRequest):
    """基于距离的聊天功能 - 带AI回复（考虑休息状态）"""
    try:
        # 获取房间信息 (同步 I/O)
        room = await asyncio.to_thread(get_room, req.room_name)
        
        # 假设 room.get_roles_by_distance_tiers 和 room.calculate_distance 是存在的 Room 方法
        # 为了避免阻塞，将同步调用移到 to_thread
        distance_tiers = await asyncio.to_thread(room.get_roles_by_distance_tiers, req.user_x, req.user_y)
        
        results = []
        
        # 处理近距离角色
        for role_info in distance_tiers["very_close"]:
            role_name = role_info["name"]
            if role_name != "user":
                
                distance = await asyncio.to_thread(room.calculate_distance, req.user_x, req.user_y, role_info["x"], role_info["y"])
                
                # 检查角色是否在休息
                if rest_manager.is_resting(role_name):
                    rest_info = rest_manager.get_rest_info(role_name)
                    results.append({
                        "role_name": role_name,
                        "distance": distance,
                        "message_received": req.message,
                        "message_type": "resting",
                        "ai_reply": f"{role_name}正在{rest_info.get('rest_type', '休息')}，没有回应",
                        "is_resting": True
                    })
                    continue
                
                # 正常交流
                hearing_memory = f"{req.role_name}: {req.message}"
                await asyncio.to_thread(add_memory, role_name, hearing_memory, mtype="hearing")
                
                mems = await asyncio.to_thread(query_memory, role_name, req.message, top_k=5) # 减少 top_k 以提高性能
                prompt = build_prompt(f"回应这句话: {req.message}", mems)
                
                # 异步调用同步模型
                ai_reply = await asyncio.to_thread(run_ollama_sync, prompt)
                
                await asyncio.to_thread(add_memory, role_name, f"我回应了: {ai_reply}", mtype="response")
                
                results.append({
                    "role_name": role_name,
                    "distance": distance,
                    "message_received": req.message,
                    "message_type": "clear",
                    "ai_reply": ai_reply,
                    "is_resting": False
                })
        
        # 处理中距离角色（能模糊听到） - 仅将消息记录到记忆，不立即回复
        for role_info in distance_tiers["close"]:
            role_name = role_info["name"]
            if role_name != "user":
                muffled_message = f"听到附近有声音，但听不清内容 ({req.message[:10]}...)"
                await asyncio.to_thread(add_memory, role_name, muffled_message, mtype="hearing")
                
                # 仅记录，不立即产生 AI 回复，避免过多不必要的计算
                
        # 处理远距离角色（只能偶尔听到） - 仅将消息记录到记忆，不立即回复
        for role_info in distance_tiers["far"]:
            role_name = role_info["name"]
            if role_name != "user":
                # 只有重要内容才传递（例如，如果消息长度大于 MIN_TOKEN_LEN_TO_STORE）
                if len(req.message) >= MIN_TOKEN_LEN_TO_STORE:  
                    whisper_message = f"隐约听到有声音 ({req.message[:5]}...)"
                    await asyncio.to_thread(add_memory, role_name, whisper_message, mtype="hearing")
        
        return JSONResponse({
            "status": "success",
            "message": "消息已发送",
            "results": results,
            "total_receivers": len(distance_tiers["very_close"])
        })
        
    except Exception as e:
        print(f"distance_chat 失败: {e}")
        raise HTTPException(status_code=500, detail=f"发送消息失败: {str(e)}")

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