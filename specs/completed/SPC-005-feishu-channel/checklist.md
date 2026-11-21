# Checklist

- [x] `backend/app/channels/base.py` 定义 `IncomingMessage`、`MessageHandler`、`Channel` 抽象，与 Spec 中渠道抽象一致
- [x] `backend/app/channels/router.py` 实现按渠道名的处理器路由表，`dispatch` 能正确分发，未注册渠道报错
- [x] `ChannelRouter.start_all()` 在后台守护线程启动全部渠道，单渠道异常不影响其他渠道与 HTTP 服务
- [x] `backend/app/channels/feishu.py` 使用 `lark_oapi` 长连接订阅 `im.message.receive_v1`，未依赖公网回调接口
- [x] 飞书文本消息解析正确，@ 提及占位符被剥离，空文本与非文本消息被忽略
- [x] 回复通过 `im.v1.message.reply` 以纯文本消息完成
- [x] 渠道内使用队列 + 单个后台工作线程串行处理，不阻塞长连接事件循环
- [x] 新增 `t_im_identities` 映射表，`(channel, sender_id)` 唯一，启动时自动建表
- [x] 飞书用户首次消息自动创建 `t_users`（`user_id=feishu_{open_id}`、随机密码哈希、`state=1`）与映射记录，后续消息通过映射复用
- [x] 对话线程按 `{channel}_{chat_id}_{sender_id}` 隔离，不同渠道与群聊中不同用户互不串扰
- [x] IM 渠道在进程内直接调用 Agent 与记忆服务，不请求 HTTP 接口、不生成 JWT，未登录 Web 的用户可正常使用
- [x] Web 端接口鉴权逻辑未被修改或绕过
- [x] Agent 输入按"摘要 + 最近 3 轮 + 当前消息"构建，回复后持久化对话并更新摘要
- [x] 触发 `final_recommendation_tool` 中断时，回复推荐内容并追加"该推荐需人工确认，请登录 Web 端完成确认"
- [x] `config.py` 增加 `FEISHU_ENABLED`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`，默认关闭且不影响现有功能
- [x] `backend/.env.example` 与 `backend/requirements.txt` 已同步飞书配置与 `lark-oapi` 依赖
- [x] 后端启动时按配置构建路由、注册并启动渠道，缺配置或连接失败不影响 HTTP 服务启动
- [x] 已通过占位凭据验证渠道启动与异常隔离、通过进程内模拟 IM 消息验证身份落库与两轮记忆；真实飞书私聊/群聊收发需用户用自己的应用凭据启用后实测
