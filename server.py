import os
import json
import uuid
import hashlib
import urllib.request
import urllib.error
import threading
import re
from html.parser import HTMLParser
from datetime import datetime
from flask import Flask, send_from_directory, request, jsonify, session
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
import bcrypt


# ====== HTML 净化（防存储型 XSS） ======

class HTMLSanitizer(HTMLParser):
    """白名单式 HTML 净化器，防止存储型 XSS 攻击"""

    ALLOWED_TAGS = {
        'p', 'br', 'hr', 'blockquote', 'pre', 'code',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li',
        'strong', 'em', 'b', 'i', 'u', 's', 'strike', 'del', 'ins',
        'a', 'img',
        'span', 'div',
        'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'sub', 'sup',
    }

    ALLOWED_ATTRS = {
        'a': {'href', 'target', 'rel', 'title'},
        'img': {'src', 'alt', 'title', 'width', 'height'},
        'span': {'style', 'class'},
        'div': {'style', 'class'},
        'p': {'style', 'class'},
        'td': {'style', 'class'},
        'th': {'style', 'class'},
    }

    ALLOWED_STYLES = {
        'color', 'background-color', 'background',
        'text-align', 'font-weight', 'font-style', 'text-decoration',
        'list-style-type', 'margin', 'padding',
    }

    def __init__(self):
        super().__init__()
        self.result = []
        self.open_tags = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in self.ALLOWED_TAGS:
            return
        clean_attrs = []
        allowed = self.ALLOWED_ATTRS.get(tag, set())
        for name, value in attrs:
            name = name.lower()
            if name not in allowed:
                continue
            if name == 'href' and value:
                # 只允许 http/https/mailto 链接，阻止 javascript: 等
                if re.match(r'^\s*(javascript|data|vbscript):', value, re.IGNORECASE):
                    continue
            if name == 'src' and value:
                if re.match(r'^\s*(javascript|data|vbscript):', value, re.IGNORECASE):
                    continue
            if name == 'style' and value:
                # 过滤危险 CSS 属性
                safe_decls = []
                for decl in value.split(';'):
                    prop = decl.split(':')[0].strip().lower() if ':' in decl else ''
                    if prop in self.ALLOWED_STYLES:
                        safe_decls.append(decl.strip())
                value = '; '.join(safe_decls)
                if not value:
                    continue
            clean_attrs.append(f'{name}="{value}"')
        attr_str = (' ' + ' '.join(clean_attrs)) if clean_attrs else ''
        self.result.append(f'<{tag}{attr_str}>')
        self.open_tags.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag not in self.ALLOWED_TAGS:
            return
        if self.open_tags and self.open_tags[-1] == tag:
            self.result.append(f'</{tag}>')
            self.open_tags.pop()

    def handle_data(self, data):
        self.result.append(data)

    def handle_entityref(self, name):
        self.result.append(f'&{name};')

    def handle_charref(self, name):
        self.result.append(f'&#{name};')

    def get_output(self):
        return ''.join(self.result)


def sanitize_html(html_content):
    """净化 HTML 内容，移除危险的标签和属性"""
    if not html_content:
        return html_content
    sanitizer = HTMLSanitizer()
    sanitizer.feed(html_content)
    return sanitizer.get_output()

# 从脚本所在目录显式加载 .env 文件
script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(script_dir, '.env'))

app = Flask(__name__, static_folder='public', static_url_path='')
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())

# Session Cookie 配置
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24小时

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

DATA_FILE = os.path.join(script_dir, 'data', 'content.json')
PLAYERS_FILE = os.path.join(script_dir, 'data', 'players.json')
NEWS_FILE = os.path.join(script_dir, 'data', 'news.json')
VOTES_FILE = os.path.join(script_dir, 'data', 'votes.json')
REGISTRATIONS_FILE = os.path.join(script_dir, 'data', 'registrations.json')
UPLOADS_FILE = os.path.join(script_dir, 'data', 'uploads.json')
UPLOAD_FOLDER = os.path.join(script_dir, 'public', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'zip', 'json'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'msmp2026')
MC_SERVER_DIR = os.getenv('MC_SERVER_DIR', '')
PLUGIN_API_KEY = os.getenv('PLUGIN_API_KEY', 'msmp-plugin-2026')

# 确保上传目录存在
os.makedirs(os.path.join(UPLOAD_FOLDER, 'news'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'attachments'), exist_ok=True)

# 服务器状态缓存（由插件推送更新）
server_status_cache = {
    'online': False,
    'tps': [20.0, 20.0, 20.0],
    'onlinePlayers': [],
    'maxPlayers': 50,
    'serverVersion': '',
    'lastUpdate': None
}
server_status_lock = threading.Lock()


# ====== 数据读写 ======

def load_content():
    with open(DATA_FILE, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def save_content(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_players():
    if not os.path.exists(PLAYERS_FILE):
        return {"players": [], "nextId": 1}
    with open(PLAYERS_FILE, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def save_players(data):
    os.makedirs(os.path.dirname(PLAYERS_FILE), exist_ok=True)
    with open(PLAYERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def sanitize_player(player):
    """返回玩家数据，移除敏感字段"""
    return {
        'id': player['id'],
        'username': player['username'],
        'mcUsername': player['mcUsername'],
        'mcUUID': player['mcUUID'],
        'mcUUIDType': player['mcUUIDType'],
        'email': player.get('email', ''),
        'whitelisted': player['whitelisted'],
        'banned': player.get('banned', False),
        'registeredAt': player['registeredAt'],
        'lastLoginAt': player.get('lastLoginAt'),
    }


# ====== UUID 生成 ======

def generate_offline_uuid(username):
    """
    模拟 Java 的 UUID.nameUUIDFromBytes("OfflinePlayer:" + username)
    算法：MD5("OfflinePlayer:" + username) → version 3 UUID
    """
    data = f"OfflinePlayer:{username}".encode('utf-8')
    md5_hash = hashlib.md5(data).digest()
    # 设置 version 3 (name-based MD5)
    md5_hash = bytearray(md5_hash)
    md5_hash[6] = (md5_hash[6] & 0x0f) | 0x30  # version = 3
    md5_hash[8] = (md5_hash[8] & 0x3f) | 0x80  # variant = RFC 4122
    u = uuid.UUID(bytes=bytes(md5_hash))
    return str(u)


def fetch_online_uuid(username):
    """
    通过 Mojang API 查询正版玩家 UUID
    返回 UUID 字符串，失败返回 None
    """
    try:
        url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
        req = urllib.request.Request(url, headers={'User-Agent': 'MSMP-Website/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                raw_id = data.get('id', '')
                if raw_id and len(raw_id) == 32:
                    # 格式化为 8-4-4-4-12
                    formatted = f"{raw_id[0:8]}-{raw_id[8:12]}-{raw_id[12:16]}-{raw_id[16:20]}-{raw_id[20:32]}"
                    return formatted
    except Exception:
        pass
    return None


# ====== 白名单管理 ======

def add_to_whitelist(mc_username, mc_uuid):
    """
    将玩家添加到 MC 服务器的 whitelist.json
    如果 MC_SERVER_DIR 未配置，则跳过文件写入
    """
    if not MC_SERVER_DIR:
        return True  # 本地开发模式，不写文件

    whitelist_path = os.path.join(MC_SERVER_DIR, 'whitelist.json')
    try:
        # 读取现有白名单
        if os.path.exists(whitelist_path):
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                whitelist = json.load(f)
        else:
            whitelist = []

        # 检查是否已存在
        for entry in whitelist:
            if entry.get('uuid') == mc_uuid or entry.get('name') == mc_username:
                return True  # 已在白名单

        # 添加新条目
        whitelist.append({
            "uuid": mc_uuid,
            "name": mc_username
        })

        # 写回文件
        with open(whitelist_path, 'w', encoding='utf-8') as f:
            json.dump(whitelist, f, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        print(f"写入白名单失败: {e}")
        return False


# ====== 静态页面路由 ======

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')


@app.route('/admin')
def admin():
    return send_from_directory('public', 'admin.html')


@app.route('/news')
def news_page():
    return send_from_directory('public', 'news.html')


@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('public', path)


# ====== 网站内容 API ======

@app.route('/api/content', methods=['GET'])
def get_content():
    return jsonify(load_content())


# ====== 管理员 API ======

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    if not data or data.get('password') != ADMIN_PASSWORD:
        return jsonify({'error': '密码错误'}), 401
    session['admin'] = True
    session.permanent = True
    return jsonify({'success': True})


@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin', None)
    return jsonify({'success': True})


@app.route('/api/admin/check', methods=['GET'])
def admin_check():
    return jsonify({'authenticated': session.get('admin', False)})


@app.route('/api/admin/content', methods=['POST'])
def update_content():
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401
    new_content = request.get_json()
    if not new_content:
        return jsonify({'error': '无效数据'}), 400
    save_content(new_content)
    socketio.emit('content-update', new_content)
    return jsonify({'success': True})


@app.route('/api/admin/players', methods=['GET'])
def admin_get_players():
    """管理员获取所有玩家列表"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401
    players_data = load_players()
    return jsonify({
        'players': [sanitize_player(p) for p in players_data['players']]
    })


@app.route('/api/admin/players/<int:player_id>', methods=['DELETE'])
def admin_delete_player(player_id):
    """管理员删除玩家"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401
    players_data = load_players()
    players_data['players'] = [p for p in players_data['players'] if p['id'] != player_id]
    save_players(players_data)
    return jsonify({'success': True})


@app.route('/api/admin/players/<int:player_id>/whitelist', methods=['POST'])
def admin_toggle_whitelist(player_id):
    """管理员切换玩家白名单状态"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == player_id), None)
    if not player:
        return jsonify({'error': '玩家不存在'}), 404
    player['whitelisted'] = not player['whitelisted']
    if player['whitelisted']:
        add_to_whitelist(player['mcUsername'], player['mcUUID'])
    save_players(players_data)
    return jsonify({'success': True, 'whitelisted': player['whitelisted']})


@app.route('/api/admin/players/<int:player_id>/ban', methods=['POST'])
def admin_toggle_ban(player_id):
    """管理员封禁/解封玩家"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == player_id), None)
    if not player:
        return jsonify({'error': '玩家不存在'}), 404
    player['banned'] = not player.get('banned', False)
    save_players(players_data)
    return jsonify({'success': True, 'banned': player['banned']})


# ====== 玩家 API ======

@app.route('/api/player/register', methods=['POST'])
def player_register():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    mc_username = (data.get('mcUsername') or '').strip()
    mc_uuid_type = data.get('mcUUIDType', 'offline')
    email = (data.get('email') or '').strip()

    # 验证必填字段
    if not username or not password or not mc_username:
        return jsonify({'error': '必填字段不能为空'}), 400
    if len(username) < 3 or len(username) > 20:
        return jsonify({'error': '用户名长度需在3-20之间'}), 400
    if len(password) < 6:
        return jsonify({'error': '密码长度不能少于6位'}), 400
    if mc_uuid_type not in ('offline', 'online'):
        mc_uuid_type = 'offline'

    # 检查用户名唯一性
    players_data = load_players()
    if any(p['username'] == username for p in players_data['players']):
        return jsonify({'error': '用户名已被注册'}), 409
    if any(p['mcUsername'] == mc_username for p in players_data['players']):
        return jsonify({'error': '该 Minecraft 用户名已被注册'}), 409

    # 获取 UUID
    mc_uuid = ''
    if mc_uuid_type == 'online':
        mc_uuid = fetch_online_uuid(mc_username)
        if not mc_uuid:
            return jsonify({'error': '无法获取正版 UUID，请确认用户名是否正确'}), 400
    else:
        mc_uuid = generate_offline_uuid(mc_username)

    # 创建玩家
    player = {
        'id': players_data['nextId'],
        'username': username,
        'passwordHash': bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'),
        'mcUsername': mc_username,
        'mcUUID': mc_uuid,
        'mcUUIDType': mc_uuid_type,
        'email': email,
        'whitelisted': True,
        'registeredAt': datetime.now().isoformat(),
        'lastLoginAt': None,
    }
    players_data['players'].append(player)
    players_data['nextId'] += 1
    save_players(players_data)

    # 加入白名单
    add_to_whitelist(mc_username, mc_uuid)

    # 自动登录
    session['player_id'] = player['id']

    return jsonify({'success': True, 'player': sanitize_player(player)})


@app.route('/api/player/login', methods=['POST'])
def player_login():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400

    players_data = load_players()
    player = next((p for p in players_data['players'] if p['username'] == username), None)
    if not player or not bcrypt.checkpw(password.encode('utf-8'), player['passwordHash'].encode('utf-8')):
        return jsonify({'error': '用户名或密码错误'}), 401

    if player.get('banned', False):
        return jsonify({'error': '该账号已被封禁'}), 403

    session['player_id'] = player['id']
    player['lastLoginAt'] = datetime.now().isoformat()
    save_players(players_data)

    return jsonify({'success': True, 'player': sanitize_player(player)})


@app.route('/api/player/logout', methods=['POST'])
def player_logout():
    session.pop('player_id', None)
    return jsonify({'success': True})


@app.route('/api/player/check', methods=['GET'])
def player_check():
    player_id = session.get('player_id')
    if not player_id:
        return jsonify({'authenticated': False})
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == player_id), None)
    if not player:
        session.pop('player_id', None)
        return jsonify({'authenticated': False})
    return jsonify({'authenticated': True, 'player': sanitize_player(player)})


@app.route('/api/player/profile', methods=['GET'])
def player_profile():
    player_id = session.get('player_id')
    if not player_id:
        return jsonify({'error': '未登录'}), 401
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == player_id), None)
    if not player:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify(sanitize_player(player))


# ====== 插件 API（供 MC 服务器插件调用） ======

def check_plugin_api_key(api_key):
    """验证插件的 API Key"""
    return api_key == PLUGIN_API_KEY


@app.route('/api/plugin/ping', methods=['GET'])
def plugin_ping():
    """插件连接测试"""
    api_key = request.args.get('apiKey', '')
    if not check_plugin_api_key(api_key):
        return jsonify({'error': '无效的 API Key'}), 403
    return jsonify({'status': 'ok', 'message': 'MSMP Bridge API is online'})


@app.route('/api/plugin/heartbeat', methods=['POST'])
def plugin_heartbeat():
    """接收插件推送的服务器状态"""
    data = request.get_json()
    if not data or not check_plugin_api_key(data.get('apiKey', '')):
        return jsonify({'error': '无效的 API Key'}), 403

    with server_status_lock:
        server_status_cache['online'] = data.get('online', True)
        server_status_cache['tps'] = data.get('tps', [20.0, 20.0, 20.0])
        server_status_cache['onlinePlayers'] = data.get('onlinePlayers', [])
        server_status_cache['maxPlayers'] = data.get('maxPlayers', 50)
        server_status_cache['serverVersion'] = data.get('serverVersion', '')
        server_status_cache['lastUpdate'] = datetime.now().isoformat()

    # 通过 SocketIO 推送实时状态更新到前端
    socketio.emit('server-status-update', {
        'online': server_status_cache['online'],
        'tps': server_status_cache['tps'],
        'onlinePlayers': server_status_cache['onlinePlayers'],
        'maxPlayers': server_status_cache['maxPlayers'],
        'serverVersion': server_status_cache['serverVersion'],
    })

    return jsonify({'success': True})


@app.route('/api/plugin/pending-whitelist', methods=['GET'])
def plugin_pending_whitelist():
    """返回已注册但未在游戏内确认白名单的玩家列表"""
    api_key = request.args.get('apiKey', '')
    if not check_plugin_api_key(api_key):
        return jsonify({'error': '无效的 API Key'}), 403

    players_data = load_players()
    # 返回所有 whitelisted=True 但 whitelistSynced=False 或无此字段的玩家
    pending = []
    for p in players_data['players']:
        if p.get('whitelisted', False) and not p.get('whitelistSynced', False):
            pending.append({
                'mcUsername': p['mcUsername'],
                'mcUUID': p['mcUUID'],
                'mcUUIDType': p['mcUUIDType'],
            })

    return jsonify({'players': pending})


@app.route('/api/plugin/whitelist-confirmed', methods=['POST'])
def plugin_whitelist_confirmed():
    """插件确认已将玩家添加到游戏内白名单"""
    data = request.get_json()
    if not data or not check_plugin_api_key(data.get('apiKey', '')):
        return jsonify({'error': '无效的 API Key'}), 403

    mc_username = data.get('mcUsername', '')
    if not mc_username:
        return jsonify({'error': '缺少 mcUsername'}), 400

    players_data = load_players()
    updated = False
    for p in players_data['players']:
        if p['mcUsername'] == mc_username:
            p['whitelistSynced'] = True
            updated = True
            break

    if updated:
        save_players(players_data)

    return jsonify({'success': True, 'updated': updated})


@app.route('/api/plugin/player-event', methods=['POST'])
def plugin_player_event():
    """接收插件推送的玩家事件（加入/离开/踢出）"""
    data = request.get_json()
    if not data or not check_plugin_api_key(data.get('apiKey', '')):
        return jsonify({'error': '无效的 API Key'}), 403

    event_type = data.get('event', '')
    player_name = data.get('playerName', '')
    player_uuid = data.get('playerUUID', '')

    if event_type not in ('join', 'leave', 'kick'):
        return jsonify({'error': '无效的事件类型'}), 400

    # 通过 SocketIO 推送玩家事件到前端
    socketio.emit('player-event', {
        'event': event_type,
        'playerName': player_name,
        'playerUUID': player_uuid,
        'timestamp': datetime.now().isoformat(),
    })

    return jsonify({'success': True})


# ====== 服务器状态 API（前端调用） ======

@app.route('/api/server-status', methods=['GET'])
def get_server_status():
    """获取实时服务器状态（供前端展示）"""
    with server_status_lock:
        return jsonify({
            'online': server_status_cache['online'],
            'tps': server_status_cache['tps'],
            'onlinePlayers': server_status_cache['onlinePlayers'],
            'maxPlayers': server_status_cache['maxPlayers'],
            'serverVersion': server_status_cache['serverVersion'],
            'lastUpdate': server_status_cache['lastUpdate'],
        })


# ====== 新闻数据读写 ======

def load_news():
    if not os.path.exists(NEWS_FILE):
        return {"news": [], "nextNewsId": 1, "categories": [
            {"id": "update", "name": "更新", "color": "green"},
            {"id": "event", "name": "活动", "color": "gold"},
            {"id": "notice", "name": "通知", "color": "purple"},
            {"id": "urgent", "name": "紧急", "color": "red"}
        ]}
    with open(NEWS_FILE, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def save_news(data):
    os.makedirs(os.path.dirname(NEWS_FILE), exist_ok=True)
    with open(NEWS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_votes():
    if not os.path.exists(VOTES_FILE):
        return {"votes": [], "nextVoteId": 1}
    with open(VOTES_FILE, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def save_votes(data):
    os.makedirs(os.path.dirname(VOTES_FILE), exist_ok=True)
    with open(VOTES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_registrations():
    if not os.path.exists(REGISTRATIONS_FILE):
        return {"registrations": [], "nextRegistrationId": 1}
    with open(REGISTRATIONS_FILE, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def save_registrations(data):
    os.makedirs(os.path.dirname(REGISTRATIONS_FILE), exist_ok=True)
    with open(REGISTRATIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_uploads():
    if not os.path.exists(UPLOADS_FILE):
        return {"uploads": []}
    with open(UPLOADS_FILE, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def save_uploads(data):
    os.makedirs(os.path.dirname(UPLOADS_FILE), exist_ok=True)
    with open(UPLOADS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_category_label(category_id):
    labels = {'update': '更新', 'event': '活动', 'notice': '通知', 'urgent': '紧急'}
    return labels.get(category_id, '通知')


def sync_news_to_announcements(news_item):
    """将新闻同步到首页公告列表"""
    content = load_content()

    # 查找是否已有对应公告
    existing_idx = None
    for i, a in enumerate(content['announcements']):
        if a.get('newsId') == news_item['id']:
            existing_idx = i
            break

    announcement = {
        "id": news_item['id'],
        "newsId": news_item['id'],
        "title": news_item['title'],
        "desc": news_item.get('summary', '') or news_item.get('content', '')[:100] + '...',
        "date": (news_item.get('publishedAt') or news_item.get('createdAt', ''))[:10],
        "tag": news_item.get('category', 'notice'),
        "tagLabel": get_category_label(news_item.get('category', 'notice')),
        "pinned": news_item.get('pinned', False)
    }

    if existing_idx is not None:
        content['announcements'][existing_idx] = announcement
    else:
        content['announcements'].insert(0, announcement)

    # 置顶排前面，然后按日期降序
    content['announcements'].sort(
        key=lambda x: (not x.get('pinned', False), x.get('date', '')),
        reverse=True
    )

    save_content(content)
    socketio.emit('content-update', content)


def remove_news_from_announcements(news_id):
    """从首页公告列表移除新闻"""
    content = load_content()
    content['announcements'] = [a for a in content['announcements'] if a.get('newsId') != news_id]
    save_content(content)
    socketio.emit('content-update', content)


# ====== 公共新闻 API ======

@app.route('/api/news', methods=['GET'])
def get_news_list():
    """获取已发布新闻列表"""
    news_data = load_news()
    published = [n for n in news_data['news'] if n.get('status') == 'published']
    published.sort(key=lambda x: (not x.get('pinned', False), x.get('publishedAt', '')), reverse=True)

    result = []
    for n in published:
        result.append({
            'id': n['id'],
            'title': n['title'],
            'summary': n.get('summary', ''),
            'coverImage': n.get('coverImage'),
            'category': n.get('category', 'notice'),
            'tags': n.get('tags', []),
            'pinned': n.get('pinned', False),
            'publishedAt': n.get('publishedAt'),
            'author': n.get('author', 'Admin'),
            'viewCount': n.get('viewCount', 0)
        })

    return jsonify({'news': result, 'categories': news_data.get('categories', [])})


@app.route('/api/news/<int:news_id>', methods=['GET'])
def get_news_detail(news_id):
    """获取新闻详情（含投票/报名信息）"""
    news_data = load_news()
    news_item = next((n for n in news_data['news'] if n['id'] == news_id), None)

    if not news_item or news_item.get('status') != 'published':
        return jsonify({'error': '新闻不存在'}), 404

    # 浏览量 +1
    news_item['viewCount'] = news_item.get('viewCount', 0) + 1
    save_news(news_data)

    # 获取关联投票
    vote = None
    if news_item.get('voteId'):
        votes_data = load_votes()
        v = next((v for v in votes_data['votes'] if v['id'] == news_item['voteId']), None)
        if v:
            vote = {
                'id': v['id'],
                'title': v['title'],
                'description': v.get('description', ''),
                'type': v.get('type', 'single'),
                'options': [{'id': opt['id'], 'text': opt['text']} for opt in v['options']],
                'allowMultiple': v.get('allowMultiple', False),
                'maxChoices': v.get('maxChoices', 1),
                'endAt': v.get('endAt'),
                'status': v.get('status', 'active'),
                'totalVotes': v.get('totalVotes', 0)
            }
            player_id = session.get('player_id')
            if player_id:
                vote['hasVoted'] = player_id in v.get('voterIds', [])
                if vote['hasVoted']:
                    vote['results'] = [{'id': opt['id'], 'text': opt['text'], 'votes': opt['votes']} for opt in v['options']]

    # 获取关联报名
    registration = None
    if news_item.get('registrationId'):
        reg_data = load_registrations()
        r = next((r for r in reg_data['registrations'] if r['id'] == news_item['registrationId']), None)
        if r:
            registration = {
                'id': r['id'],
                'title': r['title'],
                'description': r.get('description', ''),
                'maxParticipants': r.get('maxParticipants'),
                'currentParticipants': len(r.get('participants', [])),
                'endAt': r.get('endAt'),
                'status': r.get('status', 'open'),
                'fields': r.get('fields', []),
                'requireWhitelist': r.get('requireWhitelist', True)
            }
            player_id = session.get('player_id')
            if player_id:
                reg = next((p for p in r.get('participants', []) if p['playerId'] == player_id), None)
                registration['hasRegistered'] = reg is not None
                if reg:
                    registration['registeredAt'] = reg['registeredAt']
                    registration['data'] = reg.get('data', {})

    return jsonify({
        'id': news_item['id'],
        'title': news_item['title'],
        'content': news_item['content'],
        'coverImage': news_item.get('coverImage'),
        'author': news_item.get('author', 'Admin'),
        'publishedAt': news_item.get('publishedAt'),
        'category': news_item.get('category', 'notice'),
        'tags': news_item.get('tags', []),
        'attachments': news_item.get('attachments', []),
        'viewCount': news_item['viewCount'],
        'vote': vote,
        'registration': registration
    })


@app.route('/api/news/categories', methods=['GET'])
def get_news_categories():
    """获取新闻分类"""
    news_data = load_news()
    return jsonify({'categories': news_data.get('categories', [])})


# ====== 管理员新闻 API ======

@app.route('/api/admin/news', methods=['GET'])
def admin_get_news():
    """管理员：获取所有新闻（含草稿）"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401
    news_data = load_news()
    return jsonify({'news': news_data['news'], 'categories': news_data.get('categories', [])})


@app.route('/api/admin/news', methods=['POST'])
def admin_create_news():
    """管理员：创建新闻"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    data = request.get_json()
    if not data or not data.get('title'):
        return jsonify({'error': '标题不能为空'}), 400

    news_data = load_news()
    news_item = {
        'id': news_data['nextNewsId'],
        'title': data['title'],
        'content': sanitize_html(data.get('content', '')),
        'summary': data.get('summary', ''),
        'author': 'Admin',
        'createdAt': datetime.now().isoformat(),
        'updatedAt': datetime.now().isoformat(),
        'publishedAt': datetime.now().isoformat() if data.get('status') == 'published' else None,
        'status': data.get('status', 'draft'),
        'pinned': data.get('pinned', False),
        'category': data.get('category', 'notice'),
        'tags': data.get('tags', []),
        'coverImage': data.get('coverImage'),
        'attachments': data.get('attachments', []),
        'syncToAnnouncements': data.get('syncToAnnouncements', True),
        'viewCount': 0,
        'voteId': None,
        'registrationId': None
    }

    news_data['news'].append(news_item)
    news_data['nextNewsId'] += 1
    save_news(news_data)

    # 同步到首页公告
    if news_item['status'] == 'published' and news_item['syncToAnnouncements']:
        sync_news_to_announcements(news_item)

    return jsonify({'success': True, 'news': news_item})


@app.route('/api/admin/news/<int:news_id>', methods=['PUT'])
def admin_update_news(news_id):
    """管理员：更新新闻"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    data = request.get_json()
    news_data = load_news()
    news_item = next((n for n in news_data['news'] if n['id'] == news_id), None)
    if not news_item:
        return jsonify({'error': '新闻不存在'}), 404

    # 更新字段
    for field in ['title', 'summary', 'status', 'pinned', 'category',
                   'tags', 'coverImage', 'attachments', 'syncToAnnouncements']:
        if field in data:
            news_item[field] = data[field]

    # content 字段单独处理，需要净化
    if 'content' in data:
        news_item['content'] = sanitize_html(data['content'])

    news_item['updatedAt'] = datetime.now().isoformat()

    # 首次发布设置 publishedAt
    if news_item['status'] == 'published' and not news_item.get('publishedAt'):
        news_item['publishedAt'] = datetime.now().isoformat()

    save_news(news_data)

    # 处理公告同步
    if news_item['syncToAnnouncements'] and news_item['status'] == 'published':
        sync_news_to_announcements(news_item)
    else:
        remove_news_from_announcements(news_id)

    return jsonify({'success': True, 'news': news_item})


@app.route('/api/admin/news/<int:news_id>', methods=['DELETE'])
def admin_delete_news(news_id):
    """管理员：删除新闻"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    news_data = load_news()
    news_item = next((n for n in news_data['news'] if n['id'] == news_id), None)
    if not news_item:
        return jsonify({'error': '新闻不存在'}), 404

    # 移除公告
    remove_news_from_announcements(news_id)

    # 删除关联上传文件
    uploads_data = load_uploads()
    for upload in uploads_data['uploads']:
        if upload.get('newsId') == news_id:
            try:
                file_path = os.path.join(script_dir, 'public', upload['path'].lstrip('/'))
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
    uploads_data['uploads'] = [u for u in uploads_data['uploads'] if u.get('newsId') != news_id]
    save_uploads(uploads_data)

    # 删除关联投票
    if news_item.get('voteId'):
        votes_data = load_votes()
        votes_data['votes'] = [v for v in votes_data['votes'] if v['id'] != news_item['voteId']]
        save_votes(votes_data)

    # 删除关联报名
    if news_item.get('registrationId'):
        reg_data = load_registrations()
        reg_data['registrations'] = [r for r in reg_data['registrations'] if r['id'] != news_item['registrationId']]
        save_registrations(reg_data)

    # 删除新闻
    news_data['news'] = [n for n in news_data['news'] if n['id'] != news_id]
    save_news(news_data)

    return jsonify({'success': True})


@app.route('/api/admin/news/<int:news_id>/pin', methods=['POST'])
def admin_toggle_pin(news_id):
    """管理员：切换置顶状态"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    data = request.get_json() or {}
    news_data = load_news()
    news_item = next((n for n in news_data['news'] if n['id'] == news_id), None)
    if not news_item:
        return jsonify({'error': '新闻不存在'}), 404

    news_item['pinned'] = data.get('pinned', not news_item.get('pinned', False))
    news_item['updatedAt'] = datetime.now().isoformat()
    save_news(news_data)

    # 重新同步公告
    if news_item['status'] == 'published' and news_item['syncToAnnouncements']:
        sync_news_to_announcements(news_item)

    return jsonify({'success': True, 'pinned': news_item['pinned']})


# ====== 文件上传 API ======

@app.route('/api/admin/upload', methods=['POST'])
def admin_upload_file():
    """管理员：上传文件"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400

    file = request.files['file']
    upload_type = request.form.get('type', 'attachment')
    news_id = request.form.get('newsId')

    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': '不支持的文件类型'}), 400

    # 检查文件大小
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size > MAX_FILE_SIZE:
        return jsonify({'error': f'文件大小超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)'}), 400

    # 生成安全文件名
    ext = file.filename.rsplit('.', 1)[1].lower()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_filename = f"{upload_type}_{timestamp}_{uuid.uuid4().hex[:8]}.{ext}"

    subfolder = 'news' if upload_type == 'image' else 'attachments'
    upload_path = os.path.join(UPLOAD_FOLDER, subfolder, safe_filename)

    try:
        file.save(upload_path)
    except Exception as e:
        return jsonify({'error': f'保存文件失败: {str(e)}'}), 500

    # 记录上传
    uploads_data = load_uploads()
    upload_record = {
        'id': f"upload_{uuid.uuid4().hex[:12]}",
        'filename': safe_filename,
        'originalName': file.filename,
        'mimeType': file.content_type or 'application/octet-stream',
        'size': file_size,
        'path': f"/uploads/{subfolder}/{safe_filename}",
        'uploadedBy': 'admin',
        'uploadedAt': datetime.now().isoformat(),
        'newsId': int(news_id) if news_id else None,
        'type': upload_type
    }
    uploads_data['uploads'].append(upload_record)
    save_uploads(uploads_data)

    return jsonify({
        'success': True,
        'file': {
            'id': upload_record['id'],
            'filename': safe_filename,
            'originalName': file.filename,
            'url': upload_record['path'],
            'size': file_size,
            'mimeType': upload_record['mimeType']
        }
    })


@app.route('/api/admin/upload/<upload_id>', methods=['DELETE'])
def admin_delete_upload(upload_id):
    """管理员：删除上传文件"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    uploads_data = load_uploads()
    upload = next((u for u in uploads_data['uploads'] if u['id'] == upload_id), None)
    if not upload:
        return jsonify({'error': '文件不存在'}), 404

    # 删除物理文件
    try:
        file_path = os.path.join(script_dir, 'public', upload['path'].lstrip('/'))
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"删除文件失败: {e}")

    uploads_data['uploads'] = [u for u in uploads_data['uploads'] if u['id'] != upload_id]
    save_uploads(uploads_data)

    return jsonify({'success': True})


# ====== 附件下载 API ======

@app.route('/api/download/<path:filepath>', methods=['GET'])
def download_file(filepath):
    """安全下载附件，设置 Content-Disposition 头"""
    full_path = os.path.join(script_dir, 'public', filepath)
    if not os.path.exists(full_path):
        return jsonify({'error': '文件不存在'}), 404

    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)

    # 查找原始文件名
    original_name = filename
    uploads_data = load_uploads()
    for u in uploads_data['uploads']:
        if u['filename'] == filename:
            original_name = u.get('originalName', filename)
            break

    return send_from_directory(
        directory, filename,
        as_attachment=True,
        download_name=original_name
    )


# ====== 投票 API ======

@app.route('/api/admin/news/<int:news_id>/vote', methods=['POST'])
def admin_create_vote(news_id):
    """管理员：为新闻创建投票"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    data = request.get_json()
    if not data or not data.get('title') or not data.get('options'):
        return jsonify({'error': '标题和选项不能为空'}), 400

    news_data = load_news()
    news_item = next((n for n in news_data['news'] if n['id'] == news_id), None)
    if not news_item:
        return jsonify({'error': '新闻不存在'}), 404

    if news_item.get('voteId'):
        return jsonify({'error': '该新闻已有投票'}), 400

    votes_data = load_votes()
    vote = {
        'id': votes_data['nextVoteId'],
        'newsId': news_id,
        'title': data['title'],
        'description': data.get('description', ''),
        'type': data.get('type', 'single'),
        'options': [{'id': f"opt_{i}", 'text': opt, 'votes': 0} for i, opt in enumerate(data['options'])],
        'allowMultiple': data.get('allowMultiple', False),
        'maxChoices': data.get('maxChoices', len(data['options']) if data.get('allowMultiple', False) else 1),
        'startAt': data.get('startAt', datetime.now().isoformat()),
        'endAt': data.get('endAt'),
        'status': 'active',
        'totalVotes': 0,
        'voterIds': []
    }

    votes_data['votes'].append(vote)
    votes_data['nextVoteId'] += 1
    save_votes(votes_data)

    # 关联到新闻
    news_item['voteId'] = vote['id']
    news_item['updatedAt'] = datetime.now().isoformat()
    save_news(news_data)

    return jsonify({'success': True, 'vote': vote})


@app.route('/api/admin/votes/<int:vote_id>', methods=['DELETE'])
def admin_delete_vote(vote_id):
    """管理员：删除投票"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    votes_data = load_votes()
    vote = next((v for v in votes_data['votes'] if v['id'] == vote_id), None)
    if not vote:
        return jsonify({'error': '投票不存在'}), 404

    # 解除新闻关联
    news_data = load_news()
    news_item = next((n for n in news_data['news'] if n.get('voteId') == vote_id), None)
    if news_item:
        news_item['voteId'] = None
        save_news(news_data)

    votes_data['votes'] = [v for v in votes_data['votes'] if v['id'] != vote_id]
    save_votes(votes_data)

    return jsonify({'success': True})


@app.route('/api/admin/votes/<int:vote_id>/results', methods=['GET'])
def admin_get_vote_results(vote_id):
    """管理员：获取投票结果详情"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    votes_data = load_votes()
    vote = next((v for v in votes_data['votes'] if v['id'] == vote_id), None)
    if not vote:
        return jsonify({'error': '投票不存在'}), 404

    return jsonify({
        'id': vote['id'],
        'title': vote['title'],
        'description': vote.get('description', ''),
        'type': vote.get('type', 'single'),
        'allowMultiple': vote.get('allowMultiple', False),
        'status': vote.get('status', 'active'),
        'totalVotes': vote.get('totalVotes', 0),
        'options': [{'id': opt['id'], 'text': opt['text'], 'votes': opt['votes']} for opt in vote['options']],
        'voterCount': len(vote.get('voterIds', []))
    })


@app.route('/api/votes/<int:vote_id>/vote', methods=['POST'])
def submit_vote(vote_id):
    """玩家：提交投票"""
    player_id = session.get('player_id')
    if not player_id:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    if not data or 'optionIds' not in data:
        return jsonify({'error': '请选择选项'}), 400

    votes_data = load_votes()
    vote = next((v for v in votes_data['votes'] if v['id'] == vote_id), None)
    if not vote:
        return jsonify({'error': '投票不存在'}), 404

    if vote.get('status') != 'active':
        return jsonify({'error': '投票已结束'}), 400

    if vote.get('endAt') and datetime.now().isoformat() > vote['endAt']:
        return jsonify({'error': '投票已过期'}), 400

    # 检查是否已投票
    if player_id in vote.get('voterIds', []):
        return jsonify({'error': '您已经投过票了'}), 409

    option_ids = data['optionIds'] if isinstance(data['optionIds'], list) else [data['optionIds']]

    # 验证选项有效性
    valid_ids = {opt['id'] for opt in vote['options']}
    if not all(oid in valid_ids for oid in option_ids):
        return jsonify({'error': '无效的选项'}), 400

    max_choices = vote.get('maxChoices', len(vote['options']) if vote.get('allowMultiple', False) else 1)
    if len(option_ids) > max_choices:
        return jsonify({'error': f'最多选择 {max_choices} 项'}), 400

    # 记录投票
    for opt in vote['options']:
        if opt['id'] in option_ids:
            opt['votes'] = opt.get('votes', 0) + 1

    vote['totalVotes'] = vote.get('totalVotes', 0) + len(option_ids)
    vote['voterIds'].append(player_id)
    # 记录每个投票人的选择
    if 'voters' not in vote:
        vote['voters'] = {}
    vote['voters'][str(player_id)] = option_ids
    save_votes(votes_data)

    return jsonify({
        'success': True,
        'results': [{'id': opt['id'], 'text': opt['text'], 'votes': opt['votes']} for opt in vote['options']]
    })


# ====== 报名 API ======

@app.route('/api/admin/news/<int:news_id>/registration', methods=['POST'])
def admin_create_registration(news_id):
    """管理员：为新闻创建报名"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    data = request.get_json()
    if not data or not data.get('title'):
        return jsonify({'error': '标题不能为空'}), 400

    news_data = load_news()
    news_item = next((n for n in news_data['news'] if n['id'] == news_id), None)
    if not news_item:
        return jsonify({'error': '新闻不存在'}), 404

    if news_item.get('registrationId'):
        return jsonify({'error': '该新闻已有报名'}), 400

    reg_data = load_registrations()
    registration = {
        'id': reg_data['nextRegistrationId'],
        'newsId': news_id,
        'title': data['title'],
        'description': data.get('description', ''),
        'maxParticipants': data.get('maxParticipants'),
        'startAt': data.get('startAt', datetime.now().isoformat()),
        'endAt': data.get('endAt'),
        'status': 'open',
        'requireWhitelist': data.get('requireWhitelist', True),
        'fields': data.get('fields', []),
        'participants': []
    }

    reg_data['registrations'].append(registration)
    reg_data['nextRegistrationId'] += 1
    save_registrations(reg_data)

    # 关联到新闻
    news_item['registrationId'] = registration['id']
    news_item['updatedAt'] = datetime.now().isoformat()
    save_news(news_data)

    return jsonify({'success': True, 'registration': registration})


@app.route('/api/admin/registrations/<int:reg_id>', methods=['DELETE'])
def admin_delete_registration(reg_id):
    """管理员：删除报名"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    reg_data = load_registrations()
    reg = next((r for r in reg_data['registrations'] if r['id'] == reg_id), None)
    if not reg:
        return jsonify({'error': '报名不存在'}), 404

    # 解除新闻关联
    news_data = load_news()
    news_item = next((n for n in news_data['news'] if n.get('registrationId') == reg_id), None)
    if news_item:
        news_item['registrationId'] = None
        save_news(news_data)

    reg_data['registrations'] = [r for r in reg_data['registrations'] if r['id'] != reg_id]
    save_registrations(reg_data)

    return jsonify({'success': True})


@app.route('/api/admin/registrations/<int:reg_id>/participants', methods=['GET'])
def admin_get_participants(reg_id):
    """管理员：获取报名参与者"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    reg_data = load_registrations()
    reg = next((r for r in reg_data['registrations'] if r['id'] == reg_id), None)
    if not reg:
        return jsonify({'error': '报名不存在'}), 404

    return jsonify({
        'participants': reg.get('participants', []),
        'total': len(reg.get('participants', []))
    })


@app.route('/api/admin/news/<int:news_id>/stats', methods=['GET'])
def admin_get_news_stats(news_id):
    """管理员：获取新闻的投票结果和报名参与者列表"""
    if not session.get('admin'):
        return jsonify({'error': '未登录'}), 401

    news_data = load_news()
    news_item = next((n for n in news_data['news'] if n['id'] == news_id), None)
    if not news_item:
        return jsonify({'error': '新闻不存在'}), 404

    result = {'vote': None, 'registration': None}

    # 获取投票详情
    if news_item.get('voteId'):
        votes_data = load_votes()
        vote = next((v for v in votes_data['votes'] if v['id'] == news_item['voteId']), None)
        if vote:
            # 构建投票人详情
            voter_details = []
            voters_map = vote.get('voters', {})
            if voters_map:
                players_data = load_players()
                player_map = {p['id']: p['username'] for p in players_data['players']}
                opt_text_map = {opt['id']: opt['text'] for opt in vote['options']}
                for voter_id, chosen_opts in voters_map.items():
                    voter_details.append({
                        'playerId': int(voter_id),
                        'username': player_map.get(int(voter_id), f'玩家#{voter_id}'),
                        'selectedOptions': [opt_text_map.get(oid, oid) for oid in chosen_opts]
                    })

            result['vote'] = {
                'id': vote['id'],
                'title': vote['title'],
                'description': vote.get('description', ''),
                'type': vote.get('type', 'single'),
                'allowMultiple': vote.get('allowMultiple', False),
                'status': vote.get('status', 'active'),
                'totalVotes': vote.get('totalVotes', 0),
                'voterCount': len(vote.get('voterIds', [])),
                'options': [{'id': opt['id'], 'text': opt['text'], 'votes': opt['votes']} for opt in vote['options']],
                'voterDetails': voter_details
            }

    # 获取报名详情
    if news_item.get('registrationId'):
        reg_data = load_registrations()
        reg = next((r for r in reg_data['registrations'] if r['id'] == news_item['registrationId']), None)
        if reg:
            result['registration'] = {
                'id': reg['id'],
                'title': reg['title'],
                'description': reg.get('description', ''),
                'maxParticipants': reg.get('maxParticipants'),
                'status': reg.get('status', 'open'),
                'requireWhitelist': reg.get('requireWhitelist', True),
                'fields': reg.get('fields', []),
                'participants': reg.get('participants', []),
                'totalParticipants': len(reg.get('participants', []))
            }

    return jsonify(result)


@app.route('/api/registrations/<int:reg_id>/register', methods=['POST'])
def submit_registration(reg_id):
    """玩家：提交报名"""
    player_id = session.get('player_id')
    if not player_id:
        return jsonify({'error': '请先登录'}), 401

    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == player_id), None)
    if not player:
        return jsonify({'error': '玩家不存在'}), 404

    data = request.get_json() or {}

    reg_data = load_registrations()
    reg = next((r for r in reg_data['registrations'] if r['id'] == reg_id), None)
    if not reg:
        return jsonify({'error': '报名不存在'}), 404

    if reg.get('status') != 'open':
        return jsonify({'error': '报名已关闭'}), 400

    if reg.get('endAt') and datetime.now().isoformat() > reg['endAt']:
        return jsonify({'error': '报名已截止'}), 400

    # 白名单检查
    if reg.get('requireWhitelist', True) and not player.get('whitelisted'):
        return jsonify({'error': '需要白名单才能报名'}), 403

    # 检查是否已报名
    if any(p['playerId'] == player_id for p in reg.get('participants', [])):
        return jsonify({'error': '您已经报名了'}), 409

    # 名额检查
    if reg.get('maxParticipants') and len(reg.get('participants', [])) >= reg['maxParticipants']:
        return jsonify({'error': '报名人数已满'}), 400

    # 验证必填字段
    for field in reg.get('fields', []):
        if field.get('required') and not data.get(field['name']):
            return jsonify({'error': f"请填写 {field['label']}"}), 400

    # 添加参与者
    participant = {
        'playerId': player_id,
        'username': player['username'],
        'mcUsername': player['mcUsername'],
        'registeredAt': datetime.now().isoformat(),
        'data': {f['name']: data.get(f['name'], '') for f in reg.get('fields', [])}
    }

    reg['participants'].append(participant)
    save_registrations(reg_data)

    return jsonify({'success': True, 'registeredAt': participant['registeredAt']})


@app.route('/api/registrations/<int:reg_id>/cancel', methods=['POST'])
def cancel_registration(reg_id):
    """玩家：取消报名"""
    player_id = session.get('player_id')
    if not player_id:
        return jsonify({'error': '请先登录'}), 401

    reg_data = load_registrations()
    reg = next((r for r in reg_data['registrations'] if r['id'] == reg_id), None)
    if not reg:
        return jsonify({'error': '报名不存在'}), 404

    original_len = len(reg.get('participants', []))
    reg['participants'] = [p for p in reg.get('participants', []) if p['playerId'] != player_id]
    if len(reg['participants']) == original_len:
        return jsonify({'error': '您未报名此活动'}), 400

    save_registrations(reg_data)
    return jsonify({'success': True})


# ====== WebSocket 事件 ======

@socketio.on('connect')
def on_connect():
    emit('content-update', load_content())


@socketio.on('request-content')
def on_request_content():
    emit('content-update', load_content())


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"MSMP Server: http://localhost:{port}")
    print(f"Admin Panel: http://localhost:{port}/admin")
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
