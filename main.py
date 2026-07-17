from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import sqlite3
import os
import random
import json
import time
import re
from datetime import datetime, timedelta

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
            is_admin INTEGER DEFAULT 0,
            admin_level INTEGER DEFAULT 0,
            banned_until TEXT DEFAULT NULL,
            muted_until TEXT DEFAULT NULL
        );
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
        );
        CREATE TABLE IF NOT EXISTS world (
            x INTEGER,
            y INTEGER,
            block_type TEXT,
            owner TEXT,
            server_id INTEGER DEFAULT 1,
            house_level INTEGER DEFAULT 1,
            PRIMARY KEY (x, y, server_id)
        );
        CREATE TABLE IF NOT EXISTS house_inventories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT,
            x INTEGER,
            y INTEGER,
            slot INTEGER,
            item_type TEXT,
            amount INTEGER DEFAULT 1
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
        CREATE TABLE IF NOT EXISTS bans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            admin TEXT,
            reason TEXT,
            until TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # Админ (владыка)
    cur.execute("INSERT OR IGNORE INTO players (username, password, is_admin, admin_level) VALUES ('cursed_pharaon', 'lokaloka1472', 1, 4)")
    cur.execute("INSERT OR IGNORE INTO resources (username, wood, stone, iron, dynamite, gold, pickaxe, axe, upgraded_dynamite) VALUES ('cursed_pharaon', 100, 50, 20, 10, 5, 1, 1, 0)")
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
    print("✅ База данных инициализирована!")

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def get_player(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return row

def get_resources(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM resources WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return row

def update_resources(username, **kwargs):
    if not kwargs:
        return
    conn = get_db()
    cur = conn.cursor()
    set_str = ', '.join([f"{k}=?" for k in kwargs.keys()])
    query = f"UPDATE resources SET {set_str} WHERE username=?"
    cur.execute(query, list(kwargs.values()) + [username])
    conn.commit()
    conn.close()

def get_house_inventory(owner):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM house_inventories WHERE owner=?", (owner,))
    rows = cur.fetchall()
    conn.close()
    return rows

def clear_house_inventory(owner):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM house_inventories WHERE owner=?", (owner,))
    conn.commit()
    conn.close()

def add_house_item(owner, x, y, item_type, amount=1):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO house_inventories (owner, x, y, item_type, amount) VALUES (?, ?, ?, ?, ?)", 
                (owner, x, y, item_type, amount))
    conn.commit()
    conn.close()

def get_house_level(x, y):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT house_level FROM world WHERE x=? AND y=? AND block_type='house'", (x, y))
    row = cur.fetchone()
    conn.close()
    return row['house_level'] if row else 1

def update_house_level(x, y, new_level):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE world SET house_level=? WHERE x=? AND y=?", (new_level, x, y))
    conn.commit()
    conn.close()

def is_admin_level(username):
    player = get_player(username)
    if not player:
        return 0
    return player['admin_level'] if player['is_admin'] else 0

def parse_time(duration_str):
    """Парсит 1h, 30m, 1d в секунды"""
    match = re.match(r'(\d+)([hmd])', duration_str)
    if not match:
        return None
    num = int(match.group(1))
    unit = match.group(2)
    if unit == 'm':
        return num * 60
    elif unit == 'h':
        return num * 3600
    elif unit == 'd':
        return num * 86400
    return None

def format_time(seconds):
    if seconds >= 86400:
        return f"{seconds//86400}д"
    elif seconds >= 3600:
        return f"{seconds//3600}ч"
    else:
        return f"{seconds//60}м"

def get_admin_prefix(level):
    prefixes = {
        1: '[Модератор]',
        2: '[Ст.Модератор]',
        3: '[Куратор]',
        4: '[Владыка]'
    }
    return prefixes.get(level, '[Игрок]')

# === АДМИН-КОМАНДЫ (через API) ===
@app.route('/admin_command', methods=['POST'])
def admin_command():
    data = request.json
    admin = data.get('admin')
    command = data.get('command')  # полная строка команды
    target = data.get('target')
    reason = data.get('reason')
    duration = data.get('duration')
    level = data.get('level')
    
    admin_level = is_admin_level(admin)
    if admin_level == 0:
        return jsonify({'success': False, 'error': 'У вас нет прав'})
    
    # === /mute ===
    if command == 'mute':
        if admin_level < 1:
            return jsonify({'success': False, 'error': 'Недостаточно прав'})
        if not target or not duration:
            return jsonify({'success': False, 'error': 'Использование: /mute Nick 30m / 1h'})
        secs = parse_time(duration)
        if not secs:
            return jsonify({'success': False, 'error': 'Неверный формат времени'})
        # Для модератора максимум 1 час
        if admin_level == 1 and secs > 3600:
            return jsonify({'success': False, 'error': 'Модератор может мутить только на 1 час максимум'})
        until = (datetime.now() + timedelta(seconds=secs)).isoformat()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE players SET muted_until=? WHERE username=?", (until, target))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Игрок {target} замьючен на {format_time(secs)}'})
    
    # === /unmute ===
    if command == 'unmute':
        if admin_level < 1:
            return jsonify({'success': False, 'error': 'Недостаточно прав'})
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE players SET muted_until=NULL WHERE username=?", (target,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Игрок {target} размьючен'})
    
    # === /ban ===
    if command == 'ban':
        if admin_level < 2:
            return jsonify({'success': False, 'error': 'Недостаточно прав'})
        if not target or not reason:
            return jsonify({'success': False, 'error': 'Использование: /ban Nick причина'})
        until = (datetime.now() + timedelta(days=365*100)).isoformat()  # ~100 лет
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE players SET banned_until=? WHERE username=?", (until, target))
        cur.execute("INSERT INTO bans (username, admin, reason, until) VALUES (?, ?, ?, ?)", (target, admin, reason, until))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Игрок {target} забанен навсегда. Причина: {reason}'})
    
    # === /tempban ===
    if command == 'tempban':
        if admin_level < 2:
            return jsonify({'success': False, 'error': 'Недостаточно прав'})
        if not target or not reason or not duration:
            return jsonify({'success': False, 'error': 'Использование: /tempban Nick причина 1d / 12h'})
        secs = parse_time(duration)
        if not secs:
            return jsonify({'success': False, 'error': 'Неверный формат времени'})
        until = (datetime.now() + timedelta(seconds=secs)).isoformat()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE players SET banned_until=? WHERE username=?", (until, target))
        cur.execute("INSERT INTO bans (username, admin, reason, until) VALUES (?, ?, ?, ?)", (target, admin, reason, until))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Игрок {target} забанен на {format_time(secs)}. Причина: {reason}'})
    
    # === /unban ===
    if command == 'unban':
        if admin_level < 2:
            return jsonify({'success': False, 'error': 'Недостаточно прав'})
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE players SET banned_until=NULL WHERE username=?", (target,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Игрок {target} разбанен'})
    
    # === /addadmin ===
    if command == 'addadmin':
        if admin_level < 3:
            return jsonify({'success': False, 'error': 'Только Куратор и выше может назначать администраторов'})
        if not target or not level:
            return jsonify({'success': False, 'error': 'Использование: /addadmin Nick 1/2/3'})
        new_level = int(level)
        if new_level not in [1, 2, 3]:
            return jsonify({'success': False, 'error': 'Уровень должен быть 1, 2 или 3'})
        if new_level >= admin_level:
            return jsonify({'success': False, 'error': 'Нельзя назначать уровень выше или равный вашему'})
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE players SET is_admin=1, admin_level=? WHERE username=?", (new_level, target))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Игрок {target} назначен администратором уровня {new_level} ({get_admin_prefix(new_level)})'})
    
    # === /removeadmin ===
    if command == 'removeadmin':
        if admin_level < 3:
            return jsonify({'success': False, 'error': 'Только Куратор и выше может снимать администраторов'})
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE players SET is_admin=0, admin_level=0 WHERE username=?", (target,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Игрок {target} лишён прав администратора'})
    
    return jsonify({'success': False, 'error': 'Неизвестная команда'})

# === ОСТАЛЬНЫЕ API ===
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user, pwd = data.get('username'), data.get('password')
    player = get_player(user)
    if not player or player['password'] != pwd:
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'})
    if player['banned_until'] and datetime.now() < datetime.fromisoformat(player['banned_until']):
        return jsonify({'success': False, 'error': f'Вы забанены до {player["banned_until"]}'})
    return jsonify({
        'success': True, 
        'is_admin': player['is_admin'], 
        'admin_level': player['admin_level'],
        'admin_prefix': get_admin_prefix(player['admin_level']) if player['is_admin'] else ''
    })

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    user, pwd = data.get('username'), data.get('password')
    if get_player(user):
        return jsonify({'success': False, 'error': 'Игрок уже существует'})
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO players (username, password) VALUES (?, ?)", (user, pwd))
    cur.execute("INSERT INTO resources (username, wood, stone, iron, dynamite, gold, pickaxe, axe, upgraded_dynamite) VALUES (?, 20, 10, 0, 0, 0, 0, 0, 0)", (user,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_resources', methods=['POST'])
def get_resources():
    data = request.json
    user = data.get('username')
    res = get_resources(user)
    if res:
        return jsonify(dict(res))
    return jsonify({'wood': 0, 'stone': 0, 'iron': 0, 'dynamite': 0, 'gold': 0, 'pickaxe': 0, 'axe': 0, 'upgraded_dynamite': 0})

@app.route('/save_resources', methods=['POST'])
def save_resources():
    data = request.json
    user = data.get('username')
    update_resources(user,
        wood=data.get('wood', 0),
        stone=data.get('stone', 0),
        iron=data.get('iron', 0),
        dynamite=data.get('dynamite', 0),
        gold=data.get('gold', 0),
        pickaxe=data.get('pickaxe', 0),
        axe=data.get('axe', 0),
        upgraded_dynamite=data.get('upgraded_dynamite', 0)
    )
    return jsonify({'success': True})

@app.route('/get_world', methods=['POST'])
def get_world():
    data = request.json
    server_id = data.get('server_id', 1)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT x, y, block_type, owner, house_level FROM world WHERE server_id=?", (server_id,))
    rows = cur.fetchall()
    conn.close()
    world = {}
    for row in rows:
        world[f"{row['x']},{row['y']}"] = {
            'type': row['block_type'], 
            'owner': row['owner'],
            'house_level': row['house_level'] if row['block_type'] == 'house' else 0
        }
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
        house_level = val.get('house_level', 1) if val.get('type') == 'house' else 1
        cur.execute("INSERT INTO world (x, y, block_type, owner, server_id, house_level) VALUES (?, ?, ?, ?, ?, ?)",
                    (x, y, val['type'], val.get('owner'), server_id, house_level))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_house_inventory', methods=['POST'])
def get_house_inventory():
    data = request.json
    owner = data.get('owner')
    items = get_house_inventory(owner)
    return jsonify([dict(item) for item in items])

@app.route('/save_house_inventory', methods=['POST'])
def save_house_inventory():
    data = request.json
    owner = data.get('owner')
    items = data.get('items', [])
    clear_house_inventory(owner)
    for item in items:
        add_house_item(owner, item.get('x', 0), item.get('y', 0), item['item_type'], item.get('amount', 1))
    return jsonify({'success': True})

@app.route('/upgrade_house', methods=['POST'])
def upgrade_house():
    data = request.json
    x, y = data.get('x'), data.get('y')
    owner = data.get('owner')
    current_level = get_house_level(x, y)
    if current_level >= 5:
        return jsonify({'success': False, 'error': 'Дом уже максимального уровня'})
    # Стоимость улучшения
    costs = {
        1: {'wood': 10, 'stone': 5, 'iron': 2},
        2: {'wood': 20, 'stone': 10, 'iron': 5},
        3: {'wood': 40, 'stone': 20, 'iron': 10},
        4: {'wood': 80, 'stone': 40, 'iron': 20}
    }
    cost = costs.get(current_level, {})
    res = get_resources(owner)
    if not res:
        return jsonify({'success': False, 'error': 'Игрок не найден'})
    if res['wood'] < cost.get('wood', 0) or res['stone'] < cost.get('stone', 0) or res['iron'] < cost.get('iron', 0):
        return jsonify({'success': False, 'error': 'Недостаточно ресурсов'})
    # Списываем ресурсы
    update_resources(owner, 
        wood=res['wood'] - cost.get('wood', 0),
        stone=res['stone'] - cost.get('stone', 0),
        iron=res['iron'] - cost.get('iron', 0)
    )
    new_level = current_level + 1
    update_house_level(x, y, new_level)
    return jsonify({'success': True, 'new_level': new_level})

@app.route('/get_chat', methods=['POST'])
def get_chat():
    data = request.json
    server_id = data.get('server_id', 1)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, message, timestamp FROM chat WHERE server_id=? ORDER BY id DESC LIMIT 50", (server_id,))
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
    
    # Проверка на мут
    player = get_player(username)
    if player and player['muted_until']:
        muted_until = datetime.fromisoformat(player['muted_until'])
        if datetime.now() < muted_until:
            return jsonify({'success': False, 'error': f'Вы замьючены до {muted_until}'})
    
    conn = get_db()
    cur = conn.cursor()
    # Если это команда (начинается с /)
    if message.startswith('/'):
        conn.close()
        return jsonify({'success': False, 'error': 'Команда обрабатывается отдельно'})
    
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
    return jsonify([dict(row) for row in rows])

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
                    # Проверяем, есть ли у пользователя префикс
                    player = get_player(row['username'])
                    prefix = ''
                    if player and player['is_admin']:
                        prefix = get_admin_prefix(player['admin_level']) + ' '
                    yield f"data: {json.dumps({'user': prefix + row['username'], 'msg': row['message'], 'time': row['timestamp']})}\n\n"
                time.sleep(0.5)
            except Exception as e:
                print("SSE ошибка:", e)
                time.sleep(1)
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
