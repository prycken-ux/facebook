# 后续新视频发布与评论

此更新只安装程序，不上传视频、不发送评论、不修改旧发布记录、旧评论记录或登录资料。

新批次使用 `publish_new_with_comments.py --date YYYY-MM-DD --real-footage`；日期必须是当前北京时间日期，`--real-footage` 表示用户已确认这一批全部实拍。不能用此开关代替询问尚未确认的新素材。安装不创建定时任务，也不会自动处理以后放入的新素材。

流程：只冻结没有任何发布记录的新视频，保留同名非空 TXT，否则用已保存的 common_caption_today.txt；包括 fb10 十个公共主页，排除 fb16/fb18/fb21。所有上传处理完之后，只给本清单里确认成功的视频发送批准的 Amazon 评论。发布确认最多等待三分钟，异常逐条跳过。

视频成功后归档并保存来自本次成功提示的直达链接（最多另等十秒），避免之后从个人主页猜视频。评论前核验身份和视频链接，发送意图先落盘；刷新原视频再次找到本人完整文案及相同 Amazon 参数才记录成功。Facebook 跳转包装、query 参数顺序及 Facebook 额外添加的 fbclid、fb_content_id、content_source=fb、channel_type=fb 不影响核验，缺少商家或跟踪参数、其他产品或其他作者均不算匹配。评论不确定时保留待核实，禁止重复发送；视频保持成功。

运行示例（仅在用户明确要求开始该批次并确认实拍后）：

```powershell
& 'E:\FB-AutoUpload\.venv\Scripts\python.exe' 'E:\FB-AutoUpload\publish_new_with_comments.py' --date 'YYYY-MM-DD' --real-footage --output-dir ([Environment]::GetFolderPath('Desktop'))
```

安装期间程序会检查任务锁、备份被更新的脚本、核对下载 SHA256 并清理这些脚本对应的字节码缓存。若有运行中的任务或无法确认的锁，安装拒绝继续，不删除锁。

已验证：本地 Chromium 合成页面测试覆盖新链接采集、精确作者与链接判断、刷新持久化、失败不重发、整批先上传后评论和旧任务隔离。Facebook 真实页面可能继续变化，完整生产链路仍需要下一条新视频实际验证；此前 fb06 的单条评论实际出现不代表批量链路已验证。不得改写该旧条的待核实状态。

实际结果包已确认：fb06 评论在刷新后仍显示；旧检测因 Facebook 增加上述四类来源参数漏判。已按其真实链接格式离线复测，仅更改未来检测逻辑，不改旧评论账本。
