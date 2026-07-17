from flask import Flask, request, jsonify
from flask_cors import CORS
import libsql_client
import os

app = Flask(__name__)
CORS(app)

# ========== НАСТРОЙКИ TURSO ==========
TURSO_URL = "libsql://vk-bot-cursedd.aws-eu-west-1.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODQyOTA1NDAsImlkIjoiMDE5ZjcwMDAtOTcwMS03NDJjLWIwM2EtNzA0MTQ2MDk4ZWI2Iiwia2lkIjoicWpYbEhLbElGQmJNX29uRDlaWEkyWFVfazVBT3h3X3JIMF9TcUZ6MmU0ZyIsInJpZCI6ImM3OTFiYzM5LTg3YjktNDgwZC1iZjRkLTEwMDdiNTI1YTg2NCJ9.rvnr8-mOPA7ydTmVKb1C4QDIxA_se-HSIiGQX5OaJ9vnj89C4xJ5PZnHn5ldw4eQMf-5pRXztvisg-chcKj4Dw"

def get_db():
    return libsql_client.connect(TURSO_URL, auth_token=TURSO_TOKEN)

# ========== ПОЛУЧИТЬ ВСЕ СЕРВЕРА ==========
@app.route('/get_servers', methods=['GET'])
def get_servers():
    conn = get_db()
    rows = conn.execute("SELECT id, name, admin, size, wipe_days, tariff, status FROM servers ORDER BY id DESC").fetchall()
    conn.close()
    servers = []
    for row in rows:
        servers.append({
            'id': row[0],
            'name': row[1],
            'admin': row[2],
            'size': row[3],
            'wipe_days': row[4],
            'tariff': row[5] if len(row) > 5 else 'free',
            'status': row[6] if len(row) > 6 else 'offline'
        })
    return jsonify(servers)

# ========== СОЗДАТЬ СЕРВЕР ==========
@app.route('/create_server', methods=['POST'])
def create_server():
    data = request.json
    name = data.get('name')
    admin = data.get('admin')
    size = data.get('size', 150)
    wipe_days = data.get('wipe_days', 30)
    tariff = data.get('tariff', 'free')
    
    if not name or not admin:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    conn = get_db()
    conn.execute("""
        INSERT INTO servers (name, admin, size, wipe_days, tariff, status)
        VALUES (?, ?, ?, ?, ?, 'online')
    """, (name, admin, size, wipe_days, tariff))
    server_id = conn.last_insert_rowid()
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'server_id': server_id,
        'message': f'Сервер {name} создан!'
    })

# ========== ВКЛЮЧИТЬ/ВЫКЛЮЧИТЬ СЕРВЕР ==========
@app.route('/toggle_server', methods=['POST'])
def toggle_server():
    data = request.json
    server_id = data.get('server_id')
    admin = data.get('admin')
    
    conn = get_db()
    cur = conn.execute("SELECT status FROM servers WHERE id=? AND admin=?", (server_id, admin))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Сервер не найден'})
    
    new_status = 'offline' if row[0] == 'online' else 'online'
    conn.execute("UPDATE servers SET status=? WHERE id=?", (new_status, server_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'status': new_status})

# ========== УДАЛИТЬ СЕРВЕР ==========
@app.route('/delete_server', methods=['POST'])
def delete_server():
    data = request.json
    server_id = data.get('server_id')
    admin = data.get('admin')
    
    conn = get_db()
    conn.execute("DELETE FROM servers WHERE id=? AND admin=?", (server_id, admin))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
