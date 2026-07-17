from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import sqlite3
import os
import random
import json
import time

app = Flask(__name__)
CORS(app)

def get_db():
    conn = sqlite3.connect('york.db')
    conn.row_factory = sqlite3.Row
    return conn

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
            iron INTEGER DEFAULT 0,
            dynamite INTEGER DEFAULT 0,
            gold INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS world (
            x INTEGER,
            y INTEGER,
            block_type TEXT,
            owner TEXT,
            server_id INTEGER DEFAULT 1,
            PRIMARY KEY (x, y, server_id)
        );
        CREATE TABLE IF NOT EXISTS chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            message TEXT,
            server_id INTEGER DEFAULT 1,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
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
    cur.execute("INSERT OR IGNORE INTO players (username, password, is_admin) VALUES ('cursed_pharaon', 'lokaloka1472', 1)")
    cur.execute("INSERT OR IGNORE INTO resources (username, wood, stone, iron, dynamite, gold) VALUES ('cursed_pharaon', 100, 50, 20, 10, 5)")
    cur.execute("INSERT OR IGNORE INTO servers (id, name, admin, size, wipe_days) VALUES (1, 'York Wibe', 'cursed_pharaon', 150, 30)")
    
    cur.execute("SELECT COUNT(*) FROM world")
    if cur.fetchone()[0] == 0:
        size = 150
        for x in range(size):
            for y in range(size):
                r = random.random()
                if r < 0.15:
                    block = 'water'
                elif r < 0.30:
                    block = 'stone'
                elif r < 0.50:
                    block = 'tree'
                elif r < 0.55:
                    block = 'iron'
                elif r < 0.58:
                    block = 'gold'
                else:
                    block = 'grass'
                cur.execute("INSERT INTO world (x, y, block_type, server_id) VALUES (?, ?, ?, 1)", (x, y, block))
    
    conn.commit()
    conn.close()

# === API ===
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user, pwd = data.get('username'), data.get('password')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE username=? AND password=?", (user, pwd))
    row = cur.fetchone()
    conn.close()
    if row:
        return jsonify({'success': True, 'is_admin': row['is_admin']})
    return jsonify({'success': False, 'error': 'Неверный логин или пароль'})

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    user, pwd = data.get('username'), data.get('password')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE username=?", (user,))
    if cur.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Игрок уже существует'})
    cur.execute("INSERT INTO players (username, password) VALUES (?, ?)", (user, pwd))
    cur.execute("INSERT INTO resources (username, wood, stone, iron, dynamite, gold) VALUES (?, 20, 10, 0, 0, 0)", (user,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_resources', methods=['POST'])
def get_resources():
    data = request.json
    user = data.get('username')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT wood, stone, iron, dynamite, gold FROM resources WHERE username=?", (user,))
    row = cur.fetchone()
    conn.close()
    if row:
        return jsonify(dict(row))
    return jsonify({'wood': 0, 'stone': 0, 'iron': 0, 'dynamite': 0, 'gold': 0})

@app.route('/save_resources', methods=['POST'])
def save_resources():
    data = request.json
    user = data.get('username')
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''UPDATE resources SET wood=?, stone=?, iron=?, dynamite=?, gold=? WHERE username=?''',
                (data['wood'], data['stone'], data['iron'], data['dynamite'], data['gold'], user))
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
    rows = cur.fetchall()
    conn.close()
    world = {}
    for row in rows:
        world[f"{row['x']},{row['y']}"] = {'type': row['block_type'], 'owner': row['owner']}
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

@app.route('/send_chat', methods=['POST'])
def send_chat():
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO chat (username, message, server_id) VALUES (?, ?, ?)",
                (data['username'], data['message'], data.get('server_id', 1)))
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
    return jsonify([dict(row) for row in rows])

# === SSE: Чат в реальном времени ===
@app.route('/stream_chat')
def stream_chat():
    def generate():
        last_id = 0
        while True:
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT id, username, message, timestamp FROM chat WHERE id > ? ORDER BY id ASC", (last_id,))
                rows = cur.fetchall()
                conn.close()
                for row in rows:
                    last_id = row['id']
                    yield f"data: {json.dumps({'user': row['username'], 'msg': row['message'], 'time': row['timestamp']})}\n\n"
                time.sleep(0.5)
            except Exception as e:
                print("SSE ошибка:", e)
                time.sleep(1)
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
