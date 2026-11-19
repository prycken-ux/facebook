# Reel公开范围提示：自动Close或Continue，然后核实Public

用户发现fb32/fb46/fb49/fb54/fb60/fb66/fb70的“Public/Friends未加载”由公开范围加载提示遮挡，并要求之后再出现时自动叉掉或点击Continue。随后用户明确昨天批次暂不再补发，此修正只服务今天及之后发布；不批量标记昨天成功。

安装器只修改原2.47核心ensure_personal_public_audience函数：保留原Public/Friends、radio Public、Done及Public保存核验，在这一环节加入辅助模块的有界提示处理。保留旧函数精确基线，未知核心修改拒绝覆盖；支持原CRLF/BOM。先核验无其他Python任务，再沿用原双锁，备份原核心/已有辅助模块；新进程特征校验失败时回滚。修正重复安装不重复写核心或建备份。安装入口不运行任何视频、补发、评论或登录检查，也不改配置、素材、账号名单或成功状态。

辅助模块只在唯一Reel settings编辑器/原文案框存在的公开范围步骤运行。已识别Review audience提示可选Continue，否则唯一Close；空白加载提示须没有输入框/其他操作，具有唯一Close且大小不似全屏编辑器。短暂等待自然加载后才处理；正常Playwright点击，不强制穿透、不用JS点击。只操作固定的实际按钮元素，防止界面重绘误定位为编辑器Close。操作后校验同一编辑器及原文案保留，再由原流程选择并确认Public。登录/安全验证、未知或重复提示不点Continue/Close，保留视频跳过。不会为提示重选视频或点击Post。

本地Chromium测试覆盖加载Close、Review audience Continue、自然加载不点、没有弹窗不点编辑器Close、未知/安全/Discard提示不点、有密码输入的空白框不点、多个提示不猜选、登录重定向停止、Public未保存仍拒绝；安装器测试覆盖备份/限定函数/旧视频状态配置保持/幂等、校验失败回滚、活动任务和未知核心拒绝、CRLF/BOM及Windows四层启动链；缓存/包范围及新进程校验通过。没有向Facebook发布。原根目录核心只在用户执行安装指令时更新。
