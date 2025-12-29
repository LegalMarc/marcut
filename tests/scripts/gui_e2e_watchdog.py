#!/usr/bin/env python3
"""
GUI E2E Watchdog Runner for MarcutApp (macOS)

Runs the Swift GUI app in headless mode (--redact) with a hard timeout.
If the app hangs, collects diagnostics and kills the process tree so the
script itself never hangs. Intended for unattended overnight runs.

Usage examples:
  python3 scripts/gui_e2e_watchdog.py \
      --iterations 3 \
      --timeout-sec 600 \
      --mode enhanced \
      --model llama3.1:8b

Options:
  --use-dmg           Mount and test from the DMG instead of the build bundle
  --skip-build        Assume build + DMG already created
  --input PATH        Input DOCX (default: sample-files/Shareholder-Consent.docx)
  --outdir DIR        Output dir (default: /tmp/marcut-e2e)
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = Path.home() / 'Library' / 'Application Support' / 'MarcutApp' / 'logs'
APP_LOG = LOG_DIR / 'marcut.log'


def run(cmd, cwd=None, env=None, timeout=None, check=False):
    p = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p


def ensure_build(skip_build: bool):
    if skip_build:
        return
    build_sh = ROOT / 'build_swift_only.sh'
    if not build_sh.exists():
        raise SystemExit('build_swift_only.sh not found')
    print('[watchdog] Building app + DMG…')
    p = run(['/bin/bash', str(build_sh)])
    print(p.stdout)
    if p.returncode != 0:
        print(p.stderr)
        raise SystemExit('Build failed')


def mount_dmg():
    # Return (mount_point, app_path)
    dmgs = sorted(ROOT.glob('MarcutApp-Swift-*.dmg'))
    if not dmgs:
        raise SystemExit('No DMG found; run build_swift_only.sh first')
    dmg = str(dmgs[-1])
    print(f'[watchdog] Mounting {dmg}…')
    p = run(['hdiutil', 'attach', '-nobrowse', dmg], check=True)
    mount_point = None
    for line in p.stdout.splitlines():
        parts = line.strip().split()  # device, type, mountpoint
        if len(parts) >= 3 and parts[-1].startswith('/Volumes/'):
            mount_point = parts[-1]
    if not mount_point:
        raise SystemExit('Failed to parse DMG mount point')
    app_path = Path(mount_point) / 'MarcutApp.app' / 'Contents' / 'MacOS' / 'MarcutApp'
    return mount_point, app_path


def detach_dmg(mount_point):
    try:
        run(['hdiutil', 'detach', mount_point])
    except Exception:
        pass


def app_binary(use_dmg: bool):
    if use_dmg:
        return mount_dmg()
    app_bin = ROOT / 'build_swift' / 'MarcutApp.app' / 'Contents' / 'MacOS' / 'MarcutApp'
    if not app_bin.exists():
        raise SystemExit('App binary not found in build_swift. Run build_swift_only.sh')
    return None, app_bin


def word_has_tags(docx_path: Path) -> bool:
    try:
        with zipfile.ZipFile(docx_path, 'r') as z:
            xml = z.read('word/document.xml').decode('utf-8', errors='ignore')
            return any(tag in xml for tag in ['w:del', 'w:ins', '[URL_', '[EMAIL', '[ORG', '[NAME'])
    except Exception:
        return False


def kill_process_tree(proc: subprocess.Popen):
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass
    # Best-effort: also kill child helpers (ollama, if any)
    try:
        subprocess.run(['pkill', '-f', 'MarcutApp.app/Contents/MacOS/MarcutApp'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['pkill', '-f', 'ollama'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def tail_log(n=120) -> str:
    try:
        if not APP_LOG.exists():
            return ''
        with APP_LOG.open('r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            return ''.join(lines[-n:])
    except Exception:
        return ''


def make_input_docx(default_path: Path) -> Path:
    # Use provided sample if exists; otherwise create a minimal doc
    if default_path.exists():
        return default_path
    try:
        from docx import Document
        tmp = Path('/tmp/marcut-e2e-input.docx')
        d = Document()
        d.add_paragraph('Email: alice@example.com URL: https://example.com')
        d.save(tmp)
        return tmp
    except Exception:
        raise SystemExit('No input docx available and python-docx not importable')


def run_one(app_bin: Path, input_path: Path, outdir: Path, mode: str, model: str, timeout_sec: int, backend: str = None) -> bool:
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [str(app_bin), '--redact', '--in', str(input_path), '--outdir', str(outdir), '--mode', mode]
    if backend:
        cmd.extend(['--backend', backend])
    cmd.extend(['--model', model])
    print('[watchdog] Launch:', ' '.join(cmd))
    start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        rc = proc.wait(timeout=timeout_sec)
        elapsed = int(time.time() - start)
        print(f'[watchdog] Exit code {rc} after {elapsed}s')
    except subprocess.TimeoutExpired:
        print('[watchdog] TIMEOUT — capturing diagnostics and killing process')
        # Capture sample if available
        try:
            sample_path = outdir / 'process.sample.txt'
            with sample_path.open('w') as fh:
                subprocess.run(['sample', str(proc.pid), '5'], stdout=fh, stderr=subprocess.STDOUT, timeout=10)
            print(f'[watchdog] Wrote {sample_path}')
        except Exception:
            pass
        kill_process_tree(proc)
        return False

    # Persist logs for this run
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    log_copy = outdir / f'marcut-{ts}.log'
    try:
        if APP_LOG.exists():
            shutil.copy2(APP_LOG, log_copy)
            print(f'[watchdog] Copied app log to {log_copy}')
    except Exception:
        pass

    # Validate outputs
    outs = list(outdir.glob('*_redacted.docx'))
    rep = list(outdir.glob('*_report.json'))
    if not outs or not rep:
        print('[watchdog] Missing outputs')
        print(tail_log())
        return False
    if not word_has_tags(outs[0]):
        print('[watchdog] DOCX does not contain expected tags — open manually to confirm')
    print('[watchdog] Success:', outs[0].name, rep[0].name)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iterations', type=int, default=1)
    ap.add_argument('--timeout-sec', type=int, default=600)
    ap.add_argument('--mode', choices=['enhanced', 'rules'], default='enhanced')
    ap.add_argument('--model', default='llama3.1:8b')
    ap.add_argument('--use-dmg', action='store_true')
    ap.add_argument('--skip-build', action='store_true')
    ap.add_argument('--input', default=str(ROOT / 'sample-files' / 'Shareholder-Consent.docx'))
    ap.add_argument('--outdir', default='/tmp/marcut-e2e')
    ap.add_argument('--backend', default=None, help='ollama or mock (defaults to app default)')
    args = ap.parse_args()

    ensure_build(args.skip_build)

    mount_point = None
    try:
        mount_point, app_bin = app_binary(args.use_dmg)
        input_doc = make_input_docx(Path(args.input))
        base_outdir = Path(args.outdir)
        successes = 0
        failures = 0
        for i in range(1, args.iterations + 1):
            outdir = base_outdir / f'run-{i:02d}'
            print(f'\n[watchdog] === Iteration {i}/{args.iterations} ===')
            ok = run_one(app_bin, input_doc, outdir, args.mode, args.model, args.timeout_sec, args.backend)
            if ok:
                successes += 1
            else:
                failures += 1
            # Small cooldown between runs
            time.sleep(3)
        print(f'\n[watchdog] Finished: {successes} ok / {failures} failed')
        sys.exit(0 if failures == 0 else 1)
    finally:
        if mount_point:
            detach_dmg(mount_point)


if __name__ == '__main__':
    main()
