# memory_manager.py
import asyncio
from zoneinfo import ZoneInfo
import chromadb
from chromadb.config import Settings
from roomAsyc import RoomSenseParser
from room import get_room
from config import CHROMA_DB_DIR
import uuid
from datetime import datetime, timezone, timedelta
import re
import os
import json
from typing import List, Dict, Optional
from chromadb import Client
# 引入必要的 Pydantic 依赖
from pydantic import BaseModel, Field
import re
from ollama_client import run_ollama_sync
# 导入时间管理器
from time_manager import get_accelerated_time

# -----------------------
# 初始化 ChromaDB 客户端
# -----------------------
# ✅ 仅初始化一次，确保设置一致
client = chromadb.PersistentClient(
    path=CHROMA_DB_DIR,
    settings=Settings(allow_reset=True)  # ✅ 保持与所有地方一致
)

# 🔥 时区处理 - 兼容性更好的方式
def get_china_timezone():
    """获取中国时区，兼容不同环境"""
    try:
        # 尝试使用 zoneinfo（Python 3.9+）
        from zoneinfo import ZoneInfo
        return ZoneInfo("Asia/Shanghai")
    except ImportError:
        try:
            # 尝试使用 pytz
            import pytz
            return pytz.timezone('Asia/Shanghai')
        except ImportError:
            # 回退到 UTC 并打印警告
            print("警告: 无法找到 Asia/Shanghai 时区，使用 UTC 时区")
            return timezone.utc

# 获取时区对象
CHINA_TZ = get_china_timezone()
# -----------------------
# 工具函数
# -----------------------
def sanitize_name(name: str) -> str:
    """
    将任意字符串转换为符合 ChromaDB collection 名称规范
    """
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    sanitized = re.sub(r"^[^a-zA-Z0-9]+", "", sanitized)
    sanitized = re.sub(r"[^a-zA-Z0-9]+$", "", sanitized)
    while len(sanitized) < 3:
        sanitized += "_"
    return sanitized

# -----------------------
# Collection 管理
# -----------------------
def list_roles() -> List[str]:
    print( "Existing collections:", client.list_collections())  # 调试输出
    return [col.name for col in client.list_collections()]

def get_or_create_collection(role: str):
    role_safe = sanitize_name(role)
    existing = [c.name for c in client.list_collections()]
    print('Creating collection:', role_safe,client.list_collections())  # 调试输出
    if role_safe not in existing:
        
        return client.create_collection(name=role_safe)
    return client.get_collection(name=role_safe)

# -----------------------
# 添加记忆
# -----------------------

from config import START_TIME
# 在 memory_manager.py 中添加

class MemoryManager:
    def __init__(self):
        self.short_term_threshold = 5  # 短期记忆数量阈值
        self.importance_scores = {}    # 记忆重要性评分
        
    def calculate_importance(self, content: str, mem_type: str, role: str) -> float:
        """计算记忆重要性分数"""
        score = 1.0
        
        # 类型权重
        type_weights = {
            "system": 10.0,    # 系统指令最重要
            "narrative": 6.0,   # 新增：旁白记忆，比普通对话更重要
            "emotion": 8.0,    # 情感记忆
            "conversation": 3.0, # 对话记忆
            "hearing": 2.0,    # 听到的内容
            "response": 2.0,   # 自己的回应
            "note": 1.0        # 普通笔记
        }
        score *= type_weights.get(mem_type, 1.0)
        
        # 内容特征
        if "重要" in content or "关键" in content or "记住" in content:
            score *= 2.0
        if len(content) > 50:  # 较长内容可能更重要
            score *= 1.5
        if "?" in content:     # 问题可能更重要
            score *= 1.3
            
        return score

# 全局记忆管理器
memory_manager = MemoryManager()

def add_memory(role: str, content: str, mtype: str = "note") -> None:
    try:
        memory_id = str(uuid.uuid4())
        # 使用统一的时间管理器获取时间
        time_info = get_accelerated_time()
        timestamp = time_info["virtual_time"].isoformat()

        importance = memory_manager.calculate_importance(content, mtype, role)
        
        collection = get_or_create_collection(role)
        collection.add(
            ids=[memory_id],
            documents=[content],
            metadatas=[{
                "type": mtype, 
                "created_at": timestamp,
                "importance": importance,
                "access_count": 0
            }]
        )
        
        print(f"添加记忆: [{mtype}] 重要性:{importance:.1f} - {content[:30]}...")

    except Exception as e:
        print(f"Error adding memory: {e}")

# -----------------------
# 休息状态管理
# -----------------------
class RestStateManager:
    def __init__(self):
        self.rest_states = {}
    
    def set_rest_state(self, role: str, is_resting: bool, rest_type: str = "sleep"):
        if is_resting:
            current_time = get_accelerated_time()["virtual_time"]
            self.rest_states[role] = {
                "is_resting": True,
                "rest_start_time": current_time.isoformat(),
                "rest_type": rest_type
            }
            print(f"{current_time.isoformat()}角色 {role} 进入{rest_type}状态")
        else:
            if role in self.rest_states:
                del self.rest_states[role]
            print(f"角色 {role} 结束休息状态")
    
    def is_resting(self, role: str) -> bool:
        return self.rest_states.get(role, {}).get("is_resting", False)
    
    def get_rest_info(self, role: str) -> dict:
        return self.rest_states.get(role, {
            "is_resting": False,
            "rest_start_time": None,
            "rest_type": None
        })

rest_manager = RestStateManager()

def check_rest_state(role: str, current_time: datetime) -> dict:
    """AI决定角色是否应该休息"""
    try:
        # 简单基于时间的决策（可以扩展为AI决策）
        hour = current_time.hour
        print(f"检查角色 {role} 休息状态 - 当前时间: {current_time.isoformat()} (小时: {hour})")
        # 夜间睡眠时间（22:00-6:00）
        if 22 <= hour or hour <= 6:
            return {"should_rest": True, "rest_type": "sleep", "reason": "夜间休息时间"}
        # 午休时间（13:00-14:00）
        elif 13 <= hour <= 14:
            return {"should_rest": True, "rest_type": "nap", "reason": "午休时间"}
        else:
            return {"should_rest": False, "rest_type": None, "reason": "活动时间"}
                
    except Exception as e:
        print(f"检查角色 {role} 休息状态失败: {e}")
        return {"should_rest": False, "rest_type": None, "reason": "检查失败"}

def update_rest_states():
    """更新所有角色的休息状态"""
    try:
        current_time = get_accelerated_time()["virtual_time"]
        roles = list_roles()
        
        for role in roles:
            decision = check_rest_state(role, current_time)
            
            if decision["should_rest"]:
                rest_manager.set_rest_state(role, True, decision["rest_type"])
            else:
                if rest_manager.is_resting(role):
                    rest_manager.set_rest_state(role, False)
                    
    except Exception as e:
        print(f"更新休息状态失败: {e}")

def query_memory(role: str, query: str, top_k: int = 100000) -> List[Dict]:
    """获取所有记忆，兼容旧版本 ChromaDB"""
    role_safe = sanitize_name(role)
    existing = [c.name for c in client.list_collections()]
    if role_safe not in existing:
        return []

    collection = client.get_collection(name=role_safe)

    try:
        # 🔥 使用 get() 方法获取所有记忆（更兼容）
        # 先获取总数
        count_result = collection.count()
        total_count = count_result if isinstance(count_result, int) else count_result.get('count', 0)
        
        print(f"角色 {role} 共有 {total_count} 条记忆")
        
        if total_count == 0:
            return []
        
        # 使用 get() 获取所有记录（更可靠）
        all_results = collection.get(
            include=["documents", "metadatas"],
            limit=min(total_count, 100000)  # 限制最大获取数量
        )
        
        documents = all_results.get("documents", [])
        metadatas = all_results.get("metadatas", [])
        ids = all_results.get("ids", [])
        
        print(f"实际获取了 {len(documents)} 条记忆")
        
        # 处理记忆数据
        min_length = min(len(documents), len(metadatas), len(ids))
        
        mems = []
        for i in range(min_length):
            metadata = metadatas[i] if metadatas[i] else {
                "type": "note", 
                "created_at": "1970-01-01T00:00:00",
                "importance": 1.0,
                "access_count": 0
            }
            mems.append({
                "id": ids[i] if i < len(ids) else str(i),
                "content": documents[i],
                "metadata": metadata
            })
        
        # 更新访问计数（模拟记忆强化）
        for mem in mems:
            if "access_count" not in mem["metadata"]:
                mem["metadata"]["access_count"] = 0
            mem["metadata"]["access_count"] += 1
            
            # 更新访问计数到数据库
            try:
                collection.update(
                    ids=[mem.get("id", str(uuid.uuid4()))],
                    metadatas=[mem["metadata"]]
                )
            except Exception as e:
                print(f"更新访问计数失败: {e}")
        
        # 🔥 智能回忆算法
        recall_memories = []
        
        # 1. 系统身份记忆（最高优先级）
        system_mems = [mem for mem in mems if mem["metadata"].get("type") in ["system", "role_setup", "note"]]
        recall_memories.extend(system_mems)
        
        # 2. 时间记忆（重要背景信息）
        time_mems = [mem for mem in mems if mem["metadata"].get("type") == "time"]
        # 取最新的时间记忆
        if time_mems:
            latest_time_mem = sorted(time_mems, 
                                   key=lambda x: x["metadata"].get("created_at", "1970-01-01T00:00:00"))[-1]
            recall_memories.append(latest_time_mem)
        
        # 3. 高重要性记忆
        important_mems = [mem for mem in mems 
                         if mem["metadata"].get("importance", 1.0) > 5.0 
                         and mem["metadata"].get("type") not in ["system", "role_setup", "note", "time"]]
        recall_memories.extend(important_mems)
        
        # 4. 频繁访问记忆
        frequent_mems = [mem for mem in mems 
                        if mem["metadata"].get("access_count", 0) > 3
                        and mem["metadata"].get("type") not in ["system", "role_setup", "note", "time"]]
        recall_memories.extend(frequent_mems)
        
        # 5. 最近记忆（短期记忆）
        other_mems = [mem for mem in mems 
                     if mem not in recall_memories]  # 排除已选记忆
        recent_mems = sorted(other_mems, 
                           key=lambda x: x["metadata"].get("created_at", "1970-01-01T00:00:00"))[-8:]
        recall_memories.extend(recent_mems)
        
        # 去重（基于内容）
        unique_mems = {}
        for mem in recall_memories:
            key = mem["content"][:100]  # 基于内容去重
            if key not in unique_mems:
                unique_mems[key] = mem
        
        final_mems = list(unique_mems.values())
        
        # 按综合得分排序
        def memory_score(mem):
            importance = mem["metadata"].get("importance", 1.0)
            access_count = mem["metadata"].get("access_count", 0)
            create_time = mem["metadata"].get("created_at", "1970-01-01T00:00:00")
            time_factor = 1.0 if "1970" in create_time else 2.0
            
            # 时间记忆的特殊权重
            if mem["metadata"].get("type") == "time":
                importance *= 3.0
            
            return importance * (1 + access_count * 0.5) * time_factor
        
        final_mems.sort(key=memory_score, reverse=True)
        
        print(f"角色 {role} 智能回忆: {len(final_mems)} 条记忆（总数: {len(mems)}）")
        for i, mem in enumerate(final_mems[:5]):  # 只显示前5条
            importance = mem["metadata"].get("importance", 1.0)
            access_count = mem["metadata"].get("access_count", 0)
            mem_type = mem["metadata"].get("type", "unknown")
            print(f"  {i+1}. [{mem_type}] 重要性:{importance:.1f} 访问:{access_count} - {mem['content'][:50]}...")


        # ✅ 2. 获取并解析房间数据
        try:
            room = get_room()
            room_data = room.model_dump()
            
            # 初始化解析器
            parser = RoomSenseParser(room_data)
            room_raw_json = json.dumps(room.model_dump(), ensure_ascii=False)
            # 解析当前角色的主视角 (假设变量 role 是当前角色的名称，如 "user" 或 "yui1")
            user_view = parser.parse_for_role(role)
        except Exception as e:
            # 容错处理：如果解析失败，记录简化的错误信息，避免对话中断
            user_view = f"你当前身处室内，但视觉观察受限（解析错误: {e}）"

        # ✅ 3. 获取时间信息
        time_info = get_accelerated_time()
        timestamp = time_info["virtual_time"].isoformat()

        # ✅ 4. 写入记忆
        final_mems.append({
            "id": f"spatial_sense_{timestamp}", # 建议 ID 加上时间戳区分
            "content": user_view,
            "metadata": {
                "type": "room_state",
                "created_at": timestamp,
                "importance": 10.0,
                "access_count": 0
            }
        })
        # ✅ 4. 写入记忆
        final_mems.append({
            "id": f"room_json_{timestamp}", # 建议 ID 加上时间戳区分
            "content": room_raw_json,
            "metadata": {
                "type": "room_state",
                "created_at": timestamp,
                "importance": 10.0,
                "access_count": 0
            }
        })

        return final_mems
        
    except Exception as e:
        print(f"查询记忆失败: {e}")
        import traceback
        traceback.print_exc()
        return []


def delete_collection(role: str) -> bool:
    """删除指定角色的记忆 collection"""
    try:
        role_safe = sanitize_name(role)
        # 检查集合是否存在
        existing_collections = [c.name for c in client.list_collections()]
        if role_safe in existing_collections:
            client.delete_collection(name=role_safe)
            return True
        else:
            # 集合不存在，也算删除成功（幂等操作）
            return True
    except Exception as e:
        print(f"删除角色 {role} 记忆失败: {e}")
        return False



def delete_all_collections():
    """删除所有角色的记忆 collection"""
    try:
        # 使用全局的 client 实例
        collections = client.list_collections()
        for col in collections:
            # ✅ 删除整个集合
            client.delete_collection(name=col.name)
        return True
    except Exception as e:
        # 捕获所有异常并记录详细信息
        print(f"删除所有集合失败: {e}")
        return False


# 在 memory_manager.py 中添加
def update_time_memory(role: str, current_time_info: dict):
    """更新时间记忆（修改或创建唯一的时间记忆）"""
    try:
        # 🔥 使用统一的时间管理器提供的时间信息
        timestamp = current_time_info["virtual_time"].isoformat()
        
        # 格式化时间记忆内容
        time_memory_content = f"当前时间：{timestamp}。"
        
        role_safe = sanitize_name(role)
        collection = get_or_create_collection(role_safe)
        
        # 查找现有的时间记忆
        existing_memories = collection.peek(limit=1000)
        documents = existing_memories.get("documents", [])
        metadatas = existing_memories.get("metadatas", [])
        ids = existing_memories.get("ids", [])
        
        time_memory_id = None
        
        # 查找时间记忆（类型为"time"）
        for i, metadata in enumerate(metadatas):
            if i < len(ids) and metadata and metadata.get("type") == "time":
                time_memory_id = ids[i]
                break
        
        if time_memory_id:
            # 更新时间记忆
            collection.update(
                ids=[time_memory_id],
                documents=[time_memory_content],
                metadatas=[{
                    "type": "time", 
                    "created_at": timestamp,
                    "importance": 8.0,
                    "access_count": 0
                }]
            )
            print(f"更新时间记忆 - 角色 {role}: {timestamp}")
        else:
            # 创建新的时间记忆
            memory_id = str(uuid.uuid4())
            collection.add(
                ids=[memory_id],
                documents=[time_memory_content],
                metadatas=[{
                    "type": "time", 
                    "created_at": timestamp,
                    "importance": 8.0,
                    "access_count": 0
                }]
            )
            print(f"创建时间记忆 - 角色 {role}: {timestamp}")
        
    except Exception as e:
        print(f"更新时间记忆失败: {e}")


def get_latest_time_memory(role: str) -> Optional[Dict]:
    """获取角色的最新时间记忆"""
    try:
        role_safe = sanitize_name(role)
        existing = [c.name for c in client.list_collections()]
        if role_safe not in existing:
            return None
            
        collection = client.get_collection(name=role_safe)
        memories = collection.peek(limit=1000)
        
        documents = memories.get("documents", [])
        metadatas = memories.get("metadatas", [])
        
        time_memories = []
        for i, metadata in enumerate(metadatas):
            if i < len(documents) and metadata and metadata.get("type") == "time":
                time_memories.append({
                    "content": documents[i],
                    "metadata": metadata
                })
        
        if time_memories:
            # 返回最新的时间记忆
            latest = sorted(time_memories, 
                          key=lambda x: x["metadata"].get("created_at", "1970-01-01T00:00:00"))[-1]
            return latest
        
        return None
        
    except Exception as e:
        print(f"获取时间记忆失败: {e}")
        return None
# -----------------------
# 角色活动状态函数 (App.py 需要)
# -----------------------

def get_role_activity(role_name: str) -> str:
    """获取角色的当前活动状态"""
    if role_name.lower() == 'user':
        return "等待指令/移动"

    if rest_manager.is_resting(role_name):
        rest_type = rest_manager.get_rest_info(role_name).get('rest_type', '休息')
        return f"正在休息 ({rest_type})"
        
    # 默认状态
    return "思考下一步行动"
async def handle_npc_response(role, user_message: str, room):
    """
    处理 AI 的思考、回复和动作执行。
    保留你原本的感知（Parser）和动作解析逻辑。
    """
    from prompt_builder import build_prompt
    from roomAsyc import RoomSenseParser
    from room import add_role_to_room
    import re, json
    time_info = get_accelerated_time()
    current_time_str = time_info["virtual_time"].strftime("%H:%M") # 例如 "08:30" 或 "23:15"
    # 1. 实时感知
    parser = RoomSenseParser(room.to_dict())
    area_name, area_id = parser.get_area_name(role.x, role.y)
    furnitures, doors = parser.get_room_details(area_id)
    available_targets = furnitures + doors

    # 获取完整的房间感知信息（改为使用已实现的 parse_for_role）
    room_sense = parser.parse_for_role(role.name)

    # 2. 检索记忆
    memories = await asyncio.to_thread(query_memory, role.name, user_message, top_k=5)

    # 直接访问属性，并确保在属性为 None 时返回空列表
    all_furnitures = [f.name for f in (room.layout.furniture or [])]
    all_doors = [d.name for d in (room.layout.doors or [])]
    available_targets = all_furnitures + all_doors # 給予全域視野，防止 AI 找不到餐桌

    # 3. 構造 Prompt
    prompt = build_prompt(
        user_input=user_message,
        memories=memories,
        available_targets=available_targets,
        room_sense=room_sense,
        role_name=role.name,
        time_str=current_time_str  # <--- 這裡傳入時間
    )
    response_text = await asyncio.to_thread(run_ollama_sync, prompt)
    print(f"AI 回复: {response_text}")
    # 4. 解析动作
    reply = response_text
    # 如果 AI 固執地使用 /talk 格式，提取引號內的內容
    talk_match = re.search(r'/talk\s*“([^”]+)”', reply)
    if talk_match:
        reply = talk_match.group(1)
        
    # 解析 JSON_START
    action_status = None
    json_match = re.search(r"JSON_START\s*(\{.*?\})\s*JSON_END", response_text, re.DOTALL)
    match = json_match
    if match:
        try:
            cmd = json.loads(match.group(1))
            action = cmd.get("action")
            # "move" 和 "talk_and_move" 都視為需要移動
            if action in ["move", "talk_and_move"]:
                target_name = cmd.get("target")
                # 寻找目标坐标并更新数据库
                found = False
                if room.layout.furniture:
                    for f in room.layout.furniture:
                        if f.name == target_name:
                            print(f"移动到家具: {target_name} at ({f.x}, {f.y})")
                            await asyncio.to_thread(add_role_to_room, role.name, f.x, f.y, room.name)
                            action_status = f"已移動到 {target_name}"
                            found = True
                            break
                
                # 如果家具沒找到，找門 (Doors)
                if not found and room.layout.doors:
                    for d in room.layout.doors:
                        if d.name == target_name:
                            await asyncio.to_thread(add_role_to_room, role.name, d.x, d.y, room.name)
                            action_status = f"已穿過 {target_name}"
                            break
            # 清洗文本内容
            reply = re.sub(r"JSON_START.*?JSON_END", "", response_text, flags=re.DOTALL).strip()
        except Exception as e:
            print(f"Action解析失败: {e}")

    return reply, action_status

