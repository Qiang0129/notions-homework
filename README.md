# 课信 · 本地作业邮件提醒助手

面向助教的中文本地 Web 应用：管理发件邮箱和班级名单，编辑富文本通知，预览、试发，再逐人群发并核查每一封的投递结果。

单用户、单进程，只在本机或可信局域网运行；名单、正文和凭据都留在自己的电脑上。

技术：FastAPI、SQLAlchemy / SQLite、Jinja2、Bootstrap 5、Quill 2。无 Node 构建，静态依赖随项目提供。

## 功能

- **发件邮箱**：QQ、Gmail 或自定义 SMTP。只支持隐式 TLS 与 STARTTLS，不降级、不跳过证书校验。
- **班级名单**：粘贴、CSV、XLSX 导入；重复与姓名冲突逐行列出，不静默丢弃。
- **通知编辑**：模板、草稿、富文本，支持按收件人替换变量。
- **预览与试发**：切换收件人查看姓名替换效果；试发只发给你指定的测试邮箱。
- **群发**：1–5 路并发、每路 1–60 秒间隔；发送前核对发件邮箱、完整名单与策略。
- **结果核查**：逐人记录状态和说明，把"已提交"和"确定没发出去"分开对待。

## 快速开始

需要 Python 3.11 或更新版本。以下命令均在项目根目录执行。

```powershell
& '.\run.ps1' -OpenBrowser
```

首次启动会创建独立 `.venv` 并安装锁定依赖（需要联网），不会改动 Conda 基础环境。默认只监听 `127.0.0.1:8000`；首次请在运行服务的电脑上打开页面，设置至少 12 个字符的管理员密码。

```powershell
& '.\run.ps1' -Port 8010 -OpenBrowser   # 换端口
& '.\run.ps1' -Lan                      # 允许同局域网设备访问
& '.\run.ps1' -InstallOnly              # 只准备环境，不启动
```

若系统禁止运行脚本，可只对这次进程放行，不修改系统策略：

```powershell
& 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -ExecutionPolicy Bypass -File '.\run.ps1' -OpenBrowser
```

## 第一次使用

1. **邮箱设置** → 添加 SMTP，保存后先点"测试连接"（只测连接、TLS 和认证，不发信）。
2. **班级名单** → 新建班级，粘贴或上传名单，检查预览后确认导入。
3. **写通知** → 选择发件邮箱和模板，填写课程、作业、北京时间截止时间和提交邮箱。
4. 选择班级与收件同学，切换预览收件人确认效果。
5. 点"发送测试"，到自己的测试邮箱检查实际显示。
6. 点"确认并发送"，核对发件邮箱、主题、完整名单和发送策略后创建任务。
7. 在**发送记录**中查看逐人结果；发送期间保持电脑与服务运行。

## SMTP 配置

- **QQ**：`smtp.qq.com`，端口 `465`，隐式 TLS。先在邮箱设置中开启 SMTP 并获取授权码。
- **Gmail**：`smtp.gmail.com`，端口 `587`，STARTTLS。开启两步验证后创建应用专用密码；学校账号可能不可用，本版不支持 Google OAuth。
- **自定义**：填写服务商实际提供的地址、端口、加密方式和账号。只支持隐式 TLS 或 STARTTLS，不会回退到明文。

编辑邮箱时授权码留空表示保持原值，已保存的授权码不会回显。

## 名单导入

每行一位，支持以下写法：

```text
张同学 zhang@example.com
李同学,li@example.com
王同学 <wang@example.com>
John Smith john@example.com
```

CSV 支持 UTF-8 / UTF-8 BOM / GB18030，XLSX 读取第一个工作表，自动识别"姓名/name"与"邮箱/email"表头，也可手动指定列。单次上限 5 MB、5000 行、100 列。`examples` 目录提供虚构样例。

## 变量

在主题、标题和正文中插入：`{{name}}` 姓名、`{{class_name}}` 班级、`{{course}}` 课程、`{{assignment}}` 作业、`{{deadline}}` 截止时间、`{{submission_email}}` 提交邮箱。未知变量、格式错误或缺少必填数据会阻止发送。

## 发送状态

- **排队中 / 发送中 / 待发送**：一人一封，尚未完成提交。
- **已提交**：SMTP 服务器已接受，不等于送达、已读或不会退信。
- **明确失败**：确定未提交，可对失败项创建重试任务。
- **结果待确认**：提交阶段断线，可能已投递。不会自动重试，需人工核查。
- **已暂停 / 已中断 / 已取消**：分别对应服务商全局错误、应用停止、用户取消。

发送任务会冻结当时的正文、收件人和非敏感邮箱参数；同一任务只含一个班级，按邮箱去重。

## 数据与安全

- 数据库默认位于 `%LOCALAPPDATA%\HomeworkReminder\app.db`，可用 `HMR_DATA_DIR` 指定其他目录；同一目录只允许运行一个实例。
- SMTP 授权码保存在 Windows 系统凭据库，不写数据库、不在页面回显；凭据库不可用时不会退回明文存储。
- 管理员密码为 Argon2 哈希，会话 Cookie 为 HttpOnly / SameSite=Strict，8 小时过期；带 CSRF 校验、来源检查和登录限速。
- 数据库本身不加密，请保护 Windows 账户与磁盘权限。备份前先停止服务，再复制整个数据目录；Windows 凭据不随数据库迁移。

## 局域网访问

`-Lan` 会监听所有本地接口，供同一私人网络里的手机访问。网页传输是 **HTTP，未加密**，密码、名单和新输入的授权码可能被同网段的人看到：不要用于公共 Wi-Fi，不要做公网端口映射，建议在运行服务的电脑本机配置 SMTP 凭据。

## 边界

仅手动发送。没有定时提醒、提交状态回传、教务系统对接、附件上传、已读追踪、Google OAuth、多管理员和公网部署；不绕过服务商的配额、反垃圾邮件策略或网络限制。

## 开发

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r '.\requirements-dev.lock.txt'
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' '.\scripts\browser_check.py'
```

浏览器检查优先使用已安装的 Microsoft Edge，否则先执行 `-m playwright install chromium`。检查使用临时数据库、内存凭据和 SMTP 替身，不接触生产数据、不发送真实邮件，截图与报告写入 `output\playwright`。

更详细的验证记录与变更清单见 [TEST_REPORT.md](TEST_REPORT.md)，视觉规范见 [DESIGN.md](DESIGN.md)，产品定位见 [PRODUCT.md](PRODUCT.md)，第三方组件与许可证见 [THIRD_PARTY.md](THIRD_PARTY.md)。
