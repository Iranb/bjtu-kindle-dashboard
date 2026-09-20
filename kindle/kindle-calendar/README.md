# Standalone Calendar

这是一套完全在 Kindle 上运行的只读日历锁屏服务。Mac 只参与一次安装；安装后，Kindle
直接通过 HTTPS 下载 ICS、解析日程与重复规则、生成 8 位灰度 PNG，并在锁屏时显示。

## 前提

- Kindle 已越狱并可通过 SSH 登录；
- 已安装 KUAL（管理按钮）和可用的 FBInk/自定义屏保运行时；
- Kindle 已连接可访问日历源的 Wi-Fi；
- 若使用 Apple 日历，需要单独开启某个 iCloud 日历的“公共日历”并复制链接。

“公共日历”是只读，但链接本身就是访问凭据。不要把链接放进 `calendar.conf`、Git、命令行
参数或日志。安装器通过 SSH stdin 把它写入 Kindle 的：

```text
/var/local/kindle-calendar/feed.url   mode 0600
```

## 行为

- 启动、Wi-Fi `connectionAvailable` 事件和每 30 秒健康检查都会判断是否到期；
- 默认每 15 分钟检查一次，使用 ETag 与 Last-Modified；
- 电池供电进入深度睡眠前会设置 RTC，默认每小时唤醒一次；
- RTC 唤醒后用 `abortSuspend` 留出联网窗口，不模拟电源键；
- 用户解锁会取消仍在运行的下载/渲染任务；
- HTTPS、ICS 结构或渲染失败时，保留上一张成功图片；
- ICS 缓存、HTTP 校验值和订阅地址都只保存在 root 私有目录；
- 日志不包含订阅 URL，也不记录日程标题。

默认画布为 1072×1448、时区为 `Asia/Shanghai`。不同型号应在安装前根据实际 framebuffer
尺寸修改 `calendar.conf`；该文件是严格白名单解析的数据文件，不会被 root shell source。

## KUAL

KUAL → `Standalone Calendar` 提供刷新、显示、启停、状态和匿名日志按钮。订阅地址不允许
通过 KUAL 或 USB 可见配置修改。

## 一次性部署

在 Mac 创建一个权限为 0600、只含一行 iCloud `webcal://` 或 `https://` 链接的临时文件，
然后运行：

```bash
python3 scripts/deploy_standalone_calendar.py KINDLE_SSH_ALIAS \
  --feed-url-file /path/to/private-feed-url.txt
```

部署器先通过 SSH 读取设备 CPU 架构，再静态交叉编译对应的 Linux 二进制。订阅地址只经
SSH stdin 传输；完成后应删除 Mac 上的临时文件。

