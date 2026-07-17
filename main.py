import sys
import subprocess

try:
    import libsql_client
    import flask
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "flask-cors", "libsql-client"])

from flask import Flask, request, jsonify
from flask_cors import CORS
import libsql_client
import os

app = Flask(__name__)
CORS(app)

# ========== ОСНОВНАЯ БАЗА ДАННЫХ YORK ==========
TURSO_URL = "https://york-cursedd.aws-eu-west-1.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJleHAiOjE3ODQ4ODY0NzIsImlhdCI6MTc4NDI4MTY3MiwiaWQiOiIwMTlmNmY3OC1kYTAxLTdmYzAtOGM3OC05ZTA1MjFjN2MwYjIiLCJraWQiOiJxalhsSEtsSUZCYk1fb25EOVpYSTJYVV9rNUFPeHdfckgwX1NxRnoyZTRnIiwicmlkIjoiZGEyZWE4M2ItMzQ1Ni00NjA3LWIyYmItMWY1ZjU1YzQwMWEyIn0.J3VAh7UK1Rld-CUWF8FEsqDPYmXGb16fMn3EqygEdIVHuzYdCPqUwGhOgPxwPunXCNwXiGjE7Oo0Nq4V8fK-DQ"

def get_db():
    return libsql_client.create_client_sync(
        url=TURSO_URL,
        auth_token=TURSO_TOKEN,
        tls=True
    )

# ========== ПОЛУЧИТЬ ВСЕ СЕРВЕРА ==========
@app.route('/get_servers', methods=['GET'])
def get_servers():
    try:
        conn = get_db()
        rows = conn.execute("SELECT id, name, admin, size, wipe_days, tariff, status FROM servers ORDER BY id DESC")
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
        conn.close()
        return jsonify(servers)
    except Exception as e:
        print("Ошибка:", e)
        return jsonify({'error': str(e)}), 500

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
    
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO servers (name, admin, size, wipe_days, tariff, status)
            VALUES (?, ?, ?, ?, ?, 'online')
        """, (name, admin, size, wipe_days, tariff))
        server_id = conn.last_insert_rowid()
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'server_id': server_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== ВКЛЮЧИТЬ/ВЫКЛЮЧИТЬ ==========
@app.route('/toggle_server', methods=['POST'])
def toggle_server():
    data = request.json
    server_id = data.get('server_id')
    admin = data.get('admin')
    
    try:
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
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== УДАЛИТЬ ==========
@app.route('/delete_server', methods=['POST'])
def delete_server():
    data = request.json
    server_id = data.get('server_id')
    admin = data.get('admin')
    
    try:
        conn = get_db()
        conn.execute("DELETE FROM servers WHERE id=? AND admin=?", (server_id, admin))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
