"""Windows process containment: assign a suspended child before any code runs."""
import ctypes,os,subprocess,time

class WindowsJobChild:
    def __init__(self,args,environment,cwd,output):
        import _winapi,msvcrt
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.handle=None;self.process=None;self.pid=None
        pointer=ctypes.c_void_p;u32=ctypes.c_uint32;u64=ctypes.c_uint64;size=ctypes.c_size_t
        class Basic(ctypes.Structure):
            _fields_=[('ProcessTime',ctypes.c_int64),('JobTime',ctypes.c_int64),('Flags',u32),('Minimum',size),('Maximum',size),('ActiveLimit',u32),('Affinity',size),('Priority',u32),('Scheduling',u32)]
        class Counters(ctypes.Structure):
            _fields_=[(name,u64) for name in ('ReadOps','WriteOps','OtherOps','ReadBytes','WriteBytes','OtherBytes')]
        class Extended(ctypes.Structure):
            _fields_=[('Basic',Basic),('IO',Counters),('ProcessMemory',size),('JobMemory',size),('PeakProcess',size),('PeakJob',size)]
        class Accounting(ctypes.Structure):
            _fields_=[(name,ctypes.c_int64) for name in ('User','Kernel','PeriodUser','PeriodKernel')]+[(name,u32) for name in ('Faults','Total','Active','Terminated')]
        self.Accounting=Accounting
        signatures={'CreateJobObjectW':([pointer,ctypes.c_wchar_p],pointer),'SetInformationJobObject':([pointer,ctypes.c_int,pointer,u32],ctypes.c_int),'AssignProcessToJobObject':([pointer,pointer],ctypes.c_int),'ResumeThread':([pointer],u32),'CloseHandle':([pointer],ctypes.c_int),'TerminateJobObject':([pointer,u32],ctypes.c_int),'TerminateProcess':([pointer,u32],ctypes.c_int),'GetExitCodeProcess':([pointer,ctypes.POINTER(u32)],ctypes.c_int),'QueryInformationJobObject':([pointer,ctypes.c_int,pointer,u32,pointer],ctypes.c_int)}
        for name,(argspec,result) in signatures.items():
            function=getattr(self.api,name);function.argtypes=argspec;function.restype=result
        self.handle=self.api.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=Extended();limits.Basic.Flags=0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        thread=None
        try:
            if not self.api.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):raise ctypes.WinError(ctypes.get_last_error())
            with open(os.devnull,'rb') as null:
                handles=[msvcrt.get_osfhandle(null.fileno()),msvcrt.get_osfhandle(output.fileno())]
                startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESTDHANDLES
                startup.hStdInput=handles[0];startup.hStdOutput=startup.hStdError=handles[1]
                startup.lpAttributeList={'handle_list':handles}
                previous=[os.get_handle_inheritable(h) for h in handles]
                try:
                    for h in handles:os.set_handle_inheritable(h,True)
                    # CREATE_SUSPENDED prevents a venv launcher creating an uncontained
                    # base-Python descendant before job assignment.
                    process,thread,self.pid,_=_winapi.CreateProcess(None,subprocess.list2cmdline(args),None,None,True,0x08000204,environment,str(cwd),startup)
                    self.process=process
                finally:
                    for h,old in zip(handles,previous):os.set_handle_inheritable(h,old)
            if not self.api.AssignProcessToJobObject(self.handle,self.process):raise ctypes.WinError(ctypes.get_last_error())
            if self.api.ResumeThread(thread)==0xffffffff:raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            if self.process:self.api.TerminateProcess(self.process,1)
            self.close();raise
        finally:
            if thread:self.api.CloseHandle(thread)

    def poll(self):
        code=ctypes.c_uint32()
        if not self.api.GetExitCodeProcess(self.process,ctypes.byref(code)):raise ctypes.WinError(ctypes.get_last_error())
        return None if code.value==259 else code.value

    def stop(self):
        if not self.api.TerminateJobObject(self.handle,1460):raise ctypes.WinError(ctypes.get_last_error())
        end=time.monotonic()+10
        while True:
            info=self.Accounting()
            if not self.api.QueryInformationJobObject(self.handle,1,ctypes.byref(info),ctypes.sizeof(info),None):raise ctypes.WinError(ctypes.get_last_error())
            if not info.Active:return
            if time.monotonic()>=end:raise RuntimeError('本条子进程尚未全部退出，未并发启动下一条。')
            time.sleep(.1)

    def close(self):
        if self.handle:self.api.CloseHandle(self.handle);self.handle=None
        if self.process:self.api.CloseHandle(self.process);self.process=None
