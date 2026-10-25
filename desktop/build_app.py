#!/usr/bin/env python3
"""Build the macOS client from source. No data, OAuth files or dependencies are bundled."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('verification_paths.py','execution_flow.py','experiment_monitor.py','experiment_worker.py','handoff.py','usage_accounting.py','context_sync.py','execution_progress.py','side_context.py','side-sources-client.js','activity.js','feedback.py','feedback-client.js','feedback-config.json','execution-approval.js','composer-actions.js','research-tasks.js','image_store.py','images-client.js','model_catalog.py','usage_status.py','bridge.py','native_cli.py','orchestration.py','tracking.py','gemini_adapter.py','gemini_guard.py',
         'index.html','conversation-scroll.js','app.js','bridge-client.js','council-runtime.js','dynamic-runtime.js','claim-tracker.js',
         'council-ux.js','council-ux.css','markdown.js','marked.umd.js','theme.js','themes.css','runtime.css','THIRD_PARTY_NOTICES.md',
         'login_gemini_mac.command')


def build(destination, feedback_email=None, feedback_endpoint=None):
    destination = destination.expanduser().absolute()
    if destination.exists():
        raise SystemExit('Destination exists; preserve it and choose a new output: '+str(destination))
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='council-app-build-', dir=destination.parent) as temporary:
        tmp = Path(temporary)
        app = tmp/'Research Council.app'
        contents = app/'Contents'
        binaries, resources = contents/'MacOS', contents/'Resources'
        binaries.mkdir(parents=True)
        (resources/'council').mkdir(parents=True)
        for name in FILES:
            shutil.copy2(ROOT/name, resources/'council'/name)
        if feedback_email is not None or feedback_endpoint is not None:
            import json
            from feedback import validate_config
            config=json.loads((ROOT/'feedback-config.json').read_text())
            if feedback_email is not None:config['email']=feedback_email
            if feedback_endpoint is not None:config['endpoint']=feedback_endpoint
            (resources/'council'/'feedback-config.json').write_text(json.dumps(validate_config(config)))
        shutil.copytree(ROOT/'assets', resources/'council'/'assets')
        subprocess.run(['xcrun','swiftc','-swift-version','5','-O','-framework','Cocoa','-framework','WebKit',
                        '-target',subprocess.check_output(['uname','-m'],text=True).strip()+'-apple-macosx12.0',
                        str(ROOT/'desktop/ResearchCouncil.swift'),'-o',str(binaries/'ResearchCouncil')],check=True)
        subprocess.run(['xcrun','swift',str(ROOT/'desktop/make_icon.swift'),str(tmp/'Council.iconset')],check=True)
        subprocess.run(['/usr/bin/iconutil','-c','icns',str(tmp/'Council.iconset'),'-o',str(resources/'CouncilSymbolWhite.icns')],check=True)
        info = dict(CFBundleExecutable='ResearchCouncil',CFBundleIdentifier='local.research-council.desktop',
                    CFBundleName='Research Council',CFBundleDisplayName='Research Council',CFBundlePackageType='APPL',
                    CFBundleShortVersionString='0.11',CFBundleVersion='48',CFBundleIconFile='CouncilSymbolWhite',
                    LSMinimumSystemVersion='12.0',NSHighResolutionCapable=True,
                    NSAppTransportSecurity=dict(NSAllowsLocalNetworking=True),
                    RCPythonPath=str(Path(sys.executable).resolve()),
                    NSHumanReadableCopyright='Research Council · local research workspace')
        (contents/'Info.plist').write_bytes(plistlib.dumps(info))
        subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(app)],check=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
        shutil.move(str(app),destination)
    print(destination)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'work/Research Council.app')
    parser.add_argument('--feedback-email', help='Public recipient address for the email fallback')
    parser.add_argument('--feedback-endpoint', help='HTTPS feedback receiver; no secret keys in the app')
    args=parser.parse_args()
    build(args.output,args.feedback_email,args.feedback_endpoint)
