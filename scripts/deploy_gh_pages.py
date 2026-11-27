# -*- coding: utf-8 -*-
import subprocess

def run(cmd):
    print("Running:", cmd)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8")
    if r.stdout:
        print("STDOUT:", r.stdout.strip())
    if r.stderr:
        print("STDERR:", r.stderr.strip())
    if r.returncode != 0:
        raise RuntimeError(f"Command failed with code {r.returncode}")
    return r.stdout.strip()

def main():
    # 1. Update feature and main branch
    run("git push origin feature/english-tts-spelling")
    head_commit = run("git rev-parse HEAD")
    run(f"git branch -f main {head_commit}")
    run("git push origin main")

    # 2. Deploy gh-pages
    tree = run("git write-tree --prefix=pages/")
    print(f"Tree hash: {tree}")
    
    parent = run("git rev-parse origin/gh-pages")
    print(f"Parent commit on origin/gh-pages: {parent}")
    
    commit_cmd = f'git commit-tree {tree} -p {parent} -m "deploy: upgrade math textbook with 104 units, 1349 webp figures, and single-unit reader"'
    commit = run(commit_cmd)
    print(f"New gh-pages commit: {commit}")
    
    push_cmd = f"git push -f origin {commit}:refs/heads/gh-pages"
    run(push_cmd)
    print("Successfully pushed to origin/gh-pages!")

if __name__ == "__main__":
    main()
