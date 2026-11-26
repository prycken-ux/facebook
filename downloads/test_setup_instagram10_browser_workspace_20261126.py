import copy,json,os,subprocess,tempfile,unittest
from pathlib import Path
import setup_instagram10_browser_workspace_20261126 as setup
from material_distribution_worker_check import win_args

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.root=self.base/'IG project with spaces';self.desktop=self.base/'Desktop';self.desktop.mkdir();self.chrome=self.base/'Chrome Application/chrome.exe';self.chrome.parent.mkdir();self.chrome.touch();self.writes=[]
    def writer(self,items,previous,check_only=False):
        self.writes.append((copy.deepcopy(items),check_only))
        for item in items:
            path=Path(item['path'])
            if path.exists() and json.loads(path.read_text())!=item and not any(old==json.loads(path.read_text()) for old in previous if old['path']==item['path']):raise ValueError('shortcut conflict')
        if not check_only:
            for item in items:Path(item['path']).write_text(json.dumps(item))
    def run_setup(self,writer=None):return setup.prepare(self.root,self.chrome,self.desktop,writer or self.writer)
    def test_ten_isolated_persistent_profiles_exact_media_entries_and_no_publishing(self):
        result=self.run_setup();self.assertEqual(result['account_count'],10);self.assertFalse(result['automatic_publication_started'])
        cfg=setup.read(self.root/setup.CONFIG);self.assertEqual([r['account'] for r in cfg['accounts']],list(setup.ACCOUNTS));self.assertEqual(cfg['accounts'][0]['expected_username'],'faithdjurner96')
        self.assertTrue(all(not r['publishing_enabled'] and not r['identity_verified'] for r in cfg['accounts']))
        items=self.writes[-1][0];self.assertEqual(len(items),22);browsers=[i for i in items if i['arguments']];self.assertEqual(len(browsers),10)
        profiles=[]
        for item in browsers:
            args=win_args(item['arguments']);profiles.append(next(a.split('=',1)[1] for a in args if a.startswith('--user-data-dir=')))
            self.assertIn('https://www.instagram.com/',args);self.assertNotIn('--incognito',args)
        self.assertEqual(set(profiles),{str(self.root/'profiles'/a) for a in setup.ACCOUNTS})
        for a in setup.ACCOUNTS:
            for folder in ('inbox','published','review','failed'):self.assertTrue((self.root/'videos'/a/folder).is_dir())
        self.assertTrue((self.desktop/'Instagram账号.lnk').is_file());self.assertTrue((self.desktop/'Instagram素材.lnk').is_file())
        self.assertEqual((self.root/'common_caption.txt').read_text(encoding='utf-8-sig').strip(),setup.CAPTION)
        self.assertEqual((self.root/'common_comment.txt').read_text(encoding='utf-8-sig').strip(),setup.COMMENT)
    def test_rerun_preserves_login_data_videos_mappings_and_custom_text(self):
        self.run_setup();cookie=self.root/'profiles/ins02/Default/Cookies';cookie.parent.mkdir();cookie.write_bytes(b'original login data')
        media=self.root/'videos/ins02/inbox/original.mp4';media.write_bytes(b'original video')
        config=setup.read(self.root/setup.CONFIG);config['accounts'][1].update(expected_username='actual_account_2',identity_verified=True,publishing_enabled=True);setup.atomic(self.root/setup.CONFIG,config)
        (self.root/'common_caption.txt').write_text('user changed caption');(self.root/'accounts_to_register.csv').write_text('user mappings')
        before={str(p):p.read_bytes() for p in [cookie,media,self.root/setup.CONFIG,self.root/'common_caption.txt',self.root/'accounts_to_register.csv',self.root/setup.OWNER]}
        self.run_setup();self.assertEqual({path:Path(path).read_bytes() for path in before},before)
    def test_unregistered_nonempty_profile_is_not_adopted(self):
        cookie=self.root/'profiles/ins01/Default/Cookies';cookie.parent.mkdir(parents=True);cookie.write_bytes(b'unknown login')
        with self.assertRaisesRegex(ValueError,'未登记浏览器'):self.run_setup()
        self.assertEqual(cookie.read_bytes(),b'unknown login');self.assertFalse((self.root/setup.OWNER).exists());self.assertFalse(self.writes)
    def test_foreign_fb_root_and_linked_media_directory_are_preserved(self):
        self.root.mkdir();fb=self.root/'upload_config.json';fb.write_text('original FB config')
        with self.assertRaisesRegex(ValueError,'独立IG目录'):self.run_setup()
        self.assertEqual(fb.read_text(),'original FB config');fb.unlink()
        outside=self.base/'FB videos';outside.mkdir();sentinel=outside/'keep.mp4';sentinel.write_bytes(b'keep')
        (self.root/'videos').symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'包含链接'):self.run_setup()
        self.assertEqual(sentinel.read_bytes(),b'keep');self.assertFalse((self.root/setup.OWNER).exists())
    def test_shortcut_conflict_is_detected_before_workspace_registration(self):
        path=self.desktop/'Instagram账号.lnk';path.write_text(json.dumps(dict(path=str(path),target='foreign workspace',arguments='')));before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'shortcut conflict'):self.run_setup()
        self.assertEqual(path.read_bytes(),before);self.assertFalse((self.root/setup.OWNER).exists())
    def test_partial_setup_resumes_without_replacing_profile_data(self):
        def failing(items,previous,check_only=False):
            if check_only:return self.writer(items,previous,True)
            self.writer(items[:1],previous,False);raise RuntimeError('simulated shortcut write failure')
        with self.assertRaisesRegex(RuntimeError,'simulated'):self.run_setup(failing)
        cookie=self.root/'profiles/ins01/saved-login';cookie.write_bytes(b'preserve partial setup')
        self.run_setup();self.assertEqual(cookie.read_bytes(),b'preserve partial setup');self.assertEqual(len(list((self.root/'shortcuts').glob('*.lnk'))),20)

PWSH=Path('/workspace/.tools/fb-pwsh/pwsh')
@unittest.skipUnless(PWSH.exists(),'PowerShell syntax parser required')
class PowerShellSyntaxTests(unittest.TestCase):
    def test_shortcut_script_parses_as_powershell_without_running_com_or_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'shortcuts.ps1';source.write_text(setup.SHORTCUT_SCRIPT,encoding='utf-8-sig');h=root/'parse.ps1';h.write_text("$tokens=$null;$errors=$null;[Management.Automation.Language.Parser]::ParseFile($env:TEST_SOURCE,[ref]$tokens,[ref]$errors) | Out-Null;if($errors.Count){throw ($errors | Out-String)};'parsed'")
            env=dict(os.environ,TEST_SOURCE=str(source),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            r=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(h)],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(r.returncode,0,r.stderr);self.assertIn('parsed',r.stdout)

if __name__=='__main__':unittest.main()
