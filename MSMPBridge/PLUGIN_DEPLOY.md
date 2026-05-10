# MSMPBridge 插件部署指南

## 概述

MSMPBridge 是一个 Paper 1.21.11 服务端插件，用于在 Minecraft 服务器和 MSMP 网站之间自动同步数据。

**功能：**
- 玩家在网站注册后，插件自动将其加入游戏白名单
- 实时推送服务器状态（TPS、在线玩家）到网站
- 玩家加入/离开服务器时，网站实时显示
- 支持手动同步命令 `/msmp sync`

---

## 前提条件

1. **Paper 1.21.11** 服务端（或兼容版本）
2. **Java 17+** 运行环境
3. **Maven 3.8+** 用于编译插件
4. MSMP 网站已部署并运行

---

## 第一步：编译插件

### 1. 安装 Java JDK 17+

```bash
# Ubuntu/Debian
sudo apt install openjdk-17-jdk

# CentOS/RHEL
sudo yum install java-17-openjdk-devel

# 验证
java -version
javac -version
```

### 2. 安装 Maven

```bash
# Ubuntu/Debian
sudo apt install maven

# CentOS/RHEL
sudo yum install maven

# 验证
mvn -version
```

### 3. 编译

将 `MSMPBridge` 文件夹上传到服务器（或本地编译），然后执行：

```bash
cd MSMPBridge
mvn clean package
```

编译成功后，JAR 文件位于 `target/MSMPBridge-1.0.0.jar`

---

## 第二步：安装插件

1. 将编译好的 JAR 文件复制到服务器的 `plugins/` 目录：

```bash
cp target/MSMPBridge-1.0.0.jar /你的MC服务器路径/plugins/
```

2. 重启服务器（或使用 PlugMan 等插件管理器热加载）

---

## 第三步：配置插件

首次启动后，插件会在 `plugins/MSMPBridge/` 目录下生成 `config.yml`：

```yaml
# 网站地址（不要带尾部斜杠）
# 同一台服务器用 http://localhost:5000
# 不同服务器用 http://网站IP:5000 或 https://msmp.mplusm.site
website-url: "http://localhost:5000"

# API 密钥（必须与网站 .env 中的 PLUGIN_API_KEY 一致）
api-key: "msmp-plugin-2026"

# 同步间隔（秒）
sync-interval: 30

# 自动添加待处理白名单
auto-whitelist: true

# 发送玩家事件到网站
send-player-events: true

# 发送服务器心跳
send-heartbeat: true

# 调试模式
debug: false
```

### 重要配置说明

- **website-url**：如果网站和 MC 服务器在同一台机器上，使用 `http://localhost:5000`。如果使用 Nginx 反向代理，也可以用 `http://localhost:5000`。
- **api-key**：必须与网站 `.env` 文件中的 `PLUGIN_API_KEY` 完全一致。**修改后请同时更新两边！**

修改配置后，使用 `/msmp reload` 重载，或重启服务器。

---

## 第四步：验证连接

在服务器控制台或游戏中输入：

```
/msmp status
```

应该看到：
```
===== MSMPBridge Status =====
Website: http://localhost:5000
Connected: Yes
Auto-whitelist: true
Send events: true
Sync interval: 30s
TPS (1m/5m/15m): 20.0 / 20.0 / 20.0
Online players: 1 / 50
```

如果显示 `Connected: No`，请检查：
1. 网站是否正在运行
2. `website-url` 是否正确
3. `api-key` 是否与网站一致
4. 防火墙是否放行 5000 端口

---

## 工作原理

```
┌─────────────────┐         HTTP API          ┌─────────────────┐
│  MC 服务器       │ ◄──────────────────────► │  MSMP 网站       │
│  (MSMPBridge)    │                            │  (Flask)         │
├─────────────────┤                            ├─────────────────┤
│                 │  POST /heartbeat           │                 │
│  每30秒发送      │  ───────────────────►      │  更新服务器状态    │
│  TPS + 在线玩家  │                            │  推送到前端       │
│                 │                            │                 │
│  玩家加入/离开   │  POST /player-event        │  显示实时通知     │
│                 │  ───────────────────►      │                 │
│                 │                            │                 │
│  定期检查待添加   │  GET /pending-whitelist    │  返回注册未同步    │
│  的白名单玩家    │  ◄───────────────────      │  的玩家列表      │
│                 │                            │                 │
│  添加后确认      │  POST /whitelist-confirmed │  标记已同步       │
│                 │  ───────────────────►      │                 │
└─────────────────┘                            └─────────────────┘
```

---

## 管理命令

| 命令 | 描述 | 权限 |
|------|------|------|
| `/msmp status` | 查看连接状态 | msmp.admin |
| `/msmp sync` | 手动同步 | msmp.admin |
| `/msmp reload` | 重载配置 | msmp.admin |

---

## 常见问题

### Q: 插件启动后显示 "Failed to connect to website API"
A: 检查网站是否运行、URL 是否正确、API Key 是否匹配。

### Q: 玩家注册后没有自动加入白名单
A: 
1. 检查 `auto-whitelist` 是否为 `true`
2. 使用 `/msmp sync` 手动触发同步
3. 检查网站 `players.json` 中玩家的 `whitelisted` 是否为 `true`
4. 查看服务器日志是否有错误

### Q: 网站上显示服务器离线，但实际在线
A: 
1. 检查 `send-heartbeat` 是否为 `true`
2. 检查 `sync-interval` 是否过长
3. 重启插件：`/msmp reload`

### Q: 修改了 API Key 怎么办？
A: 同时修改网站的 `.env` 文件和插件的 `config.yml`，然后重启两边。

---

## 安全建议

1. **修改默认 API Key**：将 `msmp-plugin-2026` 改为你自己的随机字符串
2. **不要将 API Key 暴露在公网**：使用 Nginx 反向代理时，只允许本地访问插件 API
3. **定期检查日志**：查看是否有未授权的 API 访问

---

## 文件结构

```
MSMPBridge/
├── pom.xml                                    # Maven 构建文件
├── src/main/
│   ├── java/com/msmp/bridge/
│   │   ├── MSMPBridge.java                    # 插件主类
│   │   ├── APIClient.java                     # HTTP 通信客户端
│   │   ├── TPSTracker.java                    # TPS 追踪器
│   │   └── commands/
│   │       └── MSMPCommand.java               # /msmp 命令处理
│   └── resources/
│       ├── plugin.yml                          # 插件描述文件
│       └── config.yml                          # 默认配置
└── PLUGIN_DEPLOY.md                            # 本文件
```
