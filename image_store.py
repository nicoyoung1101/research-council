"""Private, content-addressed user images. References never grant arbitrary file access."""
import base64
import hashlib
import os
from pathlib import Path
import re
import tempfile

MAX_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 4
ID = re.compile(r'^[a-f0-9]{64}\.(png|jpg|gif|webp)$')


def media(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png','png'
    if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg','jpg'
    if data[:6] in (b'GIF87a',b'GIF89a'):return 'image/gif','gif'
    if data[:4]==b'RIFF' and data[8:12]==b'WEBP':return 'image/webp','webp'
    raise ValueError('Use PNG, JPEG, GIF or WebP images')


class ImageStore:
    def __init__(self, directory):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)

    def put(self, body):
        encoded=body.get('data')
        if not isinstance(encoded,str) or len(encoded)>((MAX_BYTES+2)//3)*4:raise ValueError('Image exceeds 5 MB')
        try:data=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError) as exc:raise ValueError('Invalid image encoding') from exc
        if not data or len(data)>MAX_BYTES:raise ValueError('Image exceeds 5 MB')
        mime,ext=media(data)
        if body.get('mime')!=mime:raise ValueError('Image type does not match its contents')
        ident=hashlib.sha256(data).hexdigest()+'.'+ext
        path=self.directory/ident
        fd,temporary=tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(fd,'wb') as out:out.write(data)
            try:os.link(temporary,path)
            except FileExistsError:pass
        finally:os.unlink(temporary)
        return {'id':ident,'mime':mime,'size':len(data),'name':str(body.get('name') or 'Pasted image')[:160]}

    def get(self, ident):
        if not isinstance(ident,str) or not ID.fullmatch(ident):raise ValueError('Invalid image reference')
        path=self.directory/ident
        if path.is_symlink() or not path.is_file():raise ValueError('Image not found; import its image assets with the backup')
        data=path.read_bytes()
        mime,ext=media(data)
        if len(data)>MAX_BYTES or hashlib.sha256(data).hexdigest()+'.'+ext!=ident:raise ValueError('Invalid saved image')
        return {'id':ident,'mime':mime,'data':base64.b64encode(data).decode(),'path':str(path.resolve())}


def request_refs(request,agent):
    if request.get('kind') in ('title','tracking','scribe'):return []
    for key in ('initialInstructions','transcript','moderator'):
        if not isinstance(request.get(key,[]),list) or any(not isinstance(x,dict) for x in request.get(key,[])):raise ValueError('Invalid image message history')
    entries=[{'images':request.get('packet',{}).get('images',[])}]
    entries += [x for x in request.get('initialInstructions',[]) if x.get('to','all')=='all']
    # Independent answers never see peer messages or other agents' targeted images.
    if request.get('kind')!='independent':
        entries += [x for x in request.get('transcript',[]) if x.get('type')=='user' and x.get('to','all') in ('all',agent['id'])]
        entries += [x for x in request.get('moderator',[]) if x.get('to','all') in ('all',agent['id'],'context' if agent.get('role')=='context' else 'all')]
    entries += [{'images':request.get('images',[])}]
    ordered={}
    for entry in entries:
        rows=entry.get('images',[])
        if not isinstance(rows,list) or len(rows)>MAX_IMAGES:raise ValueError('At most 4 images per message')
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not ID.fullmatch(row['id']):raise ValueError('Invalid image reference')
            ordered.pop(row['id'],None);ordered[row['id']]=row
    return list(ordered.values())[-MAX_IMAGES:]


def claude_content(prompt,images):
    return ([{'type':'text','text':prompt}]+[{'type':'image','source':{'type':'base64','media_type':im['mime'],'data':im['data']}} for im in images]) if images else prompt
