from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import sqlite3
import os
import json
import time
import hashlib
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ========== ТВОЯ БАЗА ==========
DB_PATH = "york.db"  # SQLite локально, но для Turso используем URL

# Для Turso используй libsql_client
import libsql_client

TURSO_URL = "libsql://york-ваш-хэндл.turso.io"  # ЗАМЕНИ НА ТВОЙ URL
TURSO_TOKEN = "твой_токен"  # ЗАМЕНИ НА ТВОЙ ТОКЕН

def get_db():
    return libsql_client.connect(TURSO_URL, auth_token=TURSO_TOKEN)

# ========== ВСЕ ТАБЛИЦЫ ДЛЯ ТВОЕЙ БАЗЫ ==========
def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            username TEXT PRIMARY KEY,
            password TEXT,
            is_admin INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
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
    conn.execute("""
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            message TEXT,
            server_id INTEGER DEFAULT 1,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
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
    # Добавляем твой аккаунт
    conn.execute("INSERT OR IGNORE INTO players (username, password, is_admin) VALUES ('cursed_pharaon', ?, 1)", 
                 (hashlib.sha256('lokaloka1472'.encode()).hexdigest(),))
    # Добавляем сервер York Wibe
    conn.execute("INSERT OR IGNORE INTO servers (id, name, admin, size, wipe_days) VALUES (1, 'York Wibe', 'cursed_pharaon', 150, 30)")
    conn.commit()
    conn.close()
    print("✅ База данных york инициализирована!")

# ========== ВСЕ МАРШРУТЫ ==========
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    conn = get_db()
    cur = conn.execute("SELECT username, password, is_admin FROM players WHERE username=?", (username,))
    user = cur.fetchone()
    conn.close()
    
    if not user or user[1] != hashlib.sha256(password.encode()).hexdigest():
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'})
    
    return jsonify({'success': True, 'is_admin': user[2] == 1})

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    conn = get_db()
    cur = conn.execute("SELECT username FROM players WHERE username=?", (username,))
    if cur.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Пользователь уже существует'})
    
    conn.execute("INSERT INTO players (username, password) VALUES (?, ?)", 
                 (username, hashlib.sha256(password.encode()).hexdigest()))
    conn.execute("INSERT INTO resources (username) VALUES (?)", (username,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_resources', methods=['POST'])
def get_resources():
    data = request.json
    username = data.get('username')
    conn = get_db()
    cur = conn.execute("SELECT wood, stone, iron, dynamite, gold, pickaxe, axe, upgraded_dynamite FROM resources WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    if row:
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
    conn = get_db()
    conn.execute("""
        UPDATE resources SET wood=?, stone=?, iron=?, dynamite=?, gold=?, pickaxe=?, axe=?, upgraded_dynamite=?
        WHERE username=?
    """, (data.get('wood', 0), data.get('stone', 0), data.get('iron', 0), 
          data.get('dynamite', 0), data.get('gold', 0), data.get('pickaxe', 0), 
          data.get('axe', 0), data.get('upgraded_dynamite', 0), username))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_world', methods=['POST'])
def get_world():
    data = request.json
    server_id = data.get('server_id', 1)
    conn = get_db()
    rows = conn.execute("SELECT x, y, block_type, owner, house_level FROM world WHERE server_id=?", (server_id,)).fetchall()
    conn.close()
    world = {}
    for row in rows:
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
    conn = get_db()
    conn.execute("DELETE FROM world WHERE server_id=?", (server_id,))
    for key, val in cells.items():
        x, y = map(int, key.split(','))
        conn.execute("""
            INSERT INTO world (x, y, block_type, owner, house_level, server_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (x, y, val['type'], val.get('owner'), val.get('house_level', 1), server_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/send_chat', methods=['POST'])
def send_chat():
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO chat (username, message, server_id) VALUES (?, ?, ?)",
                 (data['username'], data['message'], data.get('server_id', 1)))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_chat', methods=['POST'])
def get_chat():
    data = request.json
    server_id = data.get('server_id', 1)
    conn = get_db()
    rows = conn.execute("SELECT username, message, timestamp FROM chat WHERE server_id=? ORDER BY id DESC LIMIT 50", (server_id,)).fetchall()
    conn.close()
    chat = []
    for row in reversed(rows):
        chat.append({'user': row[0], 'msg': row[1], 'time': row[2]})
    return jsonify(chat)

@app.route('/get_servers', methods=['POST'])
def get_servers():
    conn = get_db()
    rows = conn.execute("SELECT id, name, admin, size, wipe_days, tariff FROM servers ORDER BY id").fetchall()
    conn.close()
    servers = []
    for row in rows:
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
                conn = get_db()
                rows = conn.execute("SELECT id, username, message, timestamp FROM chat WHERE id > ? ORDER BY id ASC", (last_id,)).fetchall()
                conn.close()
                for row in rows:
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
