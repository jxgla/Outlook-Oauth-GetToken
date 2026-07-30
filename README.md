# OutlookGetToken

给**已注册**但还没有 `refresh_token` 的 Outlook / Hotmail 账号，批量走一遍 OAuth2 授权，把 token 写入结果文件。

核心脚本：`get_refresh_token.py`（**DrissionPage + 本机 Chrome** 自动化 + 授权码换 token）。

---

## 1. 如何使用

### 1.1 环境

```bash
git clone <this-repo-url>
cd Outlook-Oauth-GetToken
pip install DrissionPage requests
```

要求：
- 本机已安装 Google Chrome
- 代理软件已启动（默认示例为本机 `127.0.0.1:7890`）

### 1.2 准备配置与账号

首次使用：

```bash
# Windows
copy config.example.json config.json
copy not_oauth2.example.txt not_oauth2.txt

# Linux / macOS
cp config.example.json config.json
cp not_oauth2.example.txt not_oauth2.txt
```

编辑 `not_oauth2.txt`，**每行一个账号**：

```text
邮箱----密码
```

示例：

```text
user1@outlook.com----YourPass1
user2@hotmail.com----YourPass2
```

- 以 `#` 开头的行视为注释，忽略  
- 也兼容更长行（如已有 `邮箱----密码----client_id----token`）：**只取前两段** 邮箱与密码  

按需编辑 `config.json`（代理、并发、OAuth scope、辅助邮箱等，见下一节）。

### 1.3 运行

```bash
python get_refresh_token.py
```

成功后会默认追加写入 `Results/oauth2.txt`：

```text
邮箱----密码----client_id----refresh_token----aux_email
```

同时也会写一份更方便导入的 `Results/accounts.txt`：

```text
邮箱----密码----client_id----refresh_token
```

日志写入 `log/`，若 OAuth 失败，故障截图会写到 `log/oauth_debug/`。

### 1.4 使用注意

- 默认会弹真实 Chrome 窗口（`headless=false`）；如需有头但后台运行，可设置 `browser.background=true` 最小化窗口，详见 [docs/browser.md](docs/browser.md)  
- **以无 cookie 冷登录为主**，但会处理 direct consent / direct code / proof / protect-account / kmsi 等变体  
- 若弹出 **保护帐户** 页：
  - `temp_mail.enabled=false` → 仍可尝试跳过
  - `temp_mail.enabled=true` → 优先绑定辅助邮箱
- 若弹出 **验证你的电子邮件** 页：
  - 优先点 **使用密码**
  - 若仍停留在验证页且已有 recovery session，则自动收码验证
- 出现 **帐户已锁定** → 该号直接失败  
- 同一账号多次成功会重复追加到输出文件，请自行去重  

---

## 2. `config.json` 配置

将 `config.example.json` 复制为 `config.json` 后修改。

### 2.1 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `input_file` | string | 输入文件名，默认 `not_oauth2.txt` |
| `output_file` | string | 结果文件，默认 `Results/oauth2.txt`（5 列，追加写入） |
| `accounts_output_file` | string | 精简结果文件，默认 `Results/accounts.txt`（4 列） |
| `concurrent` | number | 并发浏览器数；实际为 `min(concurrent, 账号数)` |
| `headless` | bool | `false`=显示浏览器窗口；`true`=无头运行 |
| `log_dir` | string | 日志目录，默认 `log` |
| `browser` | object | 浏览器配置 |
| `proxy` | object | 代理配置 |
| `oauth2` | object | OAuth 配置 |
| `temp_mail` | object | 辅助邮箱绑定/验证配置 |

### 2.2 `browser`

| 字段 | 说明 |
|------|------|
| `path` | Chrome 路径；留空=自动探测系统 Chrome |
| `window_size` | 固定窗口大小 `[宽, 高]`；`null`=随机真实分辨率 |
| `background` | 有头模式下是否启动后最小化挂后台；`headless=true` 时不生效 |
| `block_images` | 是否禁用图片请求 |

### 2.3 `proxy`

支持三种模式：
- `single`：固定单端口
- `multiple`：端口池
- `pool`：代理清单（支持认证 socks5/http、前置代理链）

| 字段 | 说明 |
|------|------|
| `mode` | `single` / `multiple` / `pool` |
| `type` | `single/multiple` 模式的代理协议，如 `http`、`socks5` |
| `host` | `single/multiple` 模式的代理主机 |
| `single_port` | `mode=single` 时的端口 |
| `port_start` / `port_end` | `mode=multiple` 时的端口闭区间 |
| `max_per_proxy` | 单个端口在进程内最多被选中次数 |
| `pool_type` | `mode=pool` 时，未写 scheme 的默认协议 |
| `pool_file` | `mode=pool` 时的代理清单文件 |
| `front_proxy` | `mode=pool` 时的前置代理（可留空） |

### 2.4 `oauth2`

| 字段 | 说明 |
|------|------|
| `client_id` | 授权客户端 ID |
| `redirect_url` | 回调地址，默认 `http://localhost` |
| `tenant` | OAuth 租户，默认 `common` |
| `Scopes` | **授权页**使用的 full scopes |
| `rt_scope` | `code -> refresh_token` 时用哪组 scope：`graph` / `imap` |

说明：
- 授权页使用 `Scopes` 全量权限
- 换 RT 时根据 `rt_scope` 自动裁成 Graph 或 Outlook(IMAP/SMTP) scope

### 2.5 `temp_mail`

仅当微软弹出 **保护帐户** / **验证你的电子邮件** 时使用。

| 字段 | 说明 |
|------|------|
| `enabled` | `true`=自动绑定/验证辅助邮箱 |
| `provider` | `cloudflare` / `self` |
| `base_url` | cloudflare 风格 temp mail API 根地址 |
| `admin_password` | cloudflare 风格管理员密码 |
| `domain` | 默认域名 |
| `name_prefix` | 本地部分前缀 |
| `enable_prefix` | 是否启用前缀 |
| `timeout` | API 请求超时 |
| `code_timeout` | 等待验证码邮件超时(秒) |
| `poll_interval` | 轮询间隔(秒) |
| `self.*` | 自建 `Ryanlyjp/tempmail` 服务配置 |

---

## 3. 代码流程

入口：`python get_refresh_token.py` → `main()`。

### 3.1 总览

```text
读 config.json 与账号文件
  → 按 concurrent 并发处理每个账号
  → 冷启动打开 OAuth authorize 页面
  → 处理 email / password / proof / protect-account / kmsi / consent / code
  → 成功：追加写入 Results/oauth2.txt + Results/accounts.txt
  → 失败：记录原因后继续下一个
```

### 3.2 单账号流程

```text
启动 Chrome（带代理）
  → 打开 Microsoft OAuth 授权页
  → 状态循环
       ├─ 一旦出现 localhost...?code=     → 立刻结束登录，换 token
       ├─ consent                         → 接受授权
       ├─ account_type                    → 点个人帐户
       ├─ protect_account                 → 绑定辅助邮箱（或失败后跳过）
       ├─ proof_verify                    → 先点“使用密码”，仍停留则辅助邮箱验证
       ├─ kmsi                            → 点“否”
       ├─ password                        → 填密码 + 提交
       └─ email                           → 填邮箱 + 下一步
  → 用 code 换 refresh_token
  → 关浏览器
```

---

## 4. 独立化说明

这个项目已经按独立仓库运行设计：
- 不依赖 `OutlookReg` 运行时 import
- 但内部思路参考了 `OutlookReg`：
  - DrissionPage 浏览器适配
  - OAuth scope split
  - protect-account / proof / kmsi 状态机
  - temp_mail provider 抽象
  - stronger proxy pool/front-proxy 支持

---

## 友情链接

- [linux.do](https://linux.do)：**学AI，上L站！！！**
