# room.py
import os
import json
from typing import List, Dict, Optional
from pydantic import BaseModel, Field

# -----------------------
# 配置
# -----------------------
ROOM_DIR = "room_data"
# 确保 room_data 文件夹存在
os.makedirs(ROOM_DIR, exist_ok=True)

def get_room_file_path(room_name: str) -> str:
    """获取房间数据文件的路径"""
    return os.path.join(ROOM_DIR, f"{room_name}.json")


# -----------------------
# Room 数据结构
# -----------------------

class Area(BaseModel):
    id: str
    name: str
    x: int
    y: int
    width: int
    height: int
    color: str

class Wall(BaseModel):
    id: int
    x1: int
    y1: int
    x2: int
    y2: int
    thickness: int
    isOuter: Optional[bool] = Field(default=False)

class Door(BaseModel):
    id: int
    name: str
    x: int
    y: int
    width: int
    thickness: int
    direction: str
    area: str

class Window(BaseModel):
    id: int
    x: int
    y: int
    width: int
    thickness: int
    direction: str

class Furniture(BaseModel):
    id: int
    name: str
    type: str
    x: int
    y: int
    width: int
    height: int
    color: str
    description: Optional[str] = None

class Layout(BaseModel):
    """房间内部布局的容器，包含所有静态元素"""
    areas: List[Area] = Field(default_factory=list)
    walls: List[Wall] = Field(default_factory=list)
    doors: List[Door] = Field(default_factory=list)
    windows: List[Window] = Field(default_factory=list)
    furniture: List[Furniture] = Field(default_factory=list)

class RoomRole(BaseModel):
    """房间内角色的定义"""
    name: str
    type: str = Field(default="person")
    x: int
    y: int
    size: int = Field(default=20)
    avatar: str = Field(default="👤")
    # 运行时字段，不参与保存
    activity: Optional[str] = Field(default=None) 
    
class Room(BaseModel):
    """完整的房间数据模型"""
    name: str = Field(default="main")
    width: int = Field(default=800)
    height: int = Field(default=600)
    scale: int = Field(default=10)
    roles: List[RoomRole] = Field(default_factory=list)
    layout: Layout = Field(default_factory=Layout)

    def to_dict(self):
        # 使用 Pydantic v2 方法，导出时排除运行时字段 activity
        return self.model_dump(exclude={"roles": {"__all__": {"activity"}}})
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls.model_validate(data)
    
    def add_role(self, role_name: str, x: int, y: int, avatar: str = "👤"):
        """添加或更新角色位置"""
        for role in self.roles:
            if role.name == role_name:
                role.x = x
                role.y = y
                role.avatar = avatar
                return
        self.roles.append(RoomRole(name=role_name, x=x, y=y, avatar=avatar))

    def remove_role(self, role_name: str):
        """移除角色"""
        self.roles = [role for role in self.roles if role.name != role_name]
        
# -----------------------
# 房间管理函数 (CRUD)
# -----------------------
# room.py

def get_room(room_name: str = "main") -> Room:
    """读取房间对象，处理 Pydantic 转换和文件降级逻辑"""
    room_file = get_room_file_path(room_name)
    
    # 1. 尝试从 room_data 文件夹读取
    if os.path.exists(room_file):
        try:
            with open(room_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 使用 Pydantic 的 parse_obj (v1) 或 model_validate (v2)
                return Room.parse_obj(data) 
        except Exception as e:
            print(f"解析房间数据 {room_file} 失败: {e}")

    # 2. 如果没找到，尝试加载项目根目录的备份文件
    default_file = "main.json"
    if os.path.exists(default_file):
        try:
            print(f"从根目录加载默认备份: {default_file}")
            with open(default_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 转换数据
                room = Room.parse_obj(data)
                # 自动将其保存到 room_data 文件夹，方便下次直接读取
                save_room(room, room_name)
                return room
        except Exception as e:
            print(f"解析备份文件失败: {e}")

    # 3. 彻底没找到，创建初始化房间（必须包含 layout 结构，否则后续 f.x 会报错）
    print(f"警告: 找不到任何房间数据，正在创建空房间: {room_name}")
    # 确保初始化了 layout 以及空的 furniture 列表
    empty_layout = Layout(
        furniture=[], 
        doors=[], 
        areas=[], 
        walls=[]
    )
    return Room(name=room_name, layout=empty_layout)
def save_room(room: Room, room_name: str = "main"):
    """保存房间对象"""
    room_file = get_room_file_path(room_name)
    try:
        with open(room_file, "w", encoding="utf-8") as f:
            json.dump(room.to_dict(), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存房间数据失败: {e}")

def add_role_to_room(role_name: str, x: int, y: int, room_name: str = "main", avatar: str = "👤"):
    """添加或更新角色位置"""
    room = get_room(room_name)
    room.add_role(role_name, x, y, avatar)
    save_room(room, room_name)

def remove_role_from_room(role_name: str, room_name: str = "main"):
    """从房间移除角色"""
    room = get_room(room_name)
    room.remove_role(role_name)
    save_room(room, room_name)
    
def clear_room(room_name: str = "main"):
    
    """清空房间中的所有非用户角色"""
    room = get_room(room_name)
    user_role = next((role for role in room.roles if role.name.lower() == 'user'), None)
    
    room.roles = []
    if user_role:
        room.roles.append(user_role)
    
    save_room(room, room_name)
    # room.py

def execute_action(role_name: str, action_data: dict) -> str:
    """执行 AI 发出的动作指令"""
    action_type = action_data.get("action")
    target = action_data.get("target")
    
    room = get_room()
    
    if action_type == "move":
        # 寻找家具或区域的中心点坐标
        target_pos = None
        
        # 先找家具
        for f in room.layout.get("furniture", []):
            if f["name"] == target:
                target_pos = (f["x"], f["y"])
                break
        
        # 再找区域（如果家具没找到）
        if not target_pos:
            for a in room.layout.get("areas", []):
                if a["name"] == target:
                    target_pos = (a["x"] + a["width"]//2, a["y"] + a["height"]//2)
                    break
        
        if target_pos:
            add_role_to_room(role_name, target_pos[0], target_pos[1])
            return f"系统：你已成功移动到 {target}。"
        return f"系统：移动失败，找不到目标 {target}。"

    elif action_type == "interact":
        # 这里可以扩展，比如开关灯、打开电脑等逻辑
        return f"系统：你对 {target} 进行了互动。"
        
    return "系统：未知动作。"