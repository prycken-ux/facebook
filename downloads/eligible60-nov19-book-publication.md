# 11月19日60条新素材后台发布及最终纠正评论

用户授权今天新分配60目标的视频及评论，确认全部实拍、AI标签关闭。跳过34个停用号（包括fb40、fb43），保留fb37、fb63。只读取eligible60本次正式导入及stage/distribution指纹，独立logs/eligible60-real-publication-request-20261119.json绑定来源、精确目标、内容修订和授权；不恢复11月18日已归档的62/78旧任务。

新内容独立publication_content_20261119.py，追加publication-content-v1并备份preferences/common_caption，历史修订及冻结保持。正文保留原句子、拼写、亚马逊商品B0GYJ55PH6的2C08551FB464224E2CDB58F74A72570A参数与Shopify首页。评论按用户最后纠正，使用同商品及B2F4D52E550EDAC7E6A92C0290F501F6参数；不使用撤回的另一ASIN/CA11275评论。只去除Markdown显示语法与转义，不另加旧文案或标签。复跑绑定固定内容SHA，不回退或覆盖后续修订。

先无窗口后台自动视频、明确发布前失败的有界安全补发，再原评论/补评，最后才提示本人检查。登录或卡住先跳过。已成功或已提交待核实不再上传；发送结果不明的评论只核对，不直接重复发。暂停名单支持扩大且不缩小；跨日、中断或重跑不重建原scope/grant/claims。保留requestfinished响应读取和诊断截图上限。

待核实视频也纳入评论定位：仅当前源needs_review+post_intent，验证key/账号/目标/URL/文件名、原冻结SHA、内容修订、时间与身份授权。可信唯一已发布元数据，或只读核对作者/原文案/发布时间唯一匹配的视频直链，才作为证据确认成功并进入原评论。找不到则lookup_pending，不假记成功或重传。原锁保护状态比较更新，保留已有sent或待核实评论状态。每次运行同一提交只查一次；最终人工处理后可再查一次。不依赖本地MP4存在，只有原内容及文案指纹一致才本地归档。旧批次不纳入。

运行时audience钩子包含已测试的加载Close/Review audience Continue处理，唯一Reel settings范围内操作，后续仍核对Public；未知、安全或重复弹窗不猜点，不关闭编辑器、不自行Post。不要求用户先运行旧单独安装器，也不永久改根目录核心。

缓存19个限定模块，活动任务存在时停止，不抢锁、不结束其他进程。测试覆盖60/34、最终新文案评论及AI关闭、历史保持、失败/评论安全重试、不明提交不重复、跨日/中断/人工最后、代次和篡改拒绝；另验证定位后通过评论门槛、无匹配/错源/暂停不发送、其他任务保持、无本地媒体可只读定位、唯一发布证据、同提交次数、已有不明评论verify_only，以及本地Chromium弹窗处理/作用域恢复。测试没有向Facebook发布。

## 本次纯文本

正文：
If this book speaks to you, you can find the same one from the video here.Get your copy here:https://www.amazon.com/gp/product/B0GYJ55PH6?maas=maas_adg_2C08551FB464224E2CDB58F74A72570A_afap_abs&ref_=aa_maas&tag=maas Shop on shopify: https://prycken.com/

评论：
Get your own copy here:https://www.amazon.com/gp/product/B0GYJ55PH6?maas=maas_adg_B2F4D52E550EDAC7E6A92C0290F501F6_afap_abs&ref_=aa_maas&tag=maas

内容SHA256：ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894
