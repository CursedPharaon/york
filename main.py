

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import requests
import json
import time
import hashlib
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ========== ПОДКЛЮЧЕНИЕ К TURSO ЧЕРЕЗ HTTP API ==========
TURSO_URL = "libsql://york-cursedd.aws-eu-west-1.turso.io"  # Твой URL базы
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODQzMTgzMTQsImlkIjoiMDE5ZjZmNzgtZGEwMS03ZmMwLThjNzgtOWUwNTIxYzdjMGIyIiwia2lkIjoicWpYbEhLbElGQmJNX29uRDlaWEkyWFVfazVBT3h3X3JIMF9TcUZ6MmU0ZyIsInJpZCI6ImRhMmVhODNiLTM0NTYtNDYwNy1iMmJiLTFmNWY1NWM0MDFhMiJ9.OBuKhFXzEJZO2JNPqQdRzOtsbdzHjADvFf5fAY-rcvJ-9Uu9rWmJHlmCeilammNOG8RRXpz1QTNbDGeuxKCSAQ"

def execute_query(sql, params=None):
    """Отправляет SQL-запрос в Turso через HTTP API"""
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {"sql": sql}
    if params:
        data["args"] = params
    try:
        response = requests.post(TURSO_URL, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        return result.get("result", {})
    except Exception as e:
        print(f"Ошибка выполнения SQL: {e}")
        return {"error": str(e)}

# ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ==========
def init_db():
    # Таблица игроков
    execute_query("""
        CREATE TABLE IF NOT EXISTS players (
            username TEXT PRIMARY KEY,
            password TEXT,
            is_admin INTEGER DEFAULT 0
        )
    """)
    # Таблица ресурсов
    execute_query("""
        CREATE TABLE IF NOT EXISTS resources (
            username TEXT PRIMARY KEY,
            wood INTEGER DEFAULT 0,
            stone INTEGER DEFAULT 0,
            iron INTEGER DEFAULT 0,
            dynamite INTEGER DEFAULT 0,
            gold INTEGER DEFAULT 0,
            pickaxe INTEGER DEFAULT 0,
            axe INTEGER DEFAULT 0,
            upgraded_dynamite INTEGER DEFAULT 0
        )
    """)
    # Таблица мира
    execute_query("""
        CREATE TABLE IF NOT EXISTS world (
            x INTEGER,
            y INTEGER,
            block_type TEXT,
            owner TEXT,
            house_level INTEGER DEFAULT 1,
            server_id INTEGER DEFAULT 1,
            PRIMARY KEY (x, y, server_id)
        )
    """)
    # Таблица чата
    execute_query("""
        CREATE TABLE IF NOT EXISTS chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            message TEXT,
            server_id INTEGER DEFAULT 1,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Таблица серверов
    execute_query("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            admin TEXT NOT NULL,
            size INTEGER DEFAULT 150,
            wipe_days INTEGER DEFAULT 30,
            tariff TEXT DEFAULT 'free',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Добавляем админа
    execute_query("INSERT OR IGNORE INTO players (username, password, is_admin) VALUES ('cursed_pharaon', ?, 1)", 
                  (hashlib.sha256('lokaloka1472'.encode()).hexdigest(),))
    # Добавляем сервер
    execute_query("INSERT OR IGNORE INTO servers (id, name, admin, size, wipe_days) VALUES (1, 'York Wibe', 'cursed_pharaon', 150, 30)")
    print("✅ База данных инициализирована!")

# ========== ВСЕ МАРШРУТЫ ==========
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    result = execute_query("SELECT username, password, is_admin FROM players WHERE username=?", (username,))
    rows = result.get('rows', [])
    if not rows:
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'})
    
    user = rows[0]
    if user[1] != hashlib.sha256(password.encode()).hexdigest():
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'})
    
    return jsonify({'success': True, 'is_admin': user[2] == 1})

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    result = execute_query("SELECT username FROM players WHERE username=?", (username,))
    if result.get('rows'):
        return jsonify({'success': False, 'error': 'Пользователь уже существует'})
    
    hashed = hashlib.sha256(password.encode()).hexdigest()
    execute_query("INSERT INTO players (username, password) VALUES (?, ?)", (username, hashed))
    execute_query("INSERT INTO resources (username) VALUES (?)", (username,))
    return jsonify({'success': True})

@app.route('/get_resources', methods=['POST'])
def get_resources():
    data = request.json
    username = data.get('username')
    result = execute_query("SELECT wood, stone, iron, dynamite, gold, pickaxe, axe, upgraded_dynamite FROM resources WHERE username=?", (username,))
    rows = result.get('rows', [])
    if rows:
        row = rows[0]
        return jsonify({
            'wood': row[0] or 0,
            'stone': row[1] or 0,
            'iron': row[2] or 0,
            'dynamite': row[3] or 0,
            'gold': row[4] or 0,
            'pickaxe': row[5] or 0,
            'axe': row[6] or 0,
            'upgraded_dynamite': row[7] or 0
        })
    return jsonify({'wood': 0, 'stone': 0, 'iron': 0, 'dynamite': 0, 'gold': 0, 'pickaxe': 0, 'axe': 0, 'upgraded_dynamite': 0})

@app.route('/save_resources', methods=['POST'])
def save_resources():
    data = request.json
    username = data.get('username')
    execute_query("""
        UPDATE resources SET wood=?, stone=?, iron=?, dynamite=?, gold=?, pickaxe=?, axe=?, upgraded_dynamite=?
        WHERE username=?
    """, (data.get('wood', 0), data.get('stone', 0), data.get('iron', 0), 
          data.get('dynamite', 0), data.get('gold', 0), data.get('pickaxe', 0), 
          data.get('axe', 0), data.get('upgraded_dynamite', 0), username))
    return jsonify({'success': True})

@app.route('/get_world', methods=['POST'])
def get_world():
    data = request.json
    server_id = data.get('server_id', 1)
    result = execute_query("SELECT x, y, block_type, owner, house_level FROM world WHERE server_id=?", (server_id,))
    world = {}
    for row in result.get('rows', []):
        world[f"{row[0]},{row[1]}"] = {
            'type': row[2],
            'owner': row[3],
            'house_level': row[4] or 1
        }
    return jsonify(world)

@app.route('/save_world', methods=['POST'])
def save_world():
    data = request.json
    server_id = data.get('server_id', 1)
    cells = data.get('cells')
    
    execute_query("DELETE FROM world WHERE server_id=?", (server_id,))
    for key, val in cells.items():
        x, y = map(int, key.split(','))
        execute_query("""
            INSERT INTO world (x, y, block_type, owner, house_level, server_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (x, y, val['type'], val.get('owner'), val.get('house_level', 1), server_id))
    return jsonify({'success': True})

@app.route('/send_chat', methods=['POST'])
def send_chat():
    data = request.json
    execute_query("INSERT INTO chat (username, message, server_id) VALUES (?, ?, ?)",
                 (data['username'], data['message'], data.get('server_id', 1)))
    return jsonify({'success': True})

@app.route('/get_chat', methods=['POST'])
def get_chat():
    data = request.json
    server_id = data.get('server_id', 1)
    result = execute_query("SELECT username, message, timestamp FROM chat WHERE server_id=? ORDER BY id DESC LIMIT 50", (server_id,))
    chat = []
    for row in reversed(result.get('rows', [])):
        chat.append({'user': row[0], 'msg': row[1], 'time': row[2]})
    return jsonify(chat)

@app.route('/get_servers', methods=['POST'])
def get_servers():
    result = execute_query("SELECT id, name, admin, size, wipe_days, tariff FROM servers ORDER BY id")
    servers = []
    for row in result.get('rows', []):
        servers.append({
            'id': row[0],
            'name': row[1],
            'admin': row[2],
            'size': row[3],
            'wipe_days': row[4],
            'tariff': row[5]
        })
    return jsonify(servers)

@app.route('/stream_chat')
def stream_chat():
    def generate():
        last_id = 0
        while True:
            try:
                result = execute_query("SELECT id, username, message, timestamp FROM chat WHERE id > ? ORDER BY id ASC", (last_id,))
                for row in result.get('rows', []):
                    last_id = row[0]
                    yield f"data: {json.dumps({'user': row[1], 'msg': row[2], 'time': row[3]})}\n\n"
                time.sleep(0.5)
            except:
                time.sleep(1)
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
