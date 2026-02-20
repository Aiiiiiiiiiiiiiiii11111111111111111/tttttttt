import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import jwt, time, os, json, asyncio, base64

# ===============================
# 配置
# ===============================
app = FastAPI()
SECRET_KEY = "请替换成超长随机密钥"
ACCESS_TOKEN_EXPIRE = 3600
ADMIN_USERS = ["admin"]
os.makedirs("uploads", exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件支持 Web 前端
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# ===============================
# 模拟数据库
# ===============================
USERS = {}           # username -> password
FRIENDS = {}         # username -> [friend_usernames]
ONLINE = {}          # username -> websocket
USER_UPLOADS = {}    # username -> [filename]

# ===============================
# JWT
# ===============================
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def create_token(username: str):
    payload = {"sub": username, "exp": time.time() + ACCESS_TOKEN_EXPIRE}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["sub"]
    except:
        return None

def get_current_user(token: str = Depends(oauth2_scheme)):
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

# ===============================
# 数据模型
# ===============================
class User(BaseModel):
    username: str
    password: str

# ===============================
# HTTP 接口
# ===============================
@app.post("/register")
def register(user: User):
    if user.username in USERS:
        return {"error": "用户已存在"}
    USERS[user.username] = user.password
    FRIENDS[user.username] = []
    USER_UPLOADS[user.username] = []
    return {"msg": "注册成功"}

@app.post("/login")
def login(user: User):
    if USERS.get(user.username) != user.password:
        raise HTTPException(401, "用户名或密码错误")
    token = create_token(user.username)
    return {"access_token": token}

@app.get("/friends")
def get_friends(current_user: str = Depends(get_current_user)):
    return {"friends": FRIENDS.get(current_user, [])}

@app.post("/add_friend")
def add_friend(friend: str, current_user: str = Depends(get_current_user)):
    if friend not in USERS:
        raise HTTPException(404, "好友不存在")
    if friend not in FRIENDS[current_user]:
        FRIENDS[current_user].append(friend)
    if current_user not in FRIENDS[friend]:
        FRIENDS[friend].append(current_user)
    return {"msg": "添加成功"}

# ===============================
# 管理员接口
# ===============================
@app.get("/admin/users")
def admin_users(current_user: str = Depends(get_current_user)):
    if current_user not in ADMIN_USERS:
        raise HTTPException(403, "不是管理员")
    return {"users": list(ONLINE.keys())}

@app.post("/admin/kick")
def admin_kick(user: str, current_user: str = Depends(get_current_user)):
    if current_user not in ADMIN_USERS:
        raise HTTPException(403, "不是管理员")
    ws = ONLINE.get(user)
    if ws:
        asyncio.create_task(ws.close())
        return {"msg": f"{user} 已被踢出"}
    return {"msg": "用户不在线"}

@app.post("/admin/broadcast")
def admin_broadcast(message: str, current_user: str = Depends(get_current_user)):
    if current_user not in ADMIN_USERS:
        raise HTTPException(403, "不是管理员")
    for ws in ONLINE.values():
        asyncio.create_task(ws.send_json({"from": "管理员", "content": message}))
    return {"msg": "广播完成"}

# ===============================
# 上传文件接口
# ===============================
@app.post("/upload")
async def upload_file(file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    save_path = f"uploads/{current_user}_{int(time.time())}_{file.filename}"
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    USER_UPLOADS[current_user].append(save_path)
    return {"msg": "上传成功", "filename": save_path}

@app.get("/uploads/{username}")
def list_uploads(username: str, current_user: str = Depends(get_current_user)):
    return {"files": USER_UPLOADS.get(username, [])}

# ===============================
# WebSocket 聊天（消息/文件/语音）
# ===============================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    username = verify_token(token)
    if not username:
        await websocket.close()
        return
    await websocket.accept()
    ONLINE[username] = websocket
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            to_user = msg.get("to")
            if not to_user:
                continue
            if to_user in ONLINE:
                try:
                    await ONLINE[to_user].send_text(json.dumps(msg))
                except:
                    pass
            if "file" in msg:
                file_data = base64.b64decode(msg["content"])
                save_path = f"uploads/{to_user}_{int(time.time())}_{msg['file']}"
                with open(save_path, "wb") as f:
                    f.write(file_data)
                USER_UPLOADS[to_user].append(save_path)
            if "voice" in msg:
                voice_data = base64.b64decode(msg["voice"])
                save_path = f"uploads/{to_user}_voice_{int(time.time())}.raw"
                with open(save_path, "wb") as f:
                    f.write(voice_data)
                USER_UPLOADS[to_user].append(save_path)
    except WebSocketDisconnect:
        ONLINE.pop(username, None)
