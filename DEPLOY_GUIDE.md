# MSMP 腾讯云部署指南 — 完整版

> 从零开始，把 MSMP 网站 + Minecraft 服务器 + MSMPBridge 插件完整部署到腾讯云。

---

## 📋 前提条件

| 项目 | 要求 |
|------|------|
| 腾讯云服务器 | 2核4G+，推荐 CentOS 8 / Ubuntu 22.04 |
| Java | JDK 17+（MC 服务器需要） |
| Python | 3.8+（网站后端需要） |
| 域名 | `msmp.mplusm.site` 已解析到服务器 IP |
| 本地工具 | SSH 终端（如 PuTTY / Windows Terminal） |

---

## 架构总览

```
互联网用户
    │
    ▼
┌──────────────────────────────────────────────────┐
│  腾讯云服务器                                      │
│                                                    │
│  ┌──────────┐    反向代理     ┌──────────────────┐  │
│  │  Nginx   │ ────────────► │  Flask 网站       │  │
│  │  :80/443 │    :5000      │  + SocketIO       │  │
│  └──────────┘               └──────────────────┘  │
│                                    ▲               │
│                                    │ HTTP API      │
│                              ┌─────┴──────────┐   │
│                              │  MSMPBridge     │   │
│                              │  (Paper 插件)    │   │
│                              └─────▲──────────┘   │
│                                    │               │
│                              ┌─────┴──────────┐   │
│                              │  Paper 1.21.11  │   │
│                              │  MC 服务器 :25565 │   │
│                              └────────────────┘   │
└──────────────────────────────────────────────────┘
```

---

## 第一部分：服务器基础环境

### 步骤 1：SSH 连接到服务器

```bash
# 在本地终端执行（替换为你的服务器 IP）
ssh root@你的服务器IP
```

### 步骤 2：更新系统

```bash
# CentOS/AlmaLinux/Rocky Linux
sudo dnf update -y

# Ubuntu/Debian
sudo apt update && sudo apt upgrade -y
```

### 步骤 3：安装 Java 17+

```bash
# CentOS/AlmaLinux/Rocky Linux
sudo dnf install java-17-openjdk-devel -y

# Ubuntu/Debian
sudo apt install openjdk-17-jdk -y

# 验证
java -version
# 应显示 openjdk version "17.x.x"
```

### 步骤 4：安装 Python 3 + 工具

```bash
# CentOS/AlmaLinux/Rocky Linux
sudo dnf install python3 python3-pip python3-venv -y

# Ubuntu/Debian
sudo apt install python3 python3-pip python3-venv -y

# 验证
python3 --version
```

### 步骤 5：开放防火墙端口

```bash
# CentOS/AlmaLinux/Rocky Linux (firewalld)
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --permanent --add-port=443/tcp
sudo firewall-cmd --permanent --add-port=25565/tcp
sudo firewall-cmd --reload

# Ubuntu/Debian (ufw)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 25565/tcp
```

⚠️ **腾讯云安全组也必须开放**：

1. 登录 [腾讯云控制台](https://console.cloud.tencent.com/cvm) → 云服务器 → 安全组
2. 找到服务器绑定的安全组，添加入站规则：

| 端口 | 来源 | 用途 |
|------|------|------|
| 80 | 0.0.0.0/0 | HTTP 网站访问 |
| 443 | 0.0.0.0/0 | HTTPS（可选） |
| 25565 | 0.0.0.0/0 | Minecraft 服务器 |

---

## 第二部分：部署 Minecraft 服务器

### 步骤 6：创建目录

```bash
sudo mkdir -p /opt/msmp-minecraft
sudo chown $(whoami) /opt/msmp-minecraft
cd /opt/msmp-minecraft
```

### 步骤 7：下载 Paper 1.21.11

```bash
# 下载最新 Paper 1.21.11 构建
# 请到 https://papermc.io/downloads/paper 查看最新构建号
wget -O paper-1.21.11.jar "https://api.papermc.io/v2/projects/paper/versions/1.21.11/builds/最新构建号/downloads/paper-1.21.11-最新构建号.jar"
```

> 💡 请到 https://papermc.io/downloads/paper 页面找到 1.21.11 版本的最新构建号，替换上面命令中的 `最新构建号`。

### 步骤 8：首次启动（生成配置文件）

```bash
# 接受 EULA
echo "# By changing the setting below to TRUE you are indicating your agreement to our EULA (https://aka.ms/MinecraftEULA)." > eula.txt
echo "eula=true" >> eula.txt

# 首次启动
java -Xms1G -Xmx2G -jar paper-1.21.11.jar --nogui
```

首次启动会生成 `server.properties` 等配置文件，看到 `Done!` 后输入 `stop` 关闭服务器。

### 步骤 9：配置 server.properties

```bash
nano server.properties
```

修改以下关键配置：

```properties
# 服务器端口（默认 25565）
server-port=25565

# 最大玩家数
max-players=50

# 关闭正版验证（离线服务器）
online-mode=false

# 开启白名单
white-list=true
enforce-whitelist=true

# MOTD（服务器列表显示的文字）
motd=MSMP - Minecraft 1.21.11

# 视距（影响性能，建议 8-12）
view-distance=8
simulation-distance=10

# 游戏模式
gamemode=survival
```

保存退出（`Ctrl+O` → `Enter` → `Ctrl+X`）。

### 步骤 10：安装 ViaVersion（支持多版本客户端）

ViaVersion 让 1.9-1.26 的客户端都能加入你的 1.21.11 服务器。

```bash
cd /opt/msmp-minecraft/plugins

# 下载 ViaVersion
wget -O ViaVersion.jar "https://github.com/ViaVersion/ViaVersion/releases/latest/download/ViaVersion-5.x.jar"

# 下载 ViaBackwards（让低版本客户端看到高版本内容）
wget -O ViaBackwards.jar "https://github.com/ViaVersion/ViaBackwards/releases/latest/download/ViaBackwards-5.x.jar"

# 下载 ViaRewind（额外兼容性）
wget -O ViaRewind.jar "https://github.com/ViaVersion/ViaRewind/releases/latest/download/ViaRewind-5.x.jar"
```

> 💡 如果下载链接失效，请到以下页面手动下载：
> - ViaVersion: https://modrinth.com/plugin/viaversion
> - ViaBackwards: https://modrinth.com/plugin/viabackwards
> - ViaRewind: https://modrinth.com/plugin/viarewind

### 步骤 11：创建 MC 服务器启动脚本

```bash
cat > /opt/msmp-minecraft/start.sh << 'EOF'
#!/bin/bash
# MSMP Minecraft 服务器启动脚本
# 服务端版本: Paper 1.21.11

cd "$(dirname "$0")"

# 内存设置（默认 2G，可通过环境变量覆盖）
MEMORY="${MSMP_MEMORY:-2G}"

# 查找 Java
JAVA_CMD="${JAVA_HOME:+$JAVA_HOME/bin/java}"
if [ -z "$JAVA_CMD" ]; then
    JAVA_CMD=$(command -v java 2>/dev/null)
fi

if [ -z "$JAVA_CMD" ]; then
    echo "[ERROR] Java not found! Install JDK 17+"
    exit 1
fi

echo "Starting MSMP Minecraft Server (Paper 1.21.11)"
echo "  Java: $JAVA_CMD"
echo "  Memory: $MEMORY"

exec $JAVA_CMD -Xms1G -Xmx$MEMORY \
    -XX:+UseG1GC \
    -XX:+ParallelRefProcEnabled \
    -XX:MaxGCPauseMillis=200 \
    -XX:+UnlockExperimentalVMOptions \
    -XX:+DisableExplicitGC \
    -XX:G1NewSizePercent=30 \
    -XX:G1MaxNewSizePercent=40 \
    -XX:G1HeapRegionSize=8M \
    -XX:G1ReservePercent=20 \
    -XX:G1HeapWastePercent=5 \
    -XX:G1MixedGCCountTarget=4 \
    -XX:InitiatingHeapOccupancyPercent=15 \
    -XX:G1MixedGCLiveThresholdPercent=90 \
    -XX:G1RSetUpdatingPauseTimePercent=5 \
    -XX:SurvivorRatio=32 \
    -XX:+PerfDisableSharedMem \
    -XX:MaxTenuringThreshold=1 \
    -Dusing.aikars.flags=https://mcflags.emc.gs \
    -Daikars.new.flags=true \
    -jar paper-1.21.11.jar --nogui
EOF

chmod +x /opt/msmp-minecraft/start.sh
```

> 💡 上面使用了 [Aikar's Flags](https://mcflags.emc.gs/)，这是 Minecraft 服务器最优的 JVM 参数，可以显著减少 GC 停顿。

### 步骤 12：创建 MC 服务器 systemd 服务（开机自启）

```bash
sudo nano /etc/systemd/system/msmp-minecraft.service
```

粘贴：

```ini
[Unit]
Description=MSMP Minecraft Server (Paper 1.21.11)
After=network.target

[Service]
User=root
WorkingDirectory=/opt/msmp-minecraft
ExecStart=/opt/msmp-minecraft/start.sh
ExecStop=/bin/bash -c "echo 'stop' > /proc/$MAINPID/fd/0"
Restart=on-failure
RestartSec=30

# 标准输入输出
StandardInput=null
StandardOutput=journal
StandardError=journal

# 资源限制
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
# 加载并启动
sudo systemctl daemon-reload
sudo systemctl start msmp-minecraft
sudo systemctl enable msmp-minecraft

# 查看状态
sudo systemctl status msmp-minecraft

# 查看日志
journalctl -u msmp-minecraft -f
```

常用管理命令：

```bash
sudo systemctl start msmp-minecraft     # 启动
sudo systemctl stop msmp-minecraft      # 停止
sudo systemctl restart msmp-minecraft   # 重启
sudo systemctl status msmp-minecraft    # 查看状态
journalctl -u msmp-minecraft -f         # 实时日志
```

> 💡 在游戏内执行命令（RCON 方式）：
> ```bash
> sudo apt install mcrcon -y   # 安装 mcrcon
> mcrcon -H localhost -P 25575 -p 你的rcon密码 "say Hello World"
> ```

---

## 第三部分：部署 MSMP 网站

### 步骤 13：上传网站文件

**方法 A：scp 上传（推荐）**

在本地 Windows 电脑上：

```powershell
cd C:\Users\mckin\WorkBuddy\20260502124030

# 打包文件（不包含 venv 和 test-server）
Compress-Archive -Path server.py, .env, public, data, requirements.txt, start.sh -DestinationPath msmp-website.zip -Force

# 上传到服务器
scp msmp-website.zip root@你的服务器IP:/root/
```

**方法 B：直接在服务器上创建文件**

如果你更倾向于直接在服务器上编辑，可以从 GitHub 拉取或手动创建。

### 步骤 14：在服务器上解压

```bash
sudo mkdir -p /opt/msmp-website
cd /opt/msmp-website
unzip /root/msmp-website.zip
```

解压后目录结构：

```
/opt/msmp-website/
├── server.py           # Flask + SocketIO 后端
├── .env                # 环境变量配置
├── requirements.txt    # Python 依赖
├── start.sh            # 启动脚本
├── public/
│   ├── index.html      # 首页
│   ├── admin.html      # 管理面板
│   ├── icon.png        # 服务器图标
│   ├── motd.png        # MOTD 截图
│   └── Minecraft_Next_Font_12px.ttf
└── data/
    ├── content.json    # 网站内容数据
    └── players.json    # 玩家账户数据
```

### 步骤 15：创建虚拟环境并安装依赖

```bash
cd /opt/msmp-website

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 步骤 16：配置 .env 文件

```bash
nano /opt/msmp-website/.env
```

确认/修改以下配置：

```ini
# 管理员密码（请修改为强密码！）
ADMIN_PASSWORD=msmp2026

# 网站端口
PORT=5000

# Flask 密钥（请修改为随机字符串！）
SECRET_KEY=msmp-secret-2026-stable

# MC 服务器目录（用于白名单文件写入，留空则由插件管理）
MC_SERVER_DIR=/opt/msmp-minecraft

# 插件 API Key（必须和插件 config.yml 一致！）
PLUGIN_API_KEY=msmp-plugin-2026
```

> ⚠️ **安全提示**：生产环境请务必修改 `ADMIN_PASSWORD`、`SECRET_KEY`、`PLUGIN_API_KEY` 为随机强字符串！

### 步骤 17：修改 server.py 适配生产环境

```bash
nano /opt/msmp-website/server.py
```

需要修改两处：

```python
# 1. 修改 async_mode（约第 19 行）
# 修改前（开发模式）：
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 修改后（生产模式）：
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')
```

```python
# 2. 修改启动参数（文件末尾）
# 修改前：
socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)

# 修改后：
socketio.run(app, host='0.0.0.0', port=port)
```

> 💡 如果使用 `async_mode='gevent'`，确保已安装 gevent：`pip install gevent`

### 步骤 18：测试网站

```bash
cd /opt/msmp-website
source venv/bin/activate
python server.py
```

看到 `MSMP Server: http://localhost:5000` 就成功了。按 `Ctrl+C` 停掉。

### 步骤 19：创建网站 systemd 服务

```bash
sudo nano /etc/systemd/system/msmp-website.service
```

粘贴：

```ini
[Unit]
Description=MSMP Website (Flask + SocketIO)
After=network.target

[Service]
User=root
WorkingDirectory=/opt/msmp-website
ExecStart=/opt/msmp-website/venv/bin/python server.py
Restart=always
RestartSec=5
Environment=PATH=/opt/msmp-website/venv/bin

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl start msmp-website
sudo systemctl enable msmp-website

# 验证
sudo systemctl status msmp-website
```

常用命令：

```bash
sudo systemctl restart msmp-website   # 重启
sudo systemctl stop msmp-website       # 停止
journalctl -u msmp-website -f          # 实时日志
```

---

## 第四部分：安装 MSMPBridge 插件

MSMPBridge 是网站和 MC 服务器之间的桥梁，负责自动同步白名单、推送服务器状态。

### 步骤 20：编译插件（在本地电脑）

```powershell
# 在本地 Windows 电脑上
cd C:\Users\mckin\WorkBuddy\20260502124030\MSMPBridge

# 使用 Maven 编译
mvn clean package

# 编译成功后 JAR 位于
# target/MSMPBridge-1.0.0.jar
```

> 💡 如果没有 Maven，可以安装或使用项目自带的：`..\apache-maven-3.9.15\bin\mvn.cmd clean package`

### 步骤 21：上传插件到服务器

```powershell
# 在本地电脑执行
scp C:\Users\mckin\WorkBuddy\20260502124030\MSMPBridge\target\MSMPBridge-1.0.0.jar root@你的服务器IP:/opt/msmp-minecraft/plugins/
```

或者直接在服务器上编译（需要 Maven + JDK 17）：

```bash
# 上传 MSMPBridge 整个目录
cd /opt/msmp-minecraft/plugins
# 编译
cd MSMPBridge && mvn clean package
cp target/MSMPBridge-1.0.0.jar ../
cd .. && rm -rf MSMPBridge
```

### 步骤 22：配置插件

重启 MC 服务器让插件生成配置文件：

```bash
sudo systemctl restart msmp-minecraft

# 等待几秒让插件加载
sleep 5
sudo systemctl stop msmp-minecraft
```

编辑插件配置：

```bash
nano /opt/msmp-minecraft/plugins/MSMPBridge/config.yml
```

确认以下配置：

```yaml
# 网站地址（同一台服务器用 localhost）
website-url: "http://localhost:5000"

# API 密钥（必须和网站 .env 中的 PLUGIN_API_KEY 一致！）
api-key: "msmp-plugin-2026"

# 同步间隔（秒）
sync-interval: 30

# 自动白名单同步
auto-whitelist: true

# 发送玩家事件
send-player-events: true

# 发送心跳（服务器状态）
send-heartbeat: true

# 调试模式（生产环境建议关闭）
debug: false
```

> ⚠️ **关键**：`api-key` 必须和网站 `.env` 中的 `PLUGIN_API_KEY` 完全一致！

### 步骤 23：启动并验证

```bash
sudo systemctl start msmp-minecraft

# 查看日志确认插件连接
journalctl -u msmp-minecraft -f
```

看到以下日志说明连接成功：

```
[MSMPBridge] Successfully connected to website API!
[MSMPBridge] Added xxx to whitelist via UUID
```

在游戏内或控制台执行验证：

```
/msmp status
```

应显示：

```
===== MSMPBridge Status =====
Website: http://localhost:5000
Connected: Yes
Auto-whitelist: true
Send events: true
Sync interval: 30s
TPS (1m/5m/15m): 20.0 / 20.0 / 20.0
Online players: 0 / 50
```

---

## 第五部分：Nginx 反向代理

### 步骤 24：安装 Nginx

```bash
# CentOS/AlmaLinux/Rocky Linux
sudo dnf install nginx -y

# Ubuntu/Debian
sudo apt install nginx -y
```

### 步骤 25：配置 Nginx

```bash
sudo nano /etc/nginx/conf.d/msmp.conf
```

粘贴：

```nginx
server {
    listen 80;
    server_name msmp.mplusm.site;

    # 网站主页和 API
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket 支持（Socket.io 实时推送必须！）
    location /socket.io/ {
        proxy_pass http://127.0.0.1:5000/socket.io/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }
}
```

### 步骤 26：启动 Nginx

```bash
# 测试配置
sudo nginx -t

# 启动并设置开机自启
sudo systemctl start nginx
sudo systemctl enable nginx
```

如果 `nginx -t` 报错（默认配置冲突）：

```bash
sudo mv /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.bak 2>/dev/null
sudo systemctl restart nginx
```

### 步骤 27：验证网站

在浏览器打开：

```
http://msmp.mplusm.site
```

如果能看到网站首页，🎉 部署成功！

管理面板地址：`http://msmp.mplusm.site/admin`

---

## 第六部分（可选）：配置 HTTPS

### 步骤 28：安装 certbot 并申请证书

```bash
# CentOS
sudo dnf install certbot python3-certbot-nginx -y

# Ubuntu
sudo apt install certbot python3-certbot-nginx -y

# 自动申请并配置证书
sudo certbot --nginx -d msmp.mplusm.site
```

按提示操作，证书会自动续期。

验证自动续期：

```bash
sudo certbot renew --dry-run
```

---

## 第七部分（可选）：安装 TAB 插件

TAB 插件给玩家列表添加分组标签（服主/管理员/玩家）。

### 步骤 29：安装 TAB

1. 下载 TAB 插件：https://modrinth.com/plugin/tab
2. 将 JAR 文件放到 `/opt/msmp-minecraft/plugins/`
3. 重启服务器

### 步骤 30：配置 TAB 分组

```bash
nano /opt/msmp-minecraft/plugins/TAB/config.yml
```

找到 `groups` 部分，按下面修改：

```yaml
groups:
  # 服主标签 — 深红色加粗
  owner:
    tabprefix: "&4&l[服主] &4"
    tagprefix: "&4&l[服主] &4"
    tabsuffix: ""
    tagsuffix: ""
  # 管理员标签 — 红色
  admin:
    tabprefix: "&c[管理员] &c"
    tagprefix: "&c[管理员] &c"
    tabsuffix: ""
    tagsuffix: ""
  # 普通玩家标签 — 灰色
  default:
    tabprefix: "&7"
    tagprefix: "&7"
    tabsuffix: ""
    tagsuffix: ""
```

> 💡 **颜色代码**：`&4` = 深红，`&c` = 红色，`&6` = 金色，`&a` = 绿色，`&7` = 灰色，`&l` = 加粗

在游戏内分配分组：

```
/tab player 你的游戏名 group owner
/tab player 管理员名字 group admin
```

---

## 第八部分：域名解析

如果域名还没解析到服务器 IP：

1. 登录你的域名服务商（`mplusm.site` 在哪买的就去哪）
2. 添加 DNS 记录：

| 主机记录 | 记录类型 | 记录值 |
|----------|----------|--------|
| `msmp` | A | `你的服务器公网IP` |
| `@`（可选） | A | `你的服务器公网IP` |

3. 等待 DNS 生效（通常几分钟到几小时）

验证解析：

```bash
# 在本地电脑执行
nslookup msmp.mplusm.site
# 应返回你的服务器 IP
```

---

## 🎯 完整操作清单

| # | 操作 | 关键命令 |
|---|------|----------|
| 1 | SSH 连接服务器 | `ssh root@IP` |
| 2 | 更新系统 | `dnf update -y` / `apt upgrade -y` |
| 3 | 安装 Java 17 | `dnf install java-17-openjdk-devel -y` |
| 4 | 安装 Python 3 | `dnf install python3 python3-venv -y` |
| 5 | 开放防火墙端口 | 80, 443, 25565 |
| 6 | 开放腾讯云安全组 | 80, 443, 25565 |
| 7 | 下载 Paper 1.21.11 | `wget -O paper-1.21.11.jar ...` |
| 8 | 首次启动生成配置 | `java -jar paper-1.21.11.jar --nogui` |
| 9 | 编辑 server.properties | online-mode=false, white-list=true |
| 10 | 安装 ViaVersion | JAR 放到 plugins/ |
| 11 | 创建 MC 启动脚本 | start.sh（含 Aikar's Flags） |
| 12 | 创建 MC systemd 服务 | msmp-minecraft.service |
| 13 | 上传网站文件 | `scp msmp-website.zip root@IP:/root/` |
| 14 | 解压到 /opt/msmp-website | `unzip msmp-website.zip` |
| 15 | 创建 venv + 安装依赖 | `pip install -r requirements.txt` |
| 16 | 配置 .env | 修改密码、SECRET_KEY、API_KEY |
| 17 | 修改 server.py | async_mode='gevent'，去掉 debug |
| 18 | 测试网站 | `python server.py` |
| 19 | 创建网站 systemd 服务 | msmp-website.service |
| 20 | 编译 MSMPBridge 插件 | `mvn clean package` |
| 21 | 上传插件到服务器 | `scp MSMPBridge-1.0.0.jar root@IP:.../plugins/` |
| 22 | 配置插件 config.yml | api-key 与网站一致 |
| 23 | 验证插件连接 | `/msmp status` → Connected: Yes |
| 24 | 安装 Nginx | `dnf install nginx -y` |
| 25 | 配置 Nginx 反向代理 | msmp.conf（含 WebSocket） |
| 26 | 启动 Nginx | `systemctl start nginx` |
| 27 | 验证网站访问 | 浏览器打开 http://msmp.mplusm.site |
| 28 | 配置 HTTPS（可选） | `certbot --nginx -d msmp.mplusm.site` |
| 29-30 | TAB 插件（可选） | 安装 + 配置分组 |

---

## ❓ 常见问题

### Q: 网站访问不了？
依次检查：
1. 网站服务：`systemctl status msmp-website`
2. Nginx 服务：`systemctl status nginx`
3. 本地测试：`curl http://localhost:5000`（在服务器上）
4. 防火墙：`curl -I http://localhost:80`
5. 腾讯云安全组是否开放 80 端口
6. DNS 解析：`nslookup msmp.mplusm.site`

### Q: MC 服务器连不上？
依次检查：
1. 服务器状态：`systemctl status msmp-minecraft`
2. 端口监听：`ss -tlnp | grep 25565`
3. 防火墙是否开放 25565
4. 腾讯云安全组是否开放 25565
5. 客户端版本是否在 ViaVersion 支持范围内（1.9-1.26）

### Q: MSMPBridge 显示 Connected: No？
检查：
1. 网站是否运行：`curl http://localhost:5000/api/plugin/ping?apiKey=msmp-plugin-2026`
2. 插件 config.yml 中的 `api-key` 是否与网站 `.env` 的 `PLUGIN_API_KEY` 一致
3. 插件 config.yml 中的 `website-url` 是否正确
4. 网站日志：`journalctl -u msmp-website -f`

### Q: Socket.io 实时更新不工作？
检查 Nginx 配置中 `/socket.io/` 的 WebSocket 代理：
1. `proxy_http_version 1.1` 是否配置
2. `Upgrade` 和 `Connection "upgrade"` header 是否设置
3. `proxy_read_timeout` 是否够长（建议 86400）

### Q: 白名单同步不生效？
1. 检查 `auto-whitelist` 是否为 `true`
2. 玩家是否在网站注册且 `whitelisted=true`
3. 使用 `/msmp sync` 手动触发
4. 检查日志是否有 UUID 解析错误
5. 确认 `MC_SERVER_DIR` 是否正确设置

### Q: 性能优化建议？
1. **JVM 参数**：使用 Aikar's Flags（已在启动脚本中包含）
2. **内存分配**：2G 起，4G+ 推荐玩家多的情况
3. **视距**：`view-distance=8`，`simulation-distance=10`
4. **Paper 配置**：编辑 `paper-global.yml` 调优
5. **预生成区块**：使用 Chunky 插件预生成世界

### Q: 如何更新网站？
```bash
# 在本地打包新版本
Compress-Archive -Path server.py, .env, public, data, requirements.txt -DestinationPath msmp-website.zip -Force

# 上传并解压
scp msmp-website.zip root@你的服务器IP:/root/
ssh root@你的服务器IP
cd /opt/msmp-website && unzip -o /root/msmp-website.zip

# 重启网站
sudo systemctl restart msmp-website
```

### Q: 如何更新插件？
```bash
# 在本地编译
cd MSMPBridge && mvn clean package

# 上传
scp target/MSMPBridge-1.0.0.jar root@服务器IP:/opt/msmp-minecraft/plugins/

# 重启 MC 服务器
ssh root@服务器IP "systemctl restart msmp-minecraft"
```

---

## 📁 服务器文件结构总览

```
/opt/
├── msmp-website/                    # 网站
│   ├── server.py                     # Flask + SocketIO 后端
│   ├── .env                          # 环境变量
│   ├── requirements.txt              # Python 依赖
│   ├── start.sh                      # 启动脚本
│   ├── venv/                         # Python 虚拟环境
│   ├── public/                       # 前端文件
│   │   ├── index.html
│   │   ├── admin.html
│   │   ├── icon.png
│   │   ├── motd.png
│   │   └── Minecraft_Next_Font_12px.ttf
│   └── data/                         # 数据文件
│       ├── content.json
│       └── players.json
│
└── msmp-minecraft/                   # MC 服务器
    ├── paper-1.21.11.jar             # Paper 服务端
    ├── start.sh                      # 启动脚本
    ├── eula.txt                      # EULA
    ├── server.properties             # 服务器配置
    ├── whitelist.json                # 白名单
    ├── ops.json                      # OP 列表
    ├── world/                        # 主世界
    ├── world_nether/                 # 下界
    ├── world_the_end/                # 末地
    └── plugins/                      # 插件目录
        ├── MSMPBridge-1.0.0.jar      # MSMPBridge 插件
        ├── MSMPBridge/              # 插件配置
        │   └── config.yml
        ├── ViaVersion.jar
        ├── ViaBackwards.jar
        ├── ViaRewind.jar
        └── TAB/                     # TAB 插件配置
            └── config.yml
```
