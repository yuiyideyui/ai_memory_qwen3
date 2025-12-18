// ----------------------------------------------------
// I. 全局变量与初始化
// ----------------------------------------------------
const socket = io({ path: '/socket.io/' });
const roomElement = document.getElementById("room");
const chatLog = document.getElementById("chatLog");
const roleSize = 60; 

let userName = document.getElementById("userNameInput").value;
let userPosition = { x: 100, y: 100 };
let roomData = null; 
let roomDimensions = { width: 800, height: 600 }; 

let isDragging = false;
let draggedRole = null;
let offsetX = 0;
let offsetY = 0;

const canvas = document.getElementById('roomCanvas');
const ctx = canvas.getContext('2d');
const collisionRadius = 20; 

// ----------------------------------------------------
// II. Socket.IO 事件监听
// ----------------------------------------------------
socket.on('connect', function () {
    logMessage("System", `已连接到服务器. Socket ID: ${socket.id}`, getTime(), "log-system");
    socket.emit('request_initial_data', { room_name: 'main' }); 
});

socket.on('disconnect', function () {
    logMessage("System", "与服务器断开连接.", getTime(), "log-system");
});

socket.on('room_data_update', function (data) {
    roomData = data;
    roomDimensions.width = roomData.width || 800;
    roomDimensions.height = roomData.height || 600;
    canvas.width = roomDimensions.width;
    canvas.height = roomDimensions.height;
    roomElement.style.width = roomDimensions.width + 'px';
    roomElement.style.height = roomDimensions.height + 'px';
    document.getElementById("room-container").style.width = roomDimensions.width + 'px';
    document.getElementById("room-container").style.height = roomDimensions.height + 'px';

    renderLayout(roomData.layout);
    renderRoles(roomData.roles);
});

socket.on('chat_message', function (data) {
    const cssClass = data.sender === userName ? "log-user" : "log-ai";
    logMessage(data.sender, data.message, data.time, cssClass);
});

socket.on('time_update', function (data) {
    document.getElementById("currentTime").innerText = data.formatted_time;
});

// ----------------------------------------------------
// III. 渲染函数
// ----------------------------------------------------
function renderLayout(layout) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    if (layout && layout.areas) {
        layout.areas.forEach(area => {
            ctx.fillStyle = area.color;
            ctx.fillRect(area.x, area.y, area.width, area.height);
            ctx.strokeStyle = '#ccc';
            ctx.strokeRect(area.x, area.y, area.width, area.height);
        });
    }

    if (layout && layout.walls) {
        layout.walls.forEach(wall => {
            ctx.beginPath();
            ctx.lineWidth = wall.thickness;
            ctx.strokeStyle = wall.isOuter ? '#333' : '#555';
            ctx.moveTo(wall.x1, wall.y1);
            ctx.lineTo(wall.x2, wall.y2);
            ctx.stroke();
        });
    }

    if (layout && layout.doors) {
        layout.doors.forEach(door => {
            ctx.beginPath();
            ctx.lineWidth = door.thickness + 2;
            ctx.strokeStyle = '#fcfcfc';
            if (door.direction === 'horizontal') {
                ctx.moveTo(door.x, door.y);
                ctx.lineTo(door.x + door.width, door.y);
            } else {
                ctx.moveTo(door.x, door.y);
                ctx.lineTo(door.x, door.y + door.width);
            }
            ctx.stroke();

            ctx.beginPath();
            ctx.lineWidth = 4;
            ctx.strokeStyle = '#666';
            if (door.direction === 'horizontal') {
                ctx.arc(door.x, door.y, door.width, Math.PI * 1.5, Math.PI * 0.5);
            } else {
                ctx.arc(door.x, door.y, door.width, Math.PI, Math.PI * 2);
            }
            ctx.stroke();
        });
    }

    if (layout && layout.furniture) {
        layout.furniture.forEach(item => {
            ctx.fillStyle = item.color;
            ctx.fillRect(item.x, item.y, item.width, item.height);
            ctx.strokeStyle = '#333';
            ctx.strokeRect(item.x, item.y, item.width, item.height);
            ctx.fillStyle = '#333';
            ctx.font = '10px Arial';
            ctx.textAlign = 'center';
            ctx.fillText(item.name, item.x + item.width / 2, item.y + item.height / 2 + 3);
        });
    }
}

function renderRoles(roles) {
    roomElement.querySelectorAll('.role').forEach(r => r.remove());
    roles.forEach(role => {
        const isUser = role.name === userName;
        if (isUser) {
            userPosition.x = role.x;
            userPosition.y = role.y;
        }

        const roleElement = document.createElement('div');
        roleElement.className = isUser ? 'role role-user' : 'role role-ai';
        roleElement.dataset.roleName = role.name;

        const left = role.x - roleSize / 2;
        const top = role.y - roleSize / 2;

        roleElement.style.left = left + 'px';
        roleElement.style.top = top + 'px';
        roleElement.title = role.name;
        roleElement.innerHTML = `
            ${role.avatar}
            <span class="role-activity" style="transform: translateX(-50%); left: 50%;">
                ${role.activity || '休息中'}
            </span>
        `;

        if (!isUser) {
            roleElement.style.cursor = 'grab';
            roleElement.addEventListener('mousedown', startDrag);
            roleElement.addEventListener('touchstart', startDrag); 
        }
        roleElement.addEventListener('click', (e) => showRoleInfo(e, role));
        roomElement.appendChild(roleElement);
    });
}

// ----------------------------------------------------
// IV. 碰撞检测逻辑
// ----------------------------------------------------
function checkCollision(centerX, centerY) {
    if (!roomData || !roomData.layout) return false;
    const layout = roomData.layout;
    const r = collisionRadius;

    const objects = (layout.walls || []).concat(layout.furniture || []);
    for (const obj of objects) {
        if (obj.x1 !== undefined && obj.x2 !== undefined) {
            if (obj.x1 === obj.x2 && Math.abs(centerX - obj.x1) < r) {
                if (centerY >= Math.min(obj.y1, obj.y2) && centerY <= Math.max(obj.y1, obj.y2)) return true;
            }
            if (obj.y1 === obj.y2 && Math.abs(centerY - obj.y1) < r) {
                if (centerX >= Math.min(obj.x1, obj.x2) && centerX <= Math.max(obj.x1, obj.x2)) return true;
            }
        } else if (obj.x !== undefined && obj.width !== undefined) {
            if (centerX >= obj.x && centerX <= obj.x + obj.width &&
                centerY >= obj.y && centerY <= obj.y + obj.height) return true;
        }
    }

    const currentRoles = Array.from(roomElement.querySelectorAll('.role'));
    for (const roleEl of currentRoles) {
        const roleName = roleEl.dataset.roleName;
        if (draggedRole && roleName === draggedRole.dataset.roleName) continue; 
        const role = roomData.roles.find(r => r.name === roleName);
        if (!role) continue;
        const distance = Math.sqrt((centerX - role.x)**2 + (centerY - role.y)**2);
        if (distance < roleSize) return true;
    }
    return false;
}

// ----------------------------------------------------
// V. AI 角色拖拽逻辑
// ----------------------------------------------------
function startDrag(e) {
    e.stopPropagation(); 
    if (e.type === 'mousedown') e.preventDefault(); 
    isDragging = true;
    draggedRole = this;
    const rect = draggedRole.getBoundingClientRect();
    const clientX = e.type.startsWith('touch') ? e.touches[0].clientX : e.clientX;
    const clientY = e.type.startsWith('touch') ? e.touches[0].clientY : e.clientY;
    offsetX = clientX - rect.left;
    offsetY = clientY - rect.top;
    draggedRole.style.cursor = 'grabbing';
    draggedRole.classList.add('role-selected');
    document.addEventListener('mousemove', drag);
    document.addEventListener('mouseup', endDrag);
    document.addEventListener('touchmove', drag);
    document.addEventListener('touchend', endDrag);
    document.getElementById("roleInfo").style.display = "none";
}

function drag(e) {
    if (!isDragging) return;
    const clientX = e.type.startsWith('touch') ? e.touches[0].clientX : e.clientX;
    const clientY = e.type.startsWith('touch') ? e.touches[0].clientY : e.clientY;
    const roomRect = document.getElementById("room").getBoundingClientRect();
    let centerX = clientX - roomRect.left - offsetX + roleSize / 2;
    let centerY = clientY - roomRect.top - offsetY + roleSize / 2;
    const boundedX = Math.max(roleSize / 2, Math.min(centerX, roomDimensions.width - roleSize / 2));
    const boundedY = Math.max(roleSize / 2, Math.min(centerY, roomDimensions.height - roleSize / 2));
    if (checkCollision(boundedX, boundedY)) return;
    draggedRole.style.left = (boundedX - roleSize / 2) + 'px';
    draggedRole.style.top = (boundedY - roleSize / 2) + 'px';
}

function endDrag(e) {
    if (!isDragging) return;
    isDragging = false;
    draggedRole.style.cursor = 'grab';
    draggedRole.classList.remove('role-selected');
    document.removeEventListener('mousemove', drag);
    document.removeEventListener('mouseup', endDrag);
    const finalCenterX = Math.round(parseFloat(draggedRole.style.left) + roleSize / 2);
    const finalCenterY = Math.round(parseFloat(draggedRole.style.top) + roleSize / 2);
    socket.emit('update_role_position', {
        room_name: 'main', role_name: draggedRole.dataset.roleName, x: finalCenterX, y: finalCenterY
    });
    logMessage("System", `角色 ${draggedRole.dataset.roleName} 移动到 (${finalCenterX}, ${finalCenterY}).`, getTime(), "log-system");
    draggedRole = null;
}

// ----------------------------------------------------
// VI. 用户交互事件监听
// ----------------------------------------------------
document.getElementById("userNameInput").addEventListener("change", function () {
    userName = this.value;
    if (userPosition.x) addUserToRoom();
});

document.getElementById("saveUserBtn").addEventListener("click", function () {
    addUserToRoom();
    updateUserButtons(false);
});

function addUserToRoom() {
    const name = document.getElementById("userNameInput").value; 
    socket.emit('update_user_position', {
        room_name: 'main', role_name: name, x: userPosition.x, y: userPosition.y, avatar: '👤'
    });
    logMessage("System", `用户 ${name} 位置已保存到 (${userPosition.x}, ${userPosition.y}).`, getTime(), "log-system");
}

document.getElementById("addRoleBtn").addEventListener("click", function () {
    const roleName = document.getElementById("newRoleName").value;
    if (roleName) {
        const startX = 100, startY = 100;
        if (checkCollision(startX, startY)) {
            alert(`无法在 (${startX}, ${startY}) 添加角色，请选择空闲位置。`);
            return;
        }
        socket.emit('add_role', { room_name: 'main', role_name: roleName, x: startX, y: startY, avatar: '🤖' });
    } else {
        alert("请输入新角色的名称。");
    }
});

document.getElementById("clearRoomBtn").addEventListener("click", function () {
    if (confirm("确定要清空所有 AI 角色吗？（用户角色会被保留）")) {
        socket.emit('clear_room', { room_name: 'main' });
    }
});

document.getElementById("sendChatBtn").addEventListener("click", sendMessage);

function sendMessage() {
    const chatInput = document.getElementById("chatMessage");
    const message = chatInput.value.trim();
    if (message && userPosition.x && userPosition.y) {
        fetch(`/distance_chat/main`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sender: userName, message: message, x: userPosition.x, y: userPosition.y })
        })
        .then(res => res.json())
        .then(data => { if (data.status !== 'success') logMessage("System", `失败: ${data.detail}`, getTime(), "log-system"); })
        .catch(() => logMessage("System", "网络错误。", getTime(), "log-system"));
        chatInput.value = '';
    }
}

document.getElementById("room").addEventListener("click", function (e) {
    if (e.target.closest('.role')) return;
    const roomRect = this.getBoundingClientRect();
    const boundedX = Math.max(roleSize / 2, Math.min(e.clientX - roomRect.left, roomDimensions.width - roleSize / 2));
    const boundedY = Math.max(roleSize / 2, Math.min(e.clientY - roomRect.top, roomDimensions.height - roleSize / 2));
    if (checkCollision(boundedX, boundedY)) {
        alert("无法将人物放置在墙壁或家具内部！");
        return; 
    }
    userPosition = { x: Math.round(boundedX), y: Math.round(boundedY) };
    document.getElementById("userPosition").innerText = `(${userPosition.x}, ${userPosition.y}) 已设置`;
    updateUserButtons(true);
    addUserToRoom();
});

document.addEventListener("click", (e) => {
    if (!e.target.closest("#roleInfo") && !e.target.closest(".role")) document.getElementById("roleInfo").style.display = "none";
});

document.getElementById("chatMessage").addEventListener("keypress", (e) => {
    if (e.key === 'Enter') { e.preventDefault(); document.getElementById("sendChatBtn").click(); }
});

document.getElementById("startTimeBtn").addEventListener("click", function () {
    socket.emit('start_time', { acceleration: parseInt(document.getElementById("timeAcceleration").value) });
    this.disabled = true;
    document.getElementById("stopTimeBtn").disabled = false;
});

document.getElementById("stopTimeBtn").addEventListener("click", function () {
    socket.emit('stop_time');
    document.getElementById("startTimeBtn").disabled = false;
    this.disabled = true;
});

// ----------------------------------------------------
// VII. 工具函数
// ----------------------------------------------------
function getTime() { return document.getElementById("currentTime").innerText.split(' ')[1] || '00:00:00'; }

function logMessage(sender, message, time, cssClass) {
    chatLog.innerHTML += `<p><span class="log-time">(${time})</span> <span class="${cssClass}">${sender}</span>: ${message}</p>`;
    chatLog.scrollTop = chatLog.scrollHeight;
}

function updateUserButtons(enabled) {
    document.getElementById("saveUserBtn").disabled = !enabled;
    document.getElementById("sendChatBtn").disabled = !enabled;
}

function showRoleInfo(e, role) {
    e.stopPropagation();
    const infoBox = document.getElementById("roleInfo");
    document.getElementById("infoRoleName").innerText = role.name;
    document.getElementById("infoPosition").innerText = `(${role.x}, ${role.y})`;
    document.getElementById("infoActivity").innerText = role.activity || '休息中';
    infoBox.style.left = (role.x + roleSize / 2 + 10) + 'px';
    infoBox.style.top = (role.y - infoBox.offsetHeight / 2) + 'px';
    infoBox.style.display = "block";
}