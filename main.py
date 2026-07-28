from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import sqlite3
import hashlib
import time
import threading
import requests
import asyncio
import websockets
from datetime import datetime

# ============ БАЗА ДАННЫХ ============
conn = sqlite3.connect('york.db', check_same_thread=False)
cursor = conn.cursor()

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
        maxPlayers INTEGER DEFAULT 35
    );
    CREATE TABLE IF NOT EXISTS server_admins (
        server_name TEXT,
        nick TEXT,
        level INTEGER
    );
    CREATE TABLE IF NOT EXISTS bans (
        server_name TEXT,
        nick TEXT,
        until TEXT,
        reason TEXT
    );
''')
conn.commit()

# Создаем дефолтный сервер если нет
cursor.execute("SELECT name FROM servers WHERE name='YorkTrue'")
if not cursor.fetchone():
    cursor.execute("INSERT INTO servers VALUES ('YorkTrue', 'free.YorkTrue.york', '', 'cursed_pharaon', 300, 300, 35)")
    cursor.execute("INSERT INTO server_admins VALUES ('YorkTrue', 'cursed_pharaon', 6)")
    conn.commit()
    print("[OK] Сервер YorkTrue создан")

# ============ HTTP ОБРАБОТЧИК ============
class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        
        try:
            data = json.loads(body)
        except:
            self.send_json({'error': 'Invalid JSON'})
            return

        print(f"[POST] {self.path} data={data}")

        if self.path == '/api/register':
            nick = data.get('nick', '').strip()
            password = data.get('password', '').strip()
            
            if not nick or not password:
                self.send_json({'error': 'Заполните все поля'})
                return
            
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            try:
                cursor.execute("INSERT INTO users VALUES (?, ?, datetime('now'))", (nick, password_hash))
                conn.commit()
                print(f"[OK] Зарегистрирован: {nick}")
                self.send_json({'ok': True})
            except sqlite3.IntegrityError:
                self.send_json({'error': 'Ник уже занят'})
            except Exception as e:
                self.send_json({'error': str(e)})

        elif self.path == '/api/login':
            nick = data.get('nick', '').strip()
            password = data.get('password', '').strip()
            
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            cursor.execute("SELECT password FROM users WHERE nick=?", (nick,))
            row = cursor.fetchone()
            
            if row and row[0] == password_hash:
                session = hashlib.sha256(f"{nick}{time.time()}".encode()).hexdigest()
                cursor.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, datetime('now', '+24 hours'))", (nick, session))
                conn.commit()
                print(f"[OK] Вход: {nick}")
                self.send_json({'session': session})
            else:
                self.send_json({'error': 'Неверный логин или пароль'})

        else:
            self.send_json({'error': f'Unknown path: {self.path}'})

    def do_GET(self):
        print(f"[GET] {self.path}")
        
        if self.path == '/api/servers':
            cursor.execute("SELECT name, firstIp, secondIp, maxPlayers FROM servers")
            servers = []
            for row in cursor.fetchall():
                servers.append({
                    'name': row[0],
                    'firstIp': row[1],
                    'secondIp': row[2] or '',
                    'maxPlayers': row[3],
                    'players': 0
                })
            self.send_json(servers)
        
        elif self.path == '/ping':
            self.send_json({'status': 'ok', 'time': str(datetime.now())})
        
        elif self.path == '/' or self.path == '/index.html':
            try:
                with open('york.html', 'r', encoding='utf-8') as f:
                    html = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            except:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b'<h1>York Server OK</h1><p>API is working</p>')
        
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        print(f"[HTTP] {args[0]}")

# ============ WEBSOCKET ============
gameServers = {}

class GameServer:
    def __init__(self, name):
        self.name = name
        self.mapW = 300
        self.mapH = 300
        self.maxPlayers = 35
        self.map = [['grass' for _ in range(self.mapW)] for _ in range(self.mapH)]
        self.players = {}
        self.blockOwners = {}
        
        import random
        for _ in range(500):
            x, y = random.randint(0, self.mapW-1), random.randint(0, self.mapH-1)
            self.map[y][x] = random.choice(['wood', 'stone', 'gold_ore'])

    def getState(self):
        return {
            'map': self.map,
            'players': self.players
        }

async def ws_handler(websocket, path):
    server_name = path.split('/ws/')[-1] if '/ws/' in path else 'YorkTrue'
    
    if server_name not in gameServers:
        gameServers[server_name] = GameServer(server_name)
    
    gs = gameServers[server_name]
    nick = None
    print(f"[WS] Новое подключение к {server_name}")

    try:
        async for message in websocket:
            data = json.loads(message)
            
            if data.get('type') == 'auth':
                nick = data.get('nick', 'anonymous')
                gs.players[nick] = {'x': 10, 'y': 10, 'nick': nick}
                await websocket.send(json.dumps({'type': 'state', 'state': gs.getState()}))
                print(f"[WS] {nick} зашел на {server_name}")
            
            elif data.get('type') == 'chat':
                msg = data.get('msg', '')
                print(f"[CHAT] {nick}: {msg}")
                await websocket.send(json.dumps({'type': 'chat', 'msg': f'[Игрок] {nick}: {msg}'}))
            
            elif data.get('type') == 'click':
                x, y = data.get('x', 0), data.get('y', 0)
                if 0 <= y < len(gs.map) and 0 <= x < len(gs.map[0]):
                    block = gs.map[y][x]
                    if block in ['wood', 'stone', 'gold_ore']:
                        gs.map[y][x] = 'grass'
                        print(f"[WS] {nick} сломал {block} на {x},{y}")
                    elif block == 'grass':
                        gs.map[y][x] = 'wood_block'
                        gs.blockOwners[(x,y)] = nick
                        print(f"[WS] {nick} поставил блок на {x},{y}")
                
                await websocket.send(json.dumps({'type': 'state', 'state': gs.getState()}))

    except websockets.exceptions.ConnectionClosed:
        print(f"[WS] Отключение")
    finally:
        if nick and nick in gs.players:
            del gs.players[nick]

# ============ САМОПИНГ ============
def self_ping():
    while True:
        try:
            r = requests.get('https://york-server-ffa3.onrender.com/ping', timeout=10)
            print(f"[PING] {datetime.now()} - Status: {r.status_code}")
        except Exception as e:
            print(f"[PING] Error: {e}")
        time.sleep(300)

# ============ ЗАПУСК ============
async def main():
    # HTTP
    httpd = HTTPServer(('0.0.0.0', int(os.environ.get('PORT', 8000))), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"[HTTP] Сервер запущен на порту {os.environ.get('PORT', 8000)}")

    # WebSocket
    ws_port = int(os.environ.get('PORT', 8080))
    async with websockets.serve(ws_handler, '0.0.0.0', ws_port):
        print(f"[WS] WebSocket запущен на порту {ws_port}")
        await asyncio.Future()

if __name__ == '__main__':
    import os
    # Запускаем самопинг в фоне
    threading.Thread(target=self_ping, daemon=True).start()
    # Запускаем сервер
    asyncio.run(main())
