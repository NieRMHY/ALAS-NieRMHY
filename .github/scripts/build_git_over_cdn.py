import argparse
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path


def run_git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def build_pack(latest, old, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    pack = output_dir / f"pack-{latest}.pack"
    idx = output_dir / f"pack-{latest}.idx"
    zip_path = output_dir / f"{old}.zip"

    revs = f"{latest}\n^{old}\n".encode("ascii")
    with pack.open("wb") as f:
        subprocess.run(
            ["git", "pack-objects", "--revs", "--stdout"],
            input=revs,
            stdout=f,
            check=True,
        )

    subprocess.run(
        ["git", "index-pack", "-o", str(idx), str(pack)],
        stdout=subprocess.DEVNULL,
        check=True,
    )

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.write(pack, pack.name)
        zipped.write(idx, idx.name)

    return zip_path


def main():
    parser = argparse.ArgumentParser(description="Build git-over-cdn update packs.")
    parser.add_argument("--branch", default="master")
    parser.add_argument("--history", type=int, default=1)
    parser.add_argument("--output", default="dist/git-over-cdn")
    args = parser.parse_args()

    output = Path(args.output)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    latest = run_git("rev-parse", args.branch)
    commits = run_git("rev-list", "--first-parent", f"--max-count={args.history + 1}", args.branch).splitlines()
    old_commits = [commit for commit in commits if commit != latest]

    (output / "latest.json").write_text(
        json.dumps({"commit": latest}, indent=2) + "\n",
        encoding="utf-8",
    )

    latest_dir = output / latest
    for old in old_commits:
        latest_dir.mkdir(parents=True, exist_ok=True)
        build_pack(latest=latest, old=old, output_dir=latest_dir)

    print(f"Latest commit: {latest}")
    print(f"Generated {len(old_commits)} pack zip(s) in {output}")


if __name__ == "__main__":
    main()
