import asyncio
import websockets
import json
import hashlib
import time
import threading
import requests
from http.server import HTTPServer, SimpleHTTPRequestHandler
import sqlite3
import os
from datetime import datetime, timedelta

# ============ БАЗА ДАННЫХ ============
DB_URL = "libsql://york-true-cursedd.aws-eu-west-1.turso.io"
DB_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODUyNTkyNzEsImlkIjoiMDE5ZmE5YmUtNjUwMS03MmMwLTkzZjAtMTA1YWYwOWNlOWZmIiwia2lkIjoicWpYbEhLbElGQmJNX29uRDlaWEkyWFVfazVBT3h3X3JIMF9TcUZ6MmU0ZyIsInJpZCI6IjE0MzQ1ODQxLWU4ZTktNDc4NS1hNjA2LTFhNGQ3ZTY2NzdhZiJ9.17Kv3A2DdBdJjoJa_kt1W5ed5qCN3f5TERlMt8yuAr-wcsenICQFGkiLeEWeX02CkDzO2DMzD0JbfRaryKbgBA"

# Используем SQLite локально + синхронизация с Turso (упрощенно)
conn = sqlite3.connect('york.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        nick TEXT PRIMARY KEY,
        password TEXT,
        registered TEXT
    );
    CREATE TABLE IF NOT EXISTS sessions (
        nick TEXT,
        session TEXT,
        expires TEXT
    );
    CREATE TABLE IF NOT EXISTS servers (
        name TEXT PRIMARY KEY,
        firstIp TEXT,
        secondIp TEXT,
        owner TEXT,
        mapSizeX INTEGER DEFAULT 300,
        mapSizeY INTEGER DEFAULT 300,
        maxPlayers INTEGER DEFAULT 35,
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS server_admins (
        server_name TEXT,
        nick TEXT,
        level INTEGER, -- 1:helper,2:moder,3:senior_moder,4:curator,5:head_admin
        PRIMARY KEY (server_name, nick)
    );
    CREATE TABLE IF NOT EXISTS bans (
        server_name TEXT,
        nick TEXT,
        until TEXT,
        reason TEXT
    );
    CREATE TABLE IF NOT EXISTS player_prefixes (
        server_name TEXT,
        nick TEXT,
        prefix TEXT
    );
''')
conn.commit()

# ============ ИНИЦИАЛИЗАЦИЯ СЕРВЕРА YORKTRUE ============
def init_default_server():
    cursor.execute("SELECT name FROM servers WHERE name='YorkTrue'")
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO servers (name, firstIp, secondIp, owner, mapSizeX, mapSizeY, maxPlayers, created)
            VALUES ('YorkTrue', 'free.YorkTrue.york', '', 'cursed_pharaon', 300, 300, 35, datetime('now'))
        ''')
        cursor.execute("INSERT INTO server_admins VALUES ('YorkTrue', 'cursed_pharaon', 6)")  # 6 = owner
        conn.commit()
        print("[INIT] Сервер YorkTrue создан")

init_default_server()

# ============ ИГРОВОЕ СОСТОЯНИЕ ============
class GameServer:
    def __init__(self, name):
        self.name = name
        cursor.execute("SELECT mapSizeX, mapSizeY, maxPlayers FROM servers WHERE name=?", (name,))
        row = cursor.fetchone()
        self.mapW = row[0] if row else 300
        self.mapH = row[1] if row else 300
        self.maxPlayers = row[2] if row else 35
        self.map = [['grass' for _ in range(self.mapW)] for _ in range(self.mapH)]
        self.blockOwners = {}  # (x,y) -> nick
        self.blockData = {}    # (x,y) -> {'type','hp'}
        self.players = {}      # nick -> {'x','y','inventory','prefix'}
        self.systemMessages = {}  # msg -> interval
        self.generateResources()

    def generateResources(self):
        import random
        for _ in range(int(self.mapW * self.mapH * 0.15)):
            x, y = random.randint(0, self.mapW-1), random.randint(0, self.mapH-1)
            r = random.random()
            if r < 0.5: block = 'wood'
            elif r < 0.8: block = 'stone'
            elif r < 0.95: block = 'gold_ore'
            else: block = 'diamond_ore'
            self.map[y][x] = block

    def canJoin(self, nick):
        # Проверка бана
        cursor.execute("SELECT until FROM bans WHERE server_name=? AND nick=? AND until > datetime('now')", (self.name, nick))
        if cursor.fetchone():
            return False
        return len(self.players) < self.maxPlayers

    def getPlayerPrefix(self, nick):
        cursor.execute("SELECT prefix FROM player_prefixes WHERE server_name=? AND nick=?", (self.name, nick))
        row = cursor.fetchone()
        if row and row[0]: return row[0]
        cursor.execute("SELECT level FROM server_admins WHERE server_name=? AND nick=?", (self.name, nick))
        adm = cursor.fetchone()
        if adm:
            levels = {1:'[Хелпер]', 2:'[Модер]', 3:'[Ст.Модер]', 4:'[Куратор]', 5:'[Гл.Админ]', 6:'[Владелец]'}
            return levels.get(adm[0], '[Игрок]')
        return '[Игрок]'

    def handleCommand(self, nick, msg):
        parts = msg.split(' ')
        cmd = parts[0].lower()
        prefix = self.getPlayerPrefix(nick)

        # /kick
        if cmd == '/kick' and prefix in ['[Гл.Админ]','[Владелец]']:
            target = parts[1] if len(parts) > 1 else None
            if target and target in self.players:
                cursor.execute("INSERT OR REPLACE INTO bans VALUES (?,?,datetime('now','+20 minutes'),'Kicked')", (self.name, target))
                conn.commit()
                del self.players[target]
                return f"Игрок {target} выгнан на 20 минут"

        # /ban
        elif cmd == '/ban' and prefix in ['[Гл.Админ]','[Владелец]']:
            try:
                hours = int(parts[1])
                target = parts[3] if len(parts) > 3 else parts[2]
                reason = ' '.join(parts[2:-1]) if len(parts) > 3 else 'Нарушение'
                cursor.execute("INSERT OR REPLACE INTO bans VALUES (?,?,datetime('now','+{} hours'),?)".format(hours), (self.name, target, reason))
                conn.commit()
                if target in self.players: del self.players[target]
                return f"Игрок {target} забанен на {hours}ч. Причина: {reason}"
            except: return "Формат: /ban 24 Причина Ник"

        # /systemmessage
        elif cmd == '/systemmessage' and prefix in ['[Владелец]']:
            try:
                interval = int(parts[-1])
                text = ' '.join(parts[1:-1])
                self.systemMessages[text] = interval
                return f"Системное сообщение установлено каждые {interval} мин"
            except: return "Формат: /systemmessage Текст Интервал"

        # /addadmin
        elif cmd == '/addadmin' and prefix in ['[Гл.Админ]','[Владелец]']:
            try:
                target = parts[1]
                level = int(parts[2])
                if level < 1 or level > 5: return "Уровень 1-5"
                cursor.execute("INSERT OR REPLACE INTO server_admins VALUES (?,?,?)", (self.name, target, level))
                conn.commit()
                return f"Админ {target} добавлен (ур.{level})"
            except: return "Формат: /addadmin Ник Уровень"

        # /removeadmin
        elif cmd == '/removeadmin' and prefix in ['[Гл.Админ]','[Владелец]']:
            try:
                target = parts[1]
                cursor.execute("DELETE FROM server_admins WHERE server_name=? AND nick=?", (self.name, target))
                conn.commit()
                return f"Админ {target} удален"
            except: return "Формат: /removeadmin Ник"

        # /setprefix (для куратора+)
        elif cmd == '/setprefix' and prefix in ['[Куратор]','[Гл.Админ]','[Владелец]']:
            try:
                target = parts[1]
                newPrefix = parts[2]
                cursor.execute("INSERT OR REPLACE INTO player_prefixes VALUES (?,?,?)", (self.name, target, newPrefix))
                conn.commit()
                return f"Префикс {target} изменен на {newPrefix}"
            except: return "Формат: /setprefix Ник Префикс"

        return None

# Хранилище активных серверов
gameServers = {}

def getOrCreateServer(name):
    if name not in gameServers:
        gameServers[name] = GameServer(name)
    return gameServers[name]

# ============ WEBSOCKET ОБРАБОТЧИК ============
async def ws_handler(websocket, path):
    server_name = path.split('/ws/')[-1] if '/ws/' in path else 'YorkTrue'
    gs = getOrCreateServer(server_name)
    nick = None

    try:
        async for message in websocket:
            data = json.loads(message)

            if data['type'] == 'auth':
                nick = data['nick']
                session = data['session']
                # Проверка сессии
                cursor.execute("SELECT nick FROM sessions WHERE session=? AND expires > datetime('now')", (session,))
                if not cursor.fetchone():
                    await websocket.send(json.dumps({'type': 'error', 'msg': 'Сессия истекла'}))
                    continue
                if not gs.canJoin(nick):
                    await websocket.send(json.dumps({'type': 'kicked'}))
                    continue
                gs.players[nick] = {'x': 10, 'y': 10, 'inventory': [], 'prefix': gs.getPlayerPrefix(nick)}
                await websocket.send(json.dumps({'type': 'state', 'state': gs.getState()}))

            elif data['type'] == 'click' and nick:
                x, y = data['x'], data['y']
                slot = data.get('slot', 0)
                if 0 <= x < gs.mapW and 0 <= y < gs.mapH:
                    block = gs.map[y][x]
                    # Рубка ресурсов
                    if block in ['wood','stone','gold_ore','diamond_ore']:
                        gs.map[y][x] = 'grass'
                        # Через время трава восстановится (упрощенно)
                        await asyncio.sleep(30)
                        if gs.map[y][x] == 'grass':
                            gs.map[y][x] = block
                    # Строительство
                    elif block == 'grass' and slot < len(gs.players[nick]['inventory']):
                        item = gs.players[nick]['inventory'][slot]
                        if item['type'] in ['wood_block','stone_block','obsidian','tnt']:
                            gs.map[y][x] = item['type']
                            gs.blockOwners[(x,y)] = nick

            elif data['type'] == 'chat' and nick:
                msg = data['msg']
                if msg.startswith('/'):
                    result = gs.handleCommand(nick, msg)
                    if result:
                        await websocket.send(json.dumps({'type': 'chat', 'msg': f'[СИСТЕМА] {result}'}))
                else:
                    prefix = gs.getPlayerPrefix(nick)
                    chatMsg = f'{prefix} {nick}: {msg}'
                    # Рассылка всем
                    for pNick, pData in gs.players.items():
                        # Отправка через websocket (упрощенно)
                        pass

            # Отправка состояния
            await websocket.send(json.dumps({'type': 'state', 'state': gs.getState()}))

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if nick and nick in gs.players:
            del gs.players[nick]

# ============ HTTP СЕРВЕР ============
class APIHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)
        data = json.loads(body)

        if self.path == '/api/register':
            nick = data['nick']
            password = hashlib.sha256(data['password'].encode()).hexdigest()
            try:
                cursor.execute("INSERT INTO users VALUES (?,?,datetime('now'))", (nick, password))
                conn.commit()
                self.send_json({'ok': True})
            except:
                self.send_json({'error': 'Ник занят'})

        elif self.path == '/api/login':
            nick = data['nick']
            password = hashlib.sha256(data['password'].encode()).hexdigest()
            cursor.execute("SELECT password FROM users WHERE nick=?", (nick,))
            row = cursor.fetchone()
            if row and row[0] == password:
                session = hashlib.sha256(f"{nick}{time.time()}".encode()).hexdigest()
                cursor.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,datetime('now','+24 hours'))", (nick, session))
                conn.commit()
                self.send_json({'session': session})
            else:
                self.send_json({'error': 'Неверный логин/пароль'})

    def do_GET(self):
        if self.path == '/api/servers':
            cursor.execute("SELECT name, firstIp, secondIp, maxPlayers FROM servers")
            servers = []
            for row in cursor.fetchall():
                gs = getOrCreateServer(row[0])
                servers.append({
                    'name': row[0],
                    'firstIp': row[1],
                    'secondIp': row[2],
                    'maxPlayers': row[3],
                    'players': len(gs.players)
                })
            self.send_json(servers)
        else:
            super().do_GET()

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

# ============ САМОПИНГ ============
def self_ping():
    while True:
        try:
            requests.get('https://york-server-ffa3.onrender.com', timeout=10)
            print(f"[PING] {datetime.now()} - OK")
        except Exception as e:
            print(f"[PING] Error: {e}")
        time.sleep(300)  # 5 минут

# ============ ЗАПУСК ============
async def main():
    # HTTP сервер в отдельном потоке
    httpd = HTTPServer(('0.0.0.0', 8000), APIHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    # WebSocket сервер
    ws_server = await websockets.serve(ws_handler, '0.0.0.0', 8080)

    # Самопинг
    threading.Thread(target=self_ping, daemon=True).start()

    print("Сервер запущен: HTTP:8000, WS:8080")
    await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(main())
