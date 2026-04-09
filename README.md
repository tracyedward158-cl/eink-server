# 墨水屏 × Claude

> 在 Claude 对话框里说"发到墨水屏"，内容自动显示到你的电子墨水屏上。

## 工作原理

```
Claude 对话  ──POST──▶  服务器  ──SSE──▶  网页  ──BLE──▶  墨水屏
                     (Render)         (Chrome)        (EPD)
```

## 功能

- **SSE 实时推送** — Claude 发送后瞬间到达，无需轮询
- **Web Bluetooth** — 手机浏览器直连墨水屏，无需 App
- **Canvas 预览** — 推送前可预览实际显示效果
- **三色支持** — 黑白红三色墨水屏
- **图片上传** — Floyd-Steinberg 抖动算法
- **推送历史** — 保留最近 50 条记录
- **密钥保护** — 防止他人推送
- **PWA** — 可添加到手机桌面

## 快速开始

1. 部署到 Render（免费）
2. 绑定你的域名
3. 手机 Chrome 打开网页，蓝牙连接墨水屏
4. 在 Claude 对话中使用对话模板
5. 说"发到墨水屏"

详见 `部署指南.md`

## 硬件要求

搭载 nRF5x 芯片的电子价签，刷入 [EPD-nRF5](https://github.com/tsl0922/EPD-nRF5) 固件。

## 致谢

- [EPD-nRF5](https://github.com/tsl0922/EPD-nRF5) — 墨水屏固件
- [eink-ble-writer](https://github.com/0xblewalker/eink-ble-writer) — BLE 协议参考
