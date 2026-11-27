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
    # 1. Update main branch
    run("git branch -f main 1a7539afd")
    run("git push origin main")

    # 2. Deploy gh-pages
    tree = run("git write-tree --prefix=pages/")
    print(f"Tree hash: {tree}")
    
    parent = "1a7539afd"
    print(f"Parent commit on origin: {parent}")
    
    commit_cmd = f'git commit-tree {tree} -p {parent} -m "deploy: update gh-pages with Science textbook & 287 interactive simulations"'
    commit = run(commit_cmd)
    print(f"New gh-pages commit: {commit}")
    
    push_cmd = f"git push origin {commit}:refs/heads/gh-pages"
    run(push_cmd)
    print("Successfully pushed to origin/gh-pages!")

if __name__ == "__main__":
    main()
