"""Regression for the actual Windows venv redirector's retained four-process tree."""
import copy,contextlib,io,json,subprocess,unittest
from unittest.mock import patch
import finish_first24_nov14_on_nov16 as app


class VenvProcessChainTests(unittest.TestCase):
    def setUp(self):
        self.root=r'E:\FB-AutoUpload';self.exe=self.root+r'\.venv\Scripts\python.exe'
        self.runtime=r'C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe'
        self.runner=self.root+r'\material-staging\tools\abc123\finish_first24_nov14_on_nov16.py'
        self.body=("import hashlib,ssl,sys,urllib.request;c=ssl.create_default_context();c.minimum_version=ssl.TLSVersion.TLSv1_2;"
                   "b=urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/"+'a'*40+
                   "/downloads/start_finish_first24_nov16.py',context=c,timeout=30).read(131073);hashlib.sha256(b).hexdigest()=='"+'b'*64+
                   "' or sys.exit('Checksum mismatch; stopped');exec(compile(b,'verified-nov16-first24-and-nov14-stage','exec'))")
        self.run_args=['-u',self.runner,self.root];self.boot_args=['-u','-c',self.body,self.root]
        self.rows=[self.row(100,99,self.run_args,runtime=True),self.row(99,98,self.run_args),
                   self.row(98,97,self.boot_args,runtime=True),self.row(97,96,self.boot_args)]
    def row(self,pid,parent,args,runtime=False):
        return dict(pid=pid,parent=parent,name='python.exe',exe=self.runtime if runtime else self.exe,
                    command=subprocess.list2cmdline([self.exe]+args),created='2026-11-16T02:00:'+f'{pid-90:02d}'+'.1234567Z')
    def classify(self,rows=None):return app.classify_workers(self.rows if rows is None else rows,self.root,100,self.runner)
    def test_four_layers_self_bootstrap_and_both_venv_redirectors_are_one_own_launch(self):
        workers,allowed=self.classify();self.assertEqual(workers,[]);self.assertEqual(allowed,[97,98,99,100])
    def test_direct_runtime_parent_without_venv_stubs_also_supported(self):
        rows=copy.deepcopy([self.rows[0],self.rows[2]]);rows[0]['parent']=98
        workers,allowed=self.classify(rows);self.assertEqual(workers,[]);self.assertEqual(allowed,[98,100])
    def test_an_identical_second_launch_is_still_a_blocker(self):
        rows=self.rows+[self.row(101,1,self.run_args,runtime=True),self.row(102,1,self.boot_args)]
        workers,allowed=self.classify(rows);self.assertEqual({r['pid'] for r in workers},{101,102});self.assertEqual(len(allowed),4)
    def test_real_old_publisher_in_parent_chain_is_not_exempted(self):
        rows=self.rows+[self.row(96,1,['-u',self.root+r'\publish_unplanned_fortysix_nov14.py',self.root])]
        workers,allowed=self.classify(rows);self.assertEqual([r['pid'] for r in workers],[96]);self.assertNotIn(96,allowed)
    def test_matching_marker_inside_other_code_cannot_exempt_a_publisher(self):
        rows=copy.deepcopy(self.rows)
        for r in rows[2:]:r['command']=subprocess.list2cmdline([self.exe,'-u','-c',self.body+';run_other_publisher()',self.root])
        workers,allowed=self.classify(rows);self.assertEqual(allowed,[99,100]);self.assertEqual({r['pid'] for r in workers},{97,98})
    def test_untrusted_host_or_missing_checksum_does_not_exempt_ancestor(self):
        for body in [self.body.replace('prycken-ux/facebook','somebody/else'),self.body.replace('hashlib.sha256(b).hexdigest()',"str('skip')")]:
            rows=copy.deepcopy(self.rows)
            for r in rows[2:]:r['command']=subprocess.list2cmdline([self.exe,'-u','-c',body,self.root])
            workers,allowed=self.classify(rows);self.assertEqual(allowed,[99,100]);self.assertEqual(len(workers),2)
    def test_recycled_parent_pid_is_not_exempted(self):
        rows=copy.deepcopy(self.rows);rows[1]['created']='2026-11-16T03:00:00Z'
        workers,allowed=self.classify(rows);self.assertEqual(allowed,[100]);self.assertEqual({r['pid'] for r in workers},{97,98,99})
    def test_unknown_venv_process_blocks_without_disclosing_its_code(self):
        secret='sample-private-value-never-print'
        rows=self.rows+[self.row(101,1,['-c',secret])]
        workers,allowed=self.classify(rows);self.assertEqual([r['pid'] for r in workers],[101]);self.assertNotIn(secret,json.dumps(workers))
    def test_uninspectable_or_ambiguous_process_snapshot_refuses(self):
        for rows in [self.rows[1:],self.rows+[copy.deepcopy(self.rows[0])],self.rows+[dict(pid=101,parent=1,name='python.exe',exe='',command='',created=None)]]:
            with self.assertRaises(ValueError):self.classify(rows)
    def test_crt_argument_decoding_matches_python_windows_quoting(self):
        samples=[['python.exe','-c','print("hello")',r'E:\with space\folder'],
                 ['python.exe','','a b','ends with space\\',"single'quote",'中文文件夹'],
                 ['python.exe',r'a\\\"b','plain',r'\\server\share\path'],[self.exe]+self.boot_args]
        for args in samples:self.assertEqual(app.win_args(subprocess.list2cmdline(args)),args)
    def test_query_error_stops_and_private_command_lines_are_never_printed(self):
        data=self.rows+[self.row(101,1,['-c','private-value'])]
        completed=subprocess.CompletedProcess([],0,json.dumps(data).encode(),b'')
        out=io.StringIO()
        with patch.object(app.sys,'platform','win32'),patch.object(app.os,'getpid',return_value=100),patch.object(app,'__file__',self.runner), \
             patch.object(app.subprocess,'run',return_value=completed),patch.object(app,'classify_workers',side_effect=lambda rows,root,pid:app_classify(rows,root,pid,self.runner)),contextlib.redirect_stdout(out):
            workers=app.active_workers(self.root)
        self.assertEqual([r['pid'] for r in workers],[101]);self.assertNotIn('private-value',out.getvalue());self.assertNotIn('urlopen',out.getvalue())
        with patch.object(app.sys,'platform','win32'),patch.object(app.subprocess,'run',return_value=subprocess.CompletedProcess([],1,b'',b'private failure')):
            with self.assertRaisesRegex(RuntimeError,'尚未导入或发布'):app.active_workers(self.root)


app_classify=app.classify_workers
if __name__=='__main__':unittest.main()
