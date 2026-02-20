import json
import sqlite3
import time
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.context import CryptContext

# =============================
# 基础配置
# =============================

SECRET_KEY = "CHANGE_THIS_SECRET"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 60 * 60 * 24

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# =============================
# 数据库
# =============================

conn = sqlite3.connect("chat.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    is_admin INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS friends (
    user TEXT,
    friend TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT,
    receiver TEXT,
    content TEXT,
    timestamp INTEGER
)
""")

conn.commit()

# =============================
# JWT
# =============================

def create_token(username: str):
    expire = int(time.time()) + ACCESS_TOKEN_EXPIRE_SECONDS
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(token: str = Depends(oauth2_scheme)):
    return verify_token(token)

# =============================
# 注册
# =============================

@app.post("/register")
def register(username: str, password: str):
    hashed = pwd_context.hash(password)
    try:
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, hashed)
        )
        conn.commit()
        return {"status": "ok"}
    except:
        raise HTTPException(status_code=400, detail="User exists")

# =============================
# 登录
# =============================

@app.post("/login")
def login(username: str, password: str):
    cursor.execute("SELECT password FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="User not found")

    if not pwd_context.verify(password, row[0]):
        raise HTTPException(status_code=400, detail="Wrong password")

    token = create_token(username)
    return {"access_token": token, "token_type": "bearer"}

# =============================
# 添加好友
# =============================

@app.post("/add_friend")
def add_friend(friend: str, user: str = Depends(get_current_user)):
    cursor.execute("INSERT INTO friends (user, friend) VALUES (?, ?)", (user, friend))
    conn.commit()
    return {"status": "added"}

# =============================
# 获取好友列表
# =============================

@app.get("/friends")
def get_friends(user: str = Depends(get_current_user)):
    cursor.execute("SELECT friend FROM friends WHERE user=?", (user,))
    rows = cursor.fetchall()
    return {"friends": [r[0] for r in rows]}

# =============================
# 消息历史
# =============================

@app.get("/history/{other}")
def get_history(other: str, user: str = Depends(get_current_user)):
    cursor.execute("""
        SELECT sender, receiver, content, timestamp
        FROM messages
        WHERE (sender=? AND receiver=?)
           OR (sender=? AND receiver=?)
        ORDER BY timestamp ASC
    """, (user, other, other, user))
    rows = cursor.fetchall()
    return {"messages": rows}

# =============================
# WebSocket
# =============================

active_connections = {}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    username = verify_token(token)
    await websocket.accept()
    active_connections[username] = websocket

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            receiver = msg["to"]
            content = msg["content"]

            timestamp = int(time.time())

            cursor.execute(
                "INSERT INTO messages (sender, receiver, content, timestamp) VALUES (?, ?, ?, ?)",
                (username, receiver, content, timestamp)
            )
            conn.commit()

            if receiver in active_connections:
                await active_connections[receiver].send_text(json.dumps({
                    "from": username,
                    "content": content,
                    "timestamp": timestamp
                }))

    except WebSocketDisconnect:
        active_connections.pop(username, None)

# =============================
# 管理员接口
# =============================

@app.get("/admin/users")
def list_users(user: str = Depends(get_current_user)):
    cursor.execute("SELECT is_admin FROM users WHERE username=?", (user,))
    row = cursor.fetchone()
    if not row or row[0] != 1:
        raise HTTPException(status_code=403, detail="Not admin")

    cursor.execute("SELECT username FROM users")
    return {"users": [u[0] for u in cursor.fetchall()]}
