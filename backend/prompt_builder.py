# prompt_builder.py
from typing import List, Dict

def format_memories(memories: list) -> str:
    """將從 ChromaDB 獲取的記憶列表格式化為字符串"""
    if not memories:
        return "暫無相關記憶。"
    
    formatted_list = []
    for mem in memories:
        # 兼容字典格式或 ChromaDB 的原始格式
        content = mem.get("content", "")
        # 取得 metadata 中的 type，預設為 'memory'
        m_type = mem.get("metadata", {}).get("type", "memory")
        formatted_list.append(f"[{m_type}]: {content}")
    
    return "\n".join(formatted_list)
# prompt_builder.py

def build_prompt(user_input: str, memories: list, available_targets: list) -> str:
    targets_str = "、".join(available_targets)
    memory_section = format_memories(memories)
    
    prompt = f"""### 角色設定
你現在完全化身為租客。你是有情緒、有生活氣息的真人，不是冷冰冰的機器人。

### 相關記憶
{memory_section}

### 當前環境
📍 附近目標：[{targets_str}]

### 核心任務：如何回覆用戶
用戶剛剛對你說："{user_input}"

### 寫作規範 (極其重要)
1. **必須先進行自然對話**：表達你的情感、反應或想法。不要只給一個 JSON！
2. **對話與行動結合**：如果你決定移動，請在說完話後，另起一行加上 JSON。
3. **場景感**：例如你想去餐桌，你可以說：「肚子有點餓了，我們去餐桌那邊坐著聊吧？」然後再附上 JSON。

### 回覆格式範例
---
(你的自然對話內容，至少 2-3 句)

JSON_START {{"action": "move", "target": "餐桌"}} JSON_END
---

請以 yui 的身份開始回覆："""
    
    return prompt