"""Surgical launcher cleanup patch; original browser flags and proxy remain."""
import ast,re

VERSION='1.0-preserve-primary-launch-errors-and-owned-handle-close'
MARKER="OWNED_CLEANUP_VERSION='1.0-owned-headless-process-cleanup'"
CLASS='''class NormalContext:
    def __init__(self,browser,context,account,process=None,run_mode=None):
        self._browser=browser;self._context=context;self._account=account;self._closed=False
        self._owned_process=process;self._run_mode=run_mode
    def __getattr__(self,name):return getattr(self._context,name)
    def close(self):
        if self._closed:return
        self._closed=True
        try:
            try:self._browser.new_browser_cdp_session().send('Browser.close')
            except Exception:pass
            try:self._browser.close()
            except Exception:pass
        finally:
            local_files.release(self._context)
            from owned_chrome_cleanup import finish_owned_process
            finish_owned_process(self._owned_process,self._run_mode,lambda:close_selected_window(self._account))
'''


def transform(source):
    tree=ast.parse(source)
    if MARKER in source:return source
    classes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NormalContext']
    launchers=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='launch_normal']
    if len(classes)!=1 or len(launchers)!=1:raise ValueError('原普通Chrome启动器结构不符，未覆盖。')
    function=ast.get_source_segment(source,launchers[0])
    if not all(text in function for text in ('--user-data-dir=','--remote-debugging-address=127.0.0.1','subprocess.Popen','run_mode=background.mode(upload.ROOT)')):raise ValueError('原浏览器或代理启动流程不同，保留原程序。')
    call='NormalContext(browser,context,account)'
    if function.count(call)!=1:raise ValueError('原Chrome上下文创建位置不唯一。')
    updated=function.replace(call,'NormalContext(browser,context,account,process=process,run_mode=run_mode)')
    previous='''    except BaseException:
        if wrapper is not None:wrapper.close()
        else:close_selected_window(account)
        raise'''
    replacement='''    except BaseException:
        import traceback
        from owned_chrome_cleanup import finish_owned_process,save_launch_error
        original=traceback.format_exc();cleanup_error=None
        try:
            if wrapper is not None:wrapper.close()
            else:finish_owned_process(process,run_mode,lambda:close_selected_window(account))
        except Exception as cleanup:
            cleanup_error=cleanup
        save_launch_error(upload.ROOT,account,original,cleanup_error)
        raise'''
    if updated.count(previous)!=1:raise ValueError('原启动异常处理结构不符，未猜测修改。')
    updated=updated.replace(previous,replacement)
    spans=[(classes[0].lineno,classes[0].end_lineno,CLASS),(launchers[0].lineno,launchers[0].end_lineno,updated)]
    lines=source.splitlines(keepends=True)
    for start,end,text in sorted(spans,reverse=True):lines[start-1:end]=[text+'\n']
    result=''.join(lines)+'\n'+MARKER+'\n'
    authorization='        except BaseException:context.close();raise'
    if result.count(authorization)!=1:raise ValueError('原文件授权异常处理位置不唯一。')
    result=result.replace(authorization,"""        except BaseException:
            import traceback
            from owned_chrome_cleanup import save_launch_error
            original=traceback.format_exc();cleanup_error=None
            try:context.close()
            except Exception as cleanup:cleanup_error=cleanup
            save_launch_error(upload.ROOT,entry['account'],original,cleanup_error)
            raise""")
    ast.parse(result)
    return result
