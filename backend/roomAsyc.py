import math

class RoomSenseParser:
    def __init__(self, room_data):
        # 🔥 如果传入的是 Pydantic 模型，自动转为字典
        if hasattr(room_data, "model_dump"):
            self.data = room_data.model_dump()
        elif hasattr(room_data, "dict"):
            self.data = room_data.dict()
        else:
            self.data = room_data
            
        # 确保使用字典访问
        self.layout = self.data.get("layout", {})

    def get_distance(self, p1, p2):
        return math.sqrt((p1['x'] - p2['x'])**2 + (p1['y'] - p2['y'])**2)

    def get_area_name(self, x, y):
        for area in self.layout.get("areas", []):
            if area['x'] <= x <= area['x'] + area['width'] and \
               area['y'] <= y <= area['y'] + area['height']:
                return area['name'], area['id']
        return "未知区域", None

    def get_room_details(self, area_id):
        # 获取该房间内的家具
        # 这里简化处理：判断家具中心点是否在房间矩形内
        area = next((a for a in self.layout["areas"] if a["id"] == area_id), None)
        if not area: return [], []

        furnitures = []
        for f in self.layout.get("furniture", []):
            if area['x'] <= f['x'] <= area['x'] + area['width'] and \
               area['y'] <= f['y'] <= area['y'] + area['height']:
                furnitures.append(f['name'])

        # 获取连接这个房间的门
        doors = []
        for d in self.layout.get("doors", []):
            if d.get("area") == area_id:
                doors.append(f"{d['name']}")
                
        return furnitures, doors

    def parse_for_role(self, role_name):
        role = next((r for r in self.data["roles"] if r["name"] == role_name), None)
        if not role: return "找不到该角色。"

        area_name, area_id = self.get_area_name(role['x'], role['y'])
        furnitures, doors = self.get_room_details(area_id)
        
        # 寻找身边的其他人
        others = []
        for r in self.data["roles"]:
            if r["name"] != role_name:
                dist = self.get_distance(role, r)
                other_area, _ = self.get_area_name(r['x'], r['y'])
                rel_pos = "就在你身边" if dist < 100 else f"距离你 {dist:.1f} 单位"
                others.append(f"{r['name']}（在{other_area}，{rel_pos}）")

        # 组装描述文本
        desc = [
            f"--- 环境感知 ---",
            f"📍 当前位置：{area_name}",
            f"🪑 房间内有：{', '.join(furnitures) if furnitures else '空无一物'}",
            f"🚪 出口/门：{', '.join(doors) if doors else '没有明显的出口'}",
            f"👥 周边人物：{', '.join(others) if others else '附近没有其他人'}"
        ]
        
        return "\n".join(desc)