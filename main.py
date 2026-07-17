from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import json
import os
import random

app = Flask(__name__)
CORS(app)

# Подключение к Turso
def get_db():
    conn = sqlite3.connect('york.db')
    conn.row_factory = sqlite3.Row
    return conn

# Создание таблиц, если их нет
def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript('''
        CREATE TABLE IF NOT EXISTS players (
            username TEXT PRIMARY KEY,
            password TEXT,
            is_admin INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS resources (
            username TEXT PRIMARY KEY,
            wood INTEGER DEFAULT 0,
            stone INTEGER DEFAULT 0,
            dynamite INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS world (
            x INTEGER,
            y INTEGER,
            block_type TEXT,
            owner TEXT,
            PRIMARY KEY (x, y)
        );
        CREATE TABLE IF NOT EXISTS chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            message TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS worlds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            owner TEXT,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            admin TEXT,
            size INTEGER,
            wipe_days INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # Добавляем админа, если его нет
    cur.execute("INSERT OR IGNORE INTO players (username, password, is_admin) VALUES (?, ?, ?)",
                ('cursed_pharaon', 'lokaloka1472', 1))
    # Добавляем ресурсы админа
    cur.execute("INSERT OR IGNORE INTO resources (username, wood, stone, dynamite) VALUES (?, ?, ?, ?)",
                ('cursed_pharaon', 100, 50, 10))
    # Добавляем сервер
    cur.execute("INSERT OR IGNORE INTO servers (id, name, admin, size, wipe_days) VALUES (1, 'York Wibe', 'cursed_pharaon', 150, 30)")
    conn.commit()
    conn.close()

# ========== API ==========

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE username=?", (username,))
    user = cur.fetchone()
    conn.close()
    if user and user['password'] == password:
        return jsonify({'success': True, 'is_admin': user['is_admin']})
    return jsonify({'success': False, 'error': 'Неверный логин или пароль'})

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE username=?", (username,))
    if cur.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Игрок уже существует'})
    cur.execute("INSERT INTO players (username, password) VALUES (?, ?)", (username, password))
    cur.execute("INSERT INTO resources (username, wood, stone, dynamite) VALUES (?, ?, ?, ?)", (username, 20, 10, 0))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_resources', methods=['POST'])
def get_resources():
    data = request.json
    username = data.get('username')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT wood, stone, dynamite FROM resources WHERE username=?", (username,))
    res = cur.fetchone()
    conn.close()
    if res:
        return jsonify({'wood': res['wood'], 'stone': res['stone'], 'dynamite': res['dynamite']})
    return jsonify({'wood': 0, 'stone': 0, 'dynamite': 0})

@app.route('/save_resources', methods=['POST'])
def save_resources():
    data = request.json
    username = data.get('username')
    wood = data.get('wood')
    stone = data.get('stone')
    dynamite = data.get('dynamite')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE resources SET wood=?, stone=?, dynamite=? WHERE username=?", (wood, stone, dynamite, username))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_world', methods=['POST'])
def get_world():
    data = request.json
    server_id = data.get('server_id', 1)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT x, y, block_type, owner FROM world WHERE server_id=?", (server_id,))
    cells = cur.fetchall()
    conn.close()
    world = {}
    for cell in cells:
        world[f"{cell['x']},{cell['y']}"] = {'type': cell['block_type'], 'owner': cell['owner']}
    return jsonify(world)

@app.route('/save_world', methods=['POST'])
def save_world():
    data = request.json
    server_id = data.get('server_id', 1)
    cells = data.get('cells')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM world WHERE server_id=?", (server_id,))
    for key, val in cells.items():
        x, y = map(int, key.split(','))
        cur.execute("INSERT INTO world (x, y, block_type, owner, server_id) VALUES (?, ?, ?, ?, ?)",
                    (x, y, val['type'], val.get('owner'), server_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_chat', methods=['POST'])
def get_chat():
    data = request.json
    server_id = data.get('server_id', 1)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, message, timestamp FROM chat WHERE server_id=? ORDER BY id DESC LIMIT 50", (server_id,))
    rows = cur.fetchall()
    conn.close()
    chat = [{'user': row['username'], 'msg': row['message'], 'time': row['timestamp']} for row in reversed(rows)]
    return jsonify(chat)

@app.route('/send_chat', methods=['POST'])
def send_chat():
    data = request.json
    username = data.get('username')
    message = data.get('message')
    server_id = data.get('server_id', 1)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO chat (username, message, server_id) VALUES (?, ?, ?)", (username, message, server_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_servers', methods=['GET'])
def get_servers():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM servers")
    rows = cur.fetchall()
    conn.close()
    servers = [dict(row) for row in rows]
    return jsonify(servers)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
