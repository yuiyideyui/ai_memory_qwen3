import re

def process_message(message):
    # 1. 移除 JSON 塊
    message = re.sub(r'JSON_START[\s\S]*?JSON_END', '', message)

    # 2. 處理思維鏈
    if "[SAY]" in message:
        message = message.split("[SAY]")[-1]
    else:
        message = re.sub(r'\[THOUGHT\][\s\S]*?(\[|$)', r'\1', message)

    # 3. 移除特定系統括號（已移動到... / 已穿過...）
    message = re.sub(r'[（\(]已(?:移動到|穿過).*?[）\)]', '', message)

    # 4. 🔥 新增：移除所有剩餘的括號內容（例如：(啊实打实的) 或 （內容））
    # 這個正則會匹配所有中文或英文括號及其內部的文字
    message = re.sub(r'[（\(].*?[）\)]', '', message)

    return message.strip()