"""Persist passive fresh publication evidence without changing a publication outcome."""
import contextlib
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import fb_upload as upload
import safe_video_comments as comments
import published_video_lookup as lookup

VERSION='1.0-frozen-job-passive-publication-evidence'


@contextlib.contextmanager
def installed(path,value):
    jobs={(j['account'],j['target']):j for j in value['payload']['jobs']}
    earliest=datetime.fromisoformat(value['created_at']).timestamp()-5
    state_path=upload.ROOT/'logs/publish_state.json'
    save=upload.save_json;original=comments.PublicationLinks;cache={};ambiguous={}
    def owned(row,job):
        try:
            return ((row.get('account'),row.get('target'))==(job['account'],job['target'])
                    and upload.target_key(row.get('url',''))==upload.target_key(job['url'])
                    and str(row.get('video','')).replace('\\','/').split('/')[-1]==job['filename']
                    and datetime.fromisoformat(row['created']).timestamp()>=earliest)
        except (KeyError,ValueError,TypeError):return False
    def stamp(document):
        for job in jobs.values():
            row=document.get(job['key'])
            if not isinstance(row,dict) or not owned(row,job):continue
            if row.get('source_frozen_manifest') not in {None,path.name}:continue
            row['source_frozen_manifest']=path.name
            row['source_frozen_sha256']=value['sha256']
            saved=cache.get(job['key'])
            if ambiguous.get(job['key'])==row['created']:
                for field in ('fresh_publication_candidate','fresh_publication_explicit_published','fresh_publication_job_key'):
                    row.pop(field,None)
                row['fresh_publication_candidate_count']=2
            elif saved and saved['created']==row['created'] and row.get('post_intent_at'):
                row.update(fresh_publication_candidate=saved['link'],fresh_publication_job_key=job['key'],
                           fresh_publication_explicit_published=saved['explicit'],fresh_publication_candidate_count=1)
    def persist(candidate,document):
        if Path(candidate)==state_path and isinstance(document,dict):stamp(document)
        return save(candidate,document)
    class Capture(original):
        def __init__(self,context,entry,caption,created):
            self.bound_job=jobs.get((entry.get('account'),entry.get('target')))
            self.bound_created=created
            self.bound_owner=upload.target_key(entry.get('url',''))
            super().__init__(context,entry,caption,created)
        def receive(self,response):
            super().receive(response)
            job=self.bound_job
            if not job or not self.armed or self.bound_owner!=upload.target_key(job['url']):return
            try:
                state=upload.read_json(state_path,{})
                row=state.get(job['key'],{})
                if (not owned(row,job) or row.get('created')!=self.bound_created or not row.get('post_intent_at')
                        or row.get('source_frozen_manifest')!=path.name):return
                links={comments.direct_link(link) for link in self.links};links.discard(None)
                if len(links)>1:
                    ambiguous[job['key']]=self.bound_created;cache.pop(job['key'],None)
                elif len(links)==1 and ambiguous.get(job['key'])!=self.bound_created:
                    link=next(iter(links));explicit=False
                    from urllib.parse import urlparse
                    parsed=urlparse(response.url)
                    if parsed.hostname in {'facebook.com','www.facebook.com'} and parsed.path.rstrip('/')=='/api/graphql':
                        raw=response.text()
                        if len(raw)<=4_000_000:
                            since=datetime.fromisoformat(row['post_intent_at']).timestamp()
                            import time
                            from actual_reels_comment_lookup import Evidence
                            for payload in lookup.payloads(raw):
                                if link not in comments.public_nodes(payload,self.owner,job['caption_text'],since):continue
                                evidence=Evidence(self.owner,job['caption_text'],since-5,time.time()+60,link)
                                evidence.add(payload)
                                if evidence.matched and evidence.published and not evidence.blocked:explicit=True
                    old=cache.get(job['key'],{})
                    cache[job['key']]=dict(created=self.bound_created,link=link,explicit=explicit or bool(old.get('explicit') and old.get('link')==link))
                else:return
                persist(state_path,state)
            except Exception:
                # Evidence collection must not interrupt the one allowed Post.
                pass
    with patch.object(comments,'PublicationLinks',Capture),patch.object(upload,'save_json',side_effect=persist):
        yield
