"""Explicit user feedback only. No research state, credentials, logs or file paths are collected."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import plistlib
import re
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request
import uuid
import zipfile
from image_store import media

ROOT = Path(__file__).resolve().parent
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGES = 2
EMAIL = re.compile(r'^[^\s@,;<>\r\n]+@[^\s@,;<>\r\n]+\.[^\s@,;<>\r\n]+$')


def validate_config(raw):
    if not isinstance(raw, dict): raise ValueError('Invalid feedback configuration')
    email, endpoint = raw.get('email', ''), raw.get('endpoint', '')
    if not isinstance(email, str) or len(email) > 254 or email and not EMAIL.fullmatch(email):
        raise ValueError('Use one valid feedback email address')
    if not isinstance(endpoint, str) or len(endpoint) > 2000: raise ValueError('Invalid feedback endpoint')
    if endpoint:
        url = urlsplit(endpoint)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError('Feedback endpoint must be HTTPS without credentials or fragment')
    return dict(email=email, endpoint=endpoint)


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False);out.flush();os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def deliver(endpoint, report):
    request = urllib.request.Request(endpoint, data=json.dumps(report, ensure_ascii=False).encode(),
        headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Idempotency-Key': report['id']}, method='POST')
    with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
        if not 200 <= response.status < 300: raise ValueError('No acknowledgement')
        raw = response.read(4096)
        try: ack = json.loads(raw)
        except (ValueError, UnicodeDecodeError): ack = None
        if isinstance(ack, dict) and (ack.get('success') is False or ack.get('ok') is False):
            raise ValueError('Receiver rejected feedback')


class FeedbackStore:
    def __init__(self, data_dir, sender=None, bundled_config=None):
        self.data_dir = Path(data_dir)
        self.directory = self.data_dir/'feedback'
        self.bundled_config = Path(bundled_config or ROOT/'feedback-config.json')
        self.sender = sender or deliver
        self.lock = threading.RLock()
        self.active = set()

    def config(self):
        raw = {}
        for file in [self.bundled_config, self.data_dir/'feedback-config.json']:
            if file.exists(): raw.update(json.loads(file.read_text()))
        return validate_config(raw)

    def public_config(self):
        error = False
        try: config = self.config()
        except (ValueError, OSError): config = dict(email='', endpoint='');error = True
        build = 'dev'
        info = ROOT.parents[1]/'Info.plist'
        if info.is_file():
            try: build = str(plistlib.loads(info.read_bytes()).get('CFBundleVersion', 'dev'))
            except (OSError, ValueError): pass
        return dict(method='direct' if config['endpoint'] else 'email' if config['email'] else 'local',
                    email=config['email'], destination=urlsplit(config['endpoint']).hostname or config['email'],
                    configurationError=error, appVersion='0.11', build=build)

    def path(self, ident):
        if not isinstance(ident, str) or str(uuid.UUID(ident)) != ident: raise ValueError('Invalid feedback ID')
        path = self.directory/(ident+'.json')
        if path.is_symlink(): raise ValueError('Invalid feedback record')
        return path

    def get(self, ident):
        return json.loads(self.path(ident).read_text())

    def public(self, report):
        return {k: report[k] for k in ('id', 'created', 'status', 'category', 'message', 'contact', 'language', 'deliveryError') if k in report} | {'imageCount': len(report['images'])}

    def list(self):
        result = []
        for path in sorted(self.directory.glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True)[:30]:
            try: result.append(self.public(self.get(path.stem)))
            except (ValueError, OSError, KeyError): continue
        return result

    def validate(self, body):
        if not isinstance(body, dict): raise ValueError('Invalid feedback')
        ident = body.get('id');self.path(ident)
        message, contact = body.get('message', ''), body.get('contact', '')
        if not isinstance(message, str) or not 2 <= len(message.strip()) <= 5000: raise ValueError('Write 2–5000 characters')
        if not isinstance(contact, str) or len(contact) > 254 or contact and not EMAIL.fullmatch(contact): raise ValueError('Invalid reply email')
        if body.get('category', 'other') not in ('bug', 'idea', 'other'): raise ValueError('Invalid category')
        if body.get('language', 'en') not in ('zh', 'ja', 'en'): raise ValueError('Invalid language')
        images = body.get('images', [])
        if not isinstance(images, list) or len(images) > MAX_IMAGES: raise ValueError('Up to two screenshots')
        clean = []
        for index, image in enumerate(images):
            if not isinstance(image, dict) or not isinstance(image.get('data'), str) or len(image['data']) > 4 * MAX_IMAGE_BYTES // 3 + 4: raise ValueError('Invalid screenshot')
            data = base64.b64decode(image['data'], validate=True)
            if not 0 < len(data) <= MAX_IMAGE_BYTES: raise ValueError('Screenshot exceeds 3 MB')
            mime, ext = media(data)
            if mime not in ('image/png', 'image/jpeg', 'image/webp') or image.get('mime') != mime: raise ValueError('Use PNG, JPEG or WebP')
            clean.append(dict(name=f'screenshot-{index+1}.{ext}', mime=mime, data=base64.b64encode(data).decode()))
        return dict(id=ident, category=body.get('category', 'other'), message=message.strip(), contact=contact.strip(),
                    language=body.get('language', 'en'), images=clean)

    def submit(self, body):
        clean = self.validate(body)
        with self.lock:
            path = self.path(clean['id'])
            if path.exists():
                report = self.get(clean['id'])
                if any(report[k] != value for k, value in clean.items()): raise ValueError('Feedback ID already belongs to different content')
                return self.public(report)
            config = self.public_config()
            report = dict(clean, created=time.time(), status='saved', environment=dict(appVersion=config['appVersion'], build=config['build'], platform=sys.platform))
            atomic(path, report)
        return self.send(clean['id'])

    def send(self, ident):
        with self.lock:
            report = self.get(ident)
            if report['status'] == 'submitted' or ident in self.active: return self.public(report)
            try: config = self.config()
            except (ValueError, OSError):
                report['deliveryError'] = 'configuration_error';atomic(self.path(ident), report);return self.public(report)
            if not config['endpoint']: return self.public(report)
            self.active.add(ident)
        try:
            # Only explicitly supplied content and minimal app metadata leave the machine.
            payload = {k: copy.deepcopy(report[k]) for k in ('id', 'created', 'category', 'message', 'contact', 'language', 'images', 'environment')}
            self.sender(config['endpoint'], payload)
            report['status'] = 'submitted';report['submittedAt'] = time.time();report.pop('deliveryError', None)
        except Exception:
            report['deliveryError'] = 'delivery_unconfirmed'
        finally:
            with self.lock:
                atomic(self.path(ident), report);self.active.discard(ident)
        return self.public(report)

    def export(self, ident):
        report = self.get(ident);stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            content = {k:v for k,v in report.items() if k != 'images'}
            content['images'] = [im['name'] for im in report['images']]
            archive.writestr('feedback.json', json.dumps(content, ensure_ascii=False, indent=2))
            archive.writestr('feedback.txt', self.text(report))
            for image in report['images']: archive.writestr(image['name'], base64.b64decode(image['data']))
        return stream.getvalue()

    def text(self, report):
        return f"Research Council feedback\nID: {report['id']}\nType: {report['category']}\nApp: {report['environment']['appVersion']} ({report['environment']['build']})\nPlatform: {report['environment']['platform']}\nReply: {report['contact'] or '—'}\n\n{report['message']}\n\nScreenshots: {len(report['images'])} (included in feedback ZIP)\n"
