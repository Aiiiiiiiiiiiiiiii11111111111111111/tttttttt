import asyncio
import websockets
import os
import json
import sqlite3
from datetime import datetime

clients = {}  # websocket -> {username, room}
rooms = {}    # room_name -> set(websocket)
blacklist = set()

DB = "chat.db"


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT,
            username TEXT,
            message TEXT,
            time TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_message(room, username, message):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO messages (room, username, message, time) VALUES (?, ?, ?, ?)",
              (room, username, message, now()))
    conn.commit()
    conn.close()


async def broadcast(room, message):
    if room in rooms:
        dead = []
        for ws in rooms[room]:
            try:
                await ws.send(json.dumps(message))
            except:
                dead.append(ws)

        for ws in dead:
            rooms[room].remove(ws)


async def handler(websocket):
    try:
        raw = await websocket.recv()
        data = json.loads(raw)

        if data["type"] != "login":
            await websocket.close()
            return

        username = data["username"]
        room = data.get("room", "默认房间")

        if username in blacklist:
            await websocket.close()
            return

        clients[websocket] = {"username": username, "room": room}

        if room not in rooms:
            rooms[room] = set()
        rooms[room].add(websocket)

        await broadcast(room, {
            "type": "system",
            "message": f"{username} 进入房间",
            "time": now(),
            "online": len(rooms[room])
        })

        async for raw in websocket:
            data = json.loads(raw)

            # 群聊
            if data["type"] == "chat":
                message = data["message"]

                save_message(room, username, message)

                await broadcast(room, {
                    "type": "chat",
                    "username": username,
                    "message": message,
                    "time": now()
                })

            # 私聊
            elif data["type"] == "private":
                target = data["to"]
                for ws, info in clients.items():
                    if info["username"] == target:
                        await ws.send(json.dumps({
                            "type": "private",
                            "from": username,
                            "message": data["message"],
                            "time": now()
                        }))

            # 管理员踢人
            elif data["type"] == "kick":
                if username == "admin":
                    target = data["target"]
                    for ws, info in list(clients.items()):
                        if info["username"] == target:
                            await ws.close()

            # 黑名单
            elif data["type"] == "ban":
                if username == "admin":
                    blacklist.add(data["target"])

    except:
        pass
    finally:
        if websocket in clients:
            info = clients.pop(websocket)
            room = info["room"]
            username = info["username"]

            if room in rooms and websocket in rooms[room]:
                rooms[room].remove(websocket)

            await broadcast(room, {
                "type": "system",
                "message": f"{username} 离开房间",
                "time": now(),
                "online": len(rooms.get(room, []))
            })


async def main():
    init_db()
    port = int(os.environ.get("PORT", 8765))
    async with websockets.serve(handler, "0.0.0.0", port):
        print(f"Server running on port {port}")
        await asyncio.Future()


asyncio.run(main())
