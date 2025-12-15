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

def get_room(room_name: str = "main") -> Room:
    """读取房间对象，如果文件不存在则尝试加载 main.json 作为默认值"""
    room_file = get_room_file_path(room_name)
    try:
        with open(room_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return Room.from_dict(data)
    except FileNotFoundError:
        # 如果 room_data/main.json 不存在，尝试加载项目根目录的 main.json
        default_file = "main.json" 
        try:
            with open(default_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                room = Room.from_dict(data)
                save_room(room, room_name) # 保存到 room_data 文件夹
                return room
        except FileNotFoundError:
             print(f"警告: 默认文件 {default_file} 也不存在。创建空房间。")
             return Room(name=room_name)
    except Exception as e:
        print(f"读取房间数据失败: {e}")
        return Room(name=room_name)

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