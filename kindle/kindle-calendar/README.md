# Standalone Calendar

这是一套完全在 Kindle 上运行的离线优先日历锁屏。Mac 只参与一次安装；安装后，Kindle
根据本机时钟计算公历、星期、农历和二十四节气，在本机生成 8 位灰度 PNG。

## 前提

- Kindle 已越狱并可通过 SSH 登录；
- 已安装 KUAL 和兼容的 Custom Screensaver/FBInk 运行时；
- 首次安装时确认真实 framebuffer 尺寸。

基础日历不需要 Wi-Fi、iCloud、Mac、服务器或个人订阅。程序内置当前年度中国法定
节假日快照；Wi-Fi 可用时，Kindle 自己每周尝试从 `holiday-cn` 的公开 HTTPS 数据更新
当前年和下一年。网络失败只会保留旧数据，不会阻止每日翻页。

## 行为

- 启动时立即生成一次月历；
- 默认每天 `00:05` 通过 RTC 唤醒并重绘今日标记；
- 公历、农历、节气均为设备内算法，不等待网络；
- 联网时最多每七天检查一次法定节假日数据；
- 节假日 JSON 必须通过年份、日期、数量、重复项和文本范围校验；
- 所有 PNG 和节假日缓存都通过同目录临时文件、`fsync` 和原子 rename 更新；
- 用户解锁会取消仍在运行的任务；未充电且低于 20% 电量时不安排新的 RTC；
- 不模拟电源键，也不要求 Wi-Fi 在深度睡眠期间保持连接。

若设备已经安装 `bjtu-native-screensaver`，离线日历会复用它的原生屏保资产和显示钩子，
避免两个钩子互相覆盖。启用离线日历会停用 `bjtu-dashboard-updater` 的调度服务；这是可逆
操作。若要回退，先在 KUAL 停用 `Offline Calendar`，再重新启用 Dashboard。

默认画布为 1072×1448、时区为 `Asia/Shanghai`。非 PW3 设备应按实际 framebuffer 修改
`calendar.conf`。该文件由 root 进程按严格白名单解析，不会被 shell source 或 eval。

`CALENDAR_MODE=ics` 仅作为以后需要个人订阅时的兼容模式；默认且推荐值为 `offline`。

## KUAL

KUAL → `Offline Calendar` 提供立即刷新、显示、自动更新启停、状态和匿名日志按钮。

## 一次性部署

```bash
python3 scripts/deploy_standalone_calendar.py KINDLE_SSH_ALIAS
```

部署器通过 SSH 识别设备 CPU 架构，并静态交叉编译 ARMv7 或 ARM64 Linux 二进制。完成后
Mac 不再参与日历更新。

第三方算法和数据的许可信息见 `THIRD_PARTY_NOTICES.md`。
