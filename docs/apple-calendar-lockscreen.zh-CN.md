# Kindle 锁屏与 Apple 日历联动

本功能把 Apple 日历做成一张独立锁屏，不与 HPC 容量、节点或账户信息叠加。
Kindle 的 KUAL 菜单提供显式按钮，用户可以随时在 HPC 仪表盘和 Apple 日历锁屏之间
切换；两种内容均分别支持竖屏与顺时针右转 90°，并使用独立图片和 ETag。

## 使用方式

打开 KUAL → `BJTU Lock Screen Manager`：

| 按钮 | 行为 |
| --- | --- |
| `Switch: HPC / Apple Calendar` | 在 HPC 仪表盘与独立日历锁屏之间切换 |
| `Show Apple Calendar` | 明确启用独立日历锁屏 |
| `Show HPC dashboard` | 返回 HPC 仪表盘 |

按钮会短暂停止更新器、拉取对应图片并完整校验，然后恢复原有调度。下载失败时保留
当前图片；root 私有的生效模式不会前进。按钮不会直接访问 Mac，也不会唤醒 Mac。

等价的 SSH 命令为：

```sh
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh calendar toggle
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh calendar on
/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh calendar off
```

## 数据流

```text
Apple Calendar.app
  → Mac 本地受授权 EventKit helper，只读取当月 6 周网格覆盖的最多 42 天
  → 仅保留标题、开始/结束时间、全天标记，最多 84 条
  → 在内存中生成独立的日历灰度 PNG（不渲染 HPC 内容）
  → SSH 原子上传最终 PNG；不上传日历 JSON
  → 41 HTTPS 端点校验私有 Bearer header
  → Kindle 按方向和内容模式使用 HTTPS + ETag 拉取
  → PNG/SHA-256 校验与原子替换
```

Mac 每 300 秒运行一次，也会在 HPC 快照变化时被唤起。日历内容变化会进入语义摘要，
因此新事件、时间变化或标题变化会重绘；完全相同的日程不会重复写图或上传。

## 隐私边界

- 默认 `DISPLAY_CONTENT_MODE=dashboard`，日程模式是显式选择；
- 只读取当前月视图的固定 6 周网格（最多 42 天）、最多 84 条事件；
- 只使用标题、开始/结束时间和全天标记；
- 不读取或发布地点、参与人、备注、Calendar 名称、账户信息；
- helper 只把原始响应写入权限 `0600` 的私有临时文件，Python 读取后立即删除；响应不进入
  `snapshot.json`、状态 JSON 或日志；
- 41 只保存最终的 1072×1448、8 位灰度 PNG；
- 日程路由要求 root 私有 curl 配置中的 Bearer header；令牌不放进 URL、USB 配置、
  LaunchAgent、Git、文档或日志；
- 纯 HPC 路由保持原有行为，日程图片不会发布到公开 `kindle-live` 分支。

最终 PNG 必然包含用户选择显示的事件标题。TLS 保护传输，Bearer header 限制读取；
私有 CA 只提供服务器身份认证，本身不等于访问控制。

## Mac 端

首次启用时，macOS 会显示一次“日历完全访问”权限提示。EventKit 没有只读授权等级，
但本 helper 的代码路径只查询事件，绝不创建、修改或删除事件。它以后台 accessory app
运行，不通过 Apple Events，也不会启动 Calendar.app。允许后可运行不输出标题的探测：

```bash
python3 scripts/apple_calendar_agenda.py --hours 24 --max-events 5
```

成功输出只包含 `event_count`。正式安装必须使用 SSH edge 和双方向发布：

```bash
python3 scripts/install_macos_hpc_sync.py --install \
  --ssh-target EDGE_ALIAS \
  --publish-both \
  --publish-calendar
```

日程模式禁止使用 GitHub 发布器。安装后的 LaunchAgent 仍使用最小 `env -i` 环境；
Calendar 读取失败时本轮整体失败，不覆盖服务器上最后一组完整图片。

## 41 发布端

服务器额外提供两个受保护路由：

```text
/panel-calendar.png
/panel-calendar-right.png
```

服务启动时同时要求两张合法 PNG 和权限 `0600` 的 token 文件。缺失任一文件会拒绝
启用日程路由；请求缺少正确 Authorization header 时返回普通 404，不泄露该路由是否
存在。服务仍不记录客户端地址、请求 header 或事件标题。

## Kindle 配置

USB 可见 `update.conf` 只增加非敏感字段：

```text
UPDATE_URL_CALENDAR="https://EDGE_ENDPOINT/panel-calendar.png"
UPDATE_URL_CALENDAR_RIGHT="https://EDGE_ENDPOINT/panel-calendar-right.png"
DISPLAY_CONTENT_MODE=dashboard
```

身份 header 只能放在权限 `0600` 的：

```text
/var/local/bjtu-dashboard/curl.conf
```

特权更新器继续把 `update.conf` 当作严格白名单数据解析，不会 `source` 或 `eval`。
内容模式只接受 `dashboard|calendar`，方向只接受 `portrait|right`。ETag 只有在方向和
内容模式同时一致时才复用，避免跨页面收到错误的 `304`。

## 显示规则

- 使用固定 `Asia/Shanghai`（UTC+8）确定月份、日期和事件时间；
- 使用与 Apple 日历月视图相近的 7 列 × 6 行网格、星期栏和分段视图按钮；
- 当天日期使用黑色圆形标记，非本月日期使用浅灰背景与灰色文字；
- 全天事件使用深色圆角横条，定时事件使用浅灰横条并显示 `HH:MM`；
- 每个日期格会按可用空间限制显示数量，超出时显示 `+N`；
- 页面只显示月份、日期与事件，不显示 HPC 容量、节点或账户区；
- 中文标题使用 macOS CJK 字体，过长标题按像素宽度截断并加省略号；
- 竖屏仍由 Kindle 原生 hook 叠加 UTC+8 时间、电量；右转模式不叠加竖屏坐标文本。

## 失败行为

| 故障 | 结果 |
| --- | --- |
| Calendar 权限被拒绝或查询超时 | 本轮 Mac 同步失败，保留服务器旧图 |
| 事件字段异常 | 丢弃无效项或拒绝本轮，不写原始响应 |
| SSH 上传中断 | `.incoming` 被清理，旧图继续提供 |
| token 缺失、权限过宽或格式错误 | edge 拒绝启动日程路由 |
| Kindle 鉴权、TLS、PNG 校验失败 | 保留当前锁屏和 ETag 状态 |
| 用户解锁 | 取消后台替换/渲染，不重新锁屏 |

该功能不改变既有的 120/30 秒插电 grace、300 秒 ETag 检查或 3600 秒电池 RTC
策略。真实深度休眠期间 Wi-Fi 仍会断开；日程只在下一次正常联网窗口更新。
