from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import libsql_client
import hashlib
import os
import time
import json
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ========== ПОДКЛЮЧЕНИЕ К TURSO ==========
TURSO_URL = "libsql://vk-bot-cursedd.aws-eu-west-1.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODQyOTA1NDAsImlkIjoiMDE5ZjcwMDAtOTcwMS03NDJjLWIwM2EtNzA0MTQ2MDk4ZWI2Iiwia2lkIjoicWpYbEhLbElGQmJNX29uRDlaWEkyWFVfazVBT3h3X3JIMF9TcUZ6MmU0ZyIsInJpZCI6ImM3OTFiYzM5LTg3YjktNDgwZC1iZjRkLTEwMDdiNTI1YTg2NCJ9.rvnr8-mOPA7ydTmVKb1C4QDIxA_se-HSIiGQX5OaJ9vnj89C4xJ5PZnHn5ldw4eQMf-5pRXztvisg-chcKj4Dw"

def get_db():
    # Новый синтаксис для libsql-client 0.3.1
    return libsql_client.connect_sync(TURSO_URL, auth_token=TURSO_TOKEN)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ==========
def init_db():
    conn = get_db()
    
    # Таблица пользователей хостинга
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hosting_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            balance REAL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица серверов хостинга
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hosting_servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            server_name TEXT,
            admin_nick TEXT,
            map_size INTEGER DEFAULT 150,
            wipe_days INTEGER DEFAULT 30,
            tariff TEXT DEFAULT 'free',
            status TEXT DEFAULT 'offline',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES hosting_users(id)
        )
    """)
    
    # Таблица серверов игры
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
    
    # Таблица ресурсов
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
    
    # Таблица мира
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
    
    # Таблица чата
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            message TEXT,
            server_id INTEGER DEFAULT 1,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Создаём админа
    conn.execute("INSERT OR IGNORE INTO hosting_users (username, password, balance) VALUES ('cursed_pharaon', ?, 1000)", (hash_password('lokaloka1472'),))
    
    # Создаём тестовый сервер
    conn.execute("INSERT OR IGNORE INTO servers (id, name, admin, size, wipe_days) VALUES (1, 'York Wibe', 'cursed_pharaon', 150, 30)")
    
    conn.commit()
    conn.close()

# ========== РЕГИСТРАЦИЯ ==========
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    conn = get_db()
    cur = conn.execute("SELECT id FROM hosting_users WHERE username=?", (username,))
    if cur.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Пользователь уже существует'})
    conn.execute("INSERT INTO hosting_users (username, password, balance) VALUES (?, ?, 0)", (username, hash_password(password)))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ========== ЛОГИН ==========
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    conn = get_db()
    cur = conn.execute("SELECT id, username, password, balance FROM hosting_users WHERE username=?", (username,))
    user = cur.fetchone()
    conn.close()
    if not user or user[2] != hash_password(password):
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'})
    return jsonify({
        'success': True,
        'user': {
            'id': user[0],
            'username': user[1],
            'balance': user[3]
        }
    })

# ========== ПОЛУЧИТЬ СЕРВЕРА ==========
@app.route('/get_servers', methods=['POST'])
def get_servers():
    data = request.json
    user_id = data.get('user_id')
    conn = get_db()
    rows = conn.execute("""
        SELECT id, server_name, admin_nick, map_size, wipe_days, tariff, status, created_at
        FROM hosting_servers
        WHERE user_id=?
        ORDER BY created_at DESC
    """, (user_id,)).fetchall()
    conn.close()
    servers = []
    for row in rows:
        servers.append({
            'id': row[0],
            'name': row[1],
            'admin': row[2],
            'size': row[3],
            'wipe': row[4],
            'tariff': row[5],
            'status': row[6],
            'created_at': row[7]
        })
    return jsonify({'success': True, 'servers': servers})

# ========== СОЗДАТЬ СЕРВЕР ==========
@app.route('/create_server', methods=['POST'])
def create_server():
    data = request.json
    user_id = data.get('user_id')
    server_name = data.get('server_name')
    admin_nick = data.get('admin_nick')
    tariff = data.get('tariff', 'free')
    
    if not user_id or not server_name or not admin_nick:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    configs = {
        'free': {'size': 40, 'wipe': 7, 'price': 0},
        'standard': {'size': 150, 'wipe': 30, 'price': 79},
        'premium': {'size': 250, 'wipe': 0, 'price': 199}
    }
    config = configs.get(tariff, {'size': 150, 'wipe': 30, 'price': 0})
    
    conn = get_db()
    cur = conn.execute("SELECT balance FROM hosting_users WHERE id=?", (user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    
    balance = user[0]
    if balance < config['price']:
        conn.close()
        return jsonify({'success': False, 'error': f'Недостаточно средств. Нужно {config["price"]} ₽'})
    
    conn.execute("UPDATE hosting_users SET balance = balance - ? WHERE id=?", (config['price'], user_id))
    
    conn.execute("""
        INSERT INTO servers (name, admin, size, wipe_days, tariff)
        VALUES (?, ?, ?, ?, ?)
    """, (server_name, admin_nick, config['size'], config['wipe'], tariff))
    server_id = conn.last_insert_rowid()
    
    conn.execute("""
        INSERT INTO hosting_servers (user_id, server_name, admin_nick, map_size, wipe_days, tariff, status)
        VALUES (?, ?, ?, ?, ?, ?, 'online')
    """, (user_id, server_name, admin_nick, config['size'], config['wipe'], tariff))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'server_id': server_id})

# ========== ПОЛУЧИТЬ РЕСУРСЫ ==========
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

# ========== СОХРАНИТЬ РЕСУРСЫ ==========
@app.route('/save_resources', methods=['POST'])
def save_resources():
    data = request.json
    username = data.get('username')
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO resources (username, wood, stone, iron, dynamite, gold, pickaxe, axe, upgraded_dynamite)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (username, data.get('wood', 0), data.get('stone', 0), data.get('iron', 0), 
          data.get('dynamite', 0), data.get('gold', 0), data.get('pickaxe', 0), 
          data.get('axe', 0), data.get('upgraded_dynamite', 0)))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ========== ПОЛУЧИТЬ МИР ==========
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

# ========== СОХРАНИТЬ МИР ==========
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

# ========== ОТПРАВИТЬ СООБЩЕНИЕ В ЧАТ ==========
@app.route('/send_chat', methods=['POST'])
def send_chat():
    data = request.json
    username = data.get('username')
    message = data.get('message')
    server_id = data.get('server_id', 1)
    conn = get_db()
    conn.execute("INSERT INTO chat (username, message, server_id) VALUES (?, ?, ?)", (username, message, server_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ========== ПОЛУЧИТЬ ЧАТ ==========
@app.route('/get_chat', methods=['POST'])
def get_chat():
    data = request.json
    server_id = data.get('server_id', 1)
    conn = get_db()
    rows = conn.execute("SELECT username, message, timestamp FROM chat WHERE server_id=? ORDER BY id DESC LIMIT 50", (server_id,)).fetchall()
    conn.close()
    chat = []
    for row in reversed(rows):
        chat.append({
            'user': row[0],
            'msg': row[1],
            'time': row[2]
        })
    return jsonify(chat)

# ========== STREAM CHAT (SSE) ==========
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
            except Exception as e:
                print("SSE ошибка:", e)
                time.sleep(1)
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

# ========== ПОЛУЧИТЬ СПИСОК СЕРВЕРОВ ДЛЯ ИГРЫ ==========
@app.route('/get_game_servers', methods=['GET'])
def get_game_servers():
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
    return jsonify({'success': True, 'servers': servers})

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
