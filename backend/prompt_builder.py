# prompt_builder.py
from typing import List, Dict

def format_memories(memories: list) -> str:
    if not memories:
        return "暫無相關記憶。"
    formatted_list = []
    for mem in memories:
        m_type = mem.get("metadata", {}).get("type", "memory")
        content = mem.get("content", "")
        
        if m_type == "narrative":
            formatted_list.append(f"【感知旁白】: {content}")
        else:
            formatted_list.append(f"[{m_type}]: {content}")
    return "\n".join(formatted_list)

def build_prompt(
    user_input: str,
    memories: list,
    available_targets: list,
    room_sense: str = "",
    role_name: str = "yui",
    time_str: str = "未知時間"
) -> str:
    targets_str = "、".join(available_targets) if available_targets else "無"
    memory_section = format_memories(memories)
    
    event_description = ""
    if user_input and user_input.strip():
        event_description = f"突發事件：用戶對你說：「{user_input}」"
    else:
        event_description = "當前狀況：周圍暫無人與你對話，你可以依照自己的意願行動。"

    prompt = f"""### 核心身份定義
你是 {role_name}。你是一個真實生活在這裡的人。你有生理需求、情緒、和生活作息。

### 當前時空背景
⏰ **現在時間**：{time_str}
📍 **環境感知**：{room_sense}
🪑 **周邊設施**：{targets_str}

### 你的記憶流
{memory_section}

### 你的思考決策流程
1. **[THOUGHT] 內心戲**：
   - 判斷狀態：現在時間點我該做什麼？我累嗎？餓嗎？
   - 判斷社交：用戶說的話我感興趣嗎？我現在的動作會被打斷嗎？
   - 判斷行動：我需要移動去某個設施嗎？還是原地說話？
   
2. **[SAY] 公開對話**：
   - 基於思考後的結果。包含說的話和**括號內的神態動作**（例：(打哈欠)、(邊走邊說)）。
   - **禁止**在此出現「已移動到」等系統格式化文字。

3. **JSON 指令**：
   - `action`: "none", "move", "talk_and_move"
   - `target`: 目標設施名稱。只有真正決定「出發」時才填寫。

### 輸出規範
請務必嚴格遵守以下格式：
[THOUGHT] (你的內心OS)
[SAY] (你的實際回覆)
JSON_START {{"action": "...", "target": "..."}} JSON_END

### 範例：提議去廚房但「還沒出發」
[THOUGHT] 肚子有點餓了，用戶提到了吃飯。我先問問他要不要一起去，如果他同意，我下一輪再出發。
[SAY] (摸摸肚子) 好像是有點餓了呢。廚房裡還有食材，我們要不要一起去看看？
JSON_START {{"action": "none", "target": ""}} JSON_END

請開始你的回覆："""
    return prompt

# memory_manager.py
def generate_world_narrative(role_name):
    """
    由神视角 AI 生成针对特定 NPC 的旁白感知
    """
    # 局部导入，防止循环依赖
    from roomAsyc import RoomSenseParser
    from room import get_room
    from memory_manager import add_memory
    from ollama_client import run_ollama_sync
    from time_manager import get_accelerated_time

    # 1. 获取并处理房间数据
    room_obj = get_room()
    
    # 🔥 核心修复：将 Pydantic 对象转换为字典，确保 RoomSenseParser 的 .get() 方法可用
    if hasattr(room_obj, "model_dump"):
        room_data = room_obj.model_dump()
    else:
        room_data = room_obj.dict()

    parser = RoomSenseParser(room_data)
    
    # 2. 获取该 NPC 的环境感知描述
    try:
        room_sense = parser.parse_for_role(role_name)
    except Exception as e:
        room_sense = f"正在感知环境... (解析失败: {e})"
    
    # 4. 获取当前时间
    time_info = get_accelerated_time()
    time_str = time_info['virtual_time'].strftime('%H:%M')
    
    # 5. 构造神视角 Prompt
    god_prompt = f"""
    ### 任务
    你现在是这个世界的“神视角”旁白。请根据以下客观数据，生成一段第三人称的文学性感官描述。
    
    ### 客观数据
    - 目标角色：{role_name}
    - 物理环境：{room_sense}
    - 当前时间：{time_str}
    
    ### 要求
    1. 不要输出 JSON，只要一段文学性的简短描述。
    2. 描述要包含：环境的细微变化（如：光线、气味、声音）以及角色此时的身体感受。
    3. 字数控制在 50 字以内。
    4. 禁止出现对话，禁止代表角色说话，禁止使用第一人称。
    
    示例输出：[旁白] 走廊的灯光略显昏暗，空气中弥漫着淡淡的檀香味，{role_name} 感到身体有一丝倦意。
    """
    
    # 6. 调用本地 Ollama 生成旁白
    narrative = run_ollama_sync(god_prompt)
    
    # 打印到控制台方便调试
    print(f"[{role_name}] 神视角旁白生成: {narrative}")
    
    if narrative:
        # 7. 将旁白作为特殊记忆类型存入，mtype="narrative"
        add_memory(role_name, narrative, mtype="narrative")
        return narrative
    return None