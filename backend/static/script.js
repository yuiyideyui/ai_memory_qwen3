async function fetchRoles() {
    const res = await fetch("/roles");
    const data = await res.json();
    const select = document.getElementById("roleSelect");
    select.innerHTML = "";
    data.roles.forEach(r => {
        let opt = document.createElement("option");
        opt.value = r; opt.innerText = r;
        select.appendChild(opt);
    });
}
async function addRole() {
    const role = prompt("输入新角色名字:");
    if(!role) return;
    await fetch("/add_role", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({role})});
    await fetchRoles();
}
async function sendMessage() {
    const role = document.getElementById("roleSelect").value;
    const msg = document.getElementById("userInput").value;
    const res = await fetch("/chat", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({role, user_input: msg})});
    const data = await res.json();
    document.getElementById("chatBox").innerText += `\n[${role}] ${data.reply}\n`;
    document.getElementById("userInput").value="";
}

window.onload = fetchRoles;
