"""Runs pipeline.py as a subprocess and streams its output line by line (used by app.py)."""
import subprocess, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))

def build_cmd(zip_path, out_dir, provider, keep, per_ep, batch_size, gap, cache_file, model=""):
    cmd = [sys.executable, "-u", os.path.join(HERE, "pipeline.py"), "--input", zip_path, "--out", out_dir, "--provider", provider,
           "--keep", str(keep), "--per-ep", str(per_ep), "--batch-size", str(batch_size), "--sleep", str(gap), "--cache", cache_file]
    if model: cmd += ["--model", model]
    return cmd

def stream(cmd, env):
    """yields ('line', text) per output line, then ('done', returncode). stderr is merged so nothing can block or get lost."""
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=HERE, bufsize=1)
    for line in proc.stdout:
        yield "line", line.rstrip()
    proc.wait()
    yield "done", proc.returncode
