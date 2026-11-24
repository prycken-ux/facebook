import os,subprocess,tempfile,unittest
from pathlib import Path

class DirectEntryTests(unittest.TestCase):
    def test_detached_entry_resolves_original_project_before_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project';root.mkdir();(root/'logs').mkdir()
            cache=Path(tmp)/'cache';cache.mkdir()
            source=Path(__file__).parent
            for name in ['publication_target_watchdog_20261124.py','publication_file_state_20261124.py','comment_deadline_windows_job_20261124.py']:(cache/name).write_bytes((source/name).read_bytes())
            # Exactly the missing dependency: present in the original project,
            # absent from the cache and the interpreter's normal import path.
            (root/'chrome_profile_guard.py').write_text('BOOTSTRAP_SENTINEL=True\n')
            env=dict(os.environ,FB_NOV24_RUN='a'*32,FB_NOV24_ROLE='supervisor');env.pop('PYTHONPATH',None)
            p=subprocess.run([__import__('sys').executable,'-I',str(cache/'publication_target_watchdog_20261124.py'),str(root)],env=env,cwd=tmp,capture_output=True,text=True)
            self.assertEqual(p.returncode,1)
            log=(root/'logs'/('nov24-launch-'+('a'*32)+'.log')).read_text()
            self.assertNotIn('ModuleNotFoundError',log);self.assertIn('Windows',log)
    def test_early_import_error_is_logged_before_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'logs').mkdir();cache=root/'cache';cache.mkdir()
            (cache/'publication_target_watchdog_20261124.py').write_bytes(Path(__file__).with_name('publication_target_watchdog_20261124.py').read_bytes())
            env=dict(os.environ,FB_NOV24_RUN='b'*32);env.pop('PYTHONPATH',None)
            p=subprocess.run([__import__('sys').executable,'-I',str(cache/'publication_target_watchdog_20261124.py'),str(root)],env=env,cwd=tmp,capture_output=True,text=True)
            self.assertEqual(p.returncode,1)
            log=(root/'logs'/('nov24-launch-'+('b'*32)+'.log')).read_text();self.assertIn('publication_file_state',log)

if __name__=='__main__':unittest.main()
