"""Set authorized local file paths through public CDP, without file-byte transfer."""
import uuid
from datetime import date as CalendarDate
from pathlib import Path
import fb_upload as upload
import scheduled_material_batch as batch

VERSION='1.0-verified-local-file-paths'
BATCH_DATE_VERSION='1.0-frozen-batch-date-binding'
_CONTEXTS={}
_ORIGINALS={}


def _context_for(handle):
    frame=handle.owner_frame()
    if frame is None:raise RuntimeError('文件输入框已脱离页面，未选择其他位置')
    return frame,frame.page.context


def _source(metadata,files):
    values=[files] if isinstance(files,(str,Path)) else list(files) if isinstance(files,(list,tuple)) else []
    if len(values)!=1 or not isinstance(values[0],(str,Path)):raise ValueError('本批只允许选择一个确切原视频路径')
    path=Path(values[0]).resolve();path.relative_to(upload.ROOT.resolve())
    matches=[j for j in metadata['jobs'] if (upload.ROOT/'videos'/j['account']/j['target']/'inbox'/j['filename']).resolve()==path]
    if len(matches)!=1:raise ValueError('文件路径不属于当前账号的原视频清单')
    job=matches[0];entry=batch.validate_job(job,date=metadata.get('date'))
    if (entry['account'],entry['target'])!=metadata['pair'] or upload.target_key(entry['url'])!=metadata['owner']:
        raise ValueError('文件原任务与浏览器身份目标不一致')
    if path.stat().st_size!=job.get('video_size',path.stat().st_size):raise ValueError('原视频大小发生变化')
    return path


def _set(handle,files):
    frame,context=_context_for(handle);metadata=_CONTEXTS.get(id(context))
    if metadata is None:raise RuntimeError('浏览器不是本批已核验的本机Chrome')
    path=_source(metadata,files);marker='data-verified-local-file-input';token=uuid.uuid4().hex
    handle.evaluate('''(e,p)=>{if(e.tagName!=='INPUT'||e.type!=='file')throw Error('Not a file input');e.setAttribute(p.marker,p.token)}''',dict(marker=marker,token=token))
    session=None;search=None
    try:
        session=context.new_cdp_session(frame)
        root=session.send('DOM.getDocument',dict(depth=0,pierce=True))['root']['nodeId']
        selector='input['+marker+'="'+token+'"]'
        nodes=session.send('DOM.querySelectorAll',dict(nodeId=root,selector=selector))['nodeIds']
        if not nodes:
            found=session.send('DOM.performSearch',dict(query=selector,includeUserAgentShadowDOM=True));search=found['searchId']
            if found['resultCount']==1:nodes=session.send('DOM.getSearchResults',dict(searchId=search,fromIndex=0,toIndex=1))['nodeIds']
        if len(nodes)!=1:raise RuntimeError('未定位到唯一的原文件输入框，未猜选其他上传位置')
        # The owned local Chrome reads this exact absolute path itself. No
        # FilePayload/buffer crosses Playwright's remote-file transfer channel.
        session.send('DOM.setFileInputFiles',dict(nodeId=nodes[0],files=[str(path)]))
        print('已通过本机路径选择原视频：',path.name,'；大小',round(path.stat().st_size/1024/1024,1),'MB。',flush=True)
    finally:
        if session is not None:
            if search is not None:
                try:session.send('DOM.discardSearchResults',dict(searchId=search))
                except Exception:pass
            try:session.detach()
            except Exception:pass
        try:handle.evaluate('(e,p)=>{if(e.getAttribute(p.marker)===p.token)e.removeAttribute(p.marker)}',dict(marker=marker,token=token))
        except Exception:pass  # React may remove the consumed input after change.


def _locator(self,files,**kwargs):
    if id(self.page.context) not in _CONTEXTS:return _ORIGINALS['locator'](self,files,**kwargs)
    handle=self.element_handle(timeout=kwargs.get('timeout'))
    if handle is None:raise RuntimeError('原文件输入框尚未出现，未猜选其他位置')
    return _set(handle,files)


def _element(self,files,**kwargs):
    frame,context=_context_for(self)
    if id(context) not in _CONTEXTS:return _ORIGINALS['element'](self,files,**kwargs)
    return _set(self,files)


def _chooser(self,files,**kwargs):
    if id(self.page.context) not in _CONTEXTS:return _ORIGINALS['chooser'](self,files,**kwargs)
    return _set(self.element,files)


def authorize(context,entry,jobs,date=None):
    from playwright.sync_api import Locator,ElementHandle,FileChooser
    pair=entry['account'],entry['target'];owner=upload.target_key(entry['url'])
    selected=[j for j in jobs if (j['account'],j['target'])==pair and upload.target_key(j['url'])==owner]
    if not selected:raise ValueError('本机文件选择没有绑定本批原目标')
    if date is not None:
        if not isinstance(date,str):raise ValueError('本机文件选择的冻结批次日期必须是文字')
        CalendarDate.fromisoformat(date)
    elif any('publication_content_sha256' in job for job in selected):
        raise ValueError('本机文件选择缺少冻结批次日期，未跳过正文版本校验')
    if not _CONTEXTS:
        _ORIGINALS.update(locator=Locator.set_input_files,element=ElementHandle.set_input_files,chooser=FileChooser.set_files)
        Locator.set_input_files=_locator;ElementHandle.set_input_files=_element;FileChooser.set_files=_chooser
    _CONTEXTS[id(context)]=dict(context=context,pair=pair,owner=owner,jobs=selected,date=date)


def release(context):
    from playwright.sync_api import Locator,ElementHandle,FileChooser
    _CONTEXTS.pop(id(context),None)
    if not _CONTEXTS and _ORIGINALS:
        Locator.set_input_files=_ORIGINALS['locator'];ElementHandle.set_input_files=_ORIGINALS['element'];FileChooser.set_files=_ORIGINALS['chooser']
        _ORIGINALS.clear()


def self_check(context,job):
    """Check the real original file on Windows before any publication grant."""
    path=upload.ROOT/'videos'/job['account']/job['target']/'inbox'/job['filename']
    size=path.stat().st_size
    with path.open('rb') as f:
        first=f.read(4096);f.seek(max(0,size-4096));last=f.read(4096)
    expected=dict(name=path.name,size=size,first=list(first),last=list(last))
    page=context.new_page()
    def verify():
        observed=page.evaluate('''async()=>{const f=document.querySelector('input').files[0];return {name:f.name,size:f.size,first:Array.from(new Uint8Array(await f.slice(0,4096).arrayBuffer())),last:Array.from(new Uint8Array(await f.slice(Math.max(0,f.size-4096)).arrayBuffer()))}}''')
        if observed!=expected:raise RuntimeError('本机选文件自检未通过，原视频未正确进入浏览器，尚未启动补发')
    try:
        page.goto('about:blank',wait_until='domcontentloaded')
        page.set_content('<input id="file" type="file"><button id="pick" onclick="document.getElementById(\'file\').click()">Choose original file</button>')
        page.locator('input').set_input_files(str(path.resolve()),timeout=20000);verify()
        with page.expect_file_chooser(timeout=10000) as choice:page.locator('button').click()
        choice.value.set_files(str(path.resolve()),timeout=20000);verify()
        print('本机大文件选取自检通过：',path.name,round(size/1024/1024,1),'MB；上传框和文件选择窗口均通过。',flush=True)
    finally:
        page.close()
