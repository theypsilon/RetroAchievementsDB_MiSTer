#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path


OWNER = "odelot"
PARENT_OWNER = "MiSTer-devel"
MAIN_REPO_NAME = "Main_MiSTer"
MIN_CORE_COUNT = 12
DB_OPERATOR_URL = (
    "https://raw.githubusercontent.com/MiSTer-devel/Distribution_MiSTer/"
    "main/.github/db_operator.py"
)
DOWNLOADER_TEST_URL = (
    "https://github.com/MiSTer-devel/Downloader_MiSTer/releases/download/latest/"
    "downloader_test.py"
)
EXTRA_FILE_TAGS = {
    "MiSTer_RA": ("essential", "racores", "misterfirmware"),
    "achievement.wav": ("racores", "achievementwav"),
}


def request_json(url: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RetroAchievementsDB-MiSTer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "RetroAchievementsDB-MiSTer"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def run(command: list[str], cwd=None, env=None):
    command = [str(part) for part in command]
    print(" ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True, stderr=subprocess.STDOUT)


def output(command: list[str], cwd=None) -> str:
    command = [str(part) for part in command]
    print(" ".join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.stdout


def list_owner_repositories() -> list[dict]:
    repos = []
    page = 1

    while True:
        batch = request_json(
            f"https://api.github.com/users/{OWNER}/repos?per_page=100&page={page}"
        )
        if not batch:
            break

        repos.extend(batch)
        if len(batch) < 100:
            break

        page += 1

    return repos


def repo_details(name: str) -> dict:
    return request_json(f"https://api.github.com/repos/{OWNER}/{name}")


def latest_release(full_name: str):
    try:
        return request_json(f"https://api.github.com/repos/{full_name}/releases/latest")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def select_asset(release: dict, suffixes: tuple[str, ...]) -> dict:
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if any(name.lower().endswith(suffix) for suffix in suffixes):
            return asset

    suffix_text = ", ".join(suffixes)
    raise RuntimeError(f"No asset ending with {suffix_text} in {release.get('html_url')}")


def discover_sources() -> list[dict]:
    sources = []

    for repo in list_owner_repositories():
        name = repo.get("name", "")
        if not name.endswith("_MiSTer") or not repo.get("fork"):
            continue

        details = repo_details(name)
        parent = details.get("parent") or {}
        parent_owner = ((parent.get("owner") or {}).get("login") or "").strip()
        if parent_owner != PARENT_OWNER:
            continue

        full_name = details["full_name"]
        release = latest_release(full_name)
        if release is None:
            print(f"Skipping {full_name}: no latest release")
            continue

        asset_suffixes = (".zip",) if name == MAIN_REPO_NAME else (".rbf", ".zip")
        try:
            asset = select_asset(release, asset_suffixes)
        except RuntimeError as error:
            if name == MAIN_REPO_NAME:
                raise
            print(f"Skipping {full_name}: {error}")
            continue

        title = name.removesuffix("_MiSTer")
        source = {
            "key": "main" if name == MAIN_REPO_NAME else title.lower(),
            "title": "Main_MiSTer" if name == MAIN_REPO_NAME else title,
            "repo": full_name,
            "release": release,
            "asset": asset,
        }
        sources.append(source)

    sources.sort(key=lambda source: (source["key"] != "main", source["title"].lower()))

    main_count = sum(1 for source in sources if source["key"] == "main")
    if main_count != 1:
        raise RuntimeError(
            f"Expected exactly one {OWNER}/{MAIN_REPO_NAME} source with a latest release; "
            f"found {main_count}."
        )

    core_count = sum(1 for source in sources if source["key"] != "main")
    if core_count < MIN_CORE_COUNT:
        raise RuntimeError(
            f"Refusing to publish: discovered {core_count} release-backed RA core repos, "
            f"but at least {MIN_CORE_COUNT} are required."
        )

    print(f"Discovered {core_count} RA core repos plus {OWNER}/{MAIN_REPO_NAME}.")
    for source in sources:
        print(f"- {source['repo']} @ {source['release'].get('tag_name', '')}")

    return sources


def zip_member(data: bytes, wanted_names: list[str]) -> bytes:
    wanted = {name.lower() for name in wanted_names}
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for info in archive.infolist():
            if not info.is_dir() and Path(info.filename).name.lower() in wanted:
                return archive.read(info)

    raise RuntimeError(f"Missing {', '.join(wanted_names)} in ZIP")


def first_rbf_from_zip(data: bytes) -> bytes:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for info in archive.infolist():
            if not info.is_dir() and info.filename.lower().endswith(".rbf"):
                return archive.read(info)

    raise RuntimeError("Missing .rbf in ZIP")


def write_bytes(path: Path, data: bytes, executable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_mgl(path: Path, title: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "<mistergamedescription>",
                f"    <rbf>_RA_Cores/Cores/{title}</rbf>",
                f"    <setname same_dir=\"1\">RA_{title}</setname>",
                "</mistergamedescription>",
                "",
            ]
        ),
        encoding="utf-8",
    )


def tag_key(term: str) -> str:
    return "".join(
        char
        for char in term.replace(" ", "").lower()
        if char.isalnum() or char in {"-", "_", "."}
    ).replace("-", "").replace("_", "")


def ensure_tag_index(tag_dictionary: dict, term: str) -> int:
    key = tag_key(term)
    if key == "":
        raise ValueError(f"Invalid empty DB tag derived from {term!r}")
    if key not in tag_dictionary:
        next_index = max(tag_dictionary.values(), default=-1) + 1
        tag_dictionary[key] = next_index
    return int(tag_dictionary[key])


def add_extra_file_tags(db_json: Path, db_url: str):
    db = json.loads(db_json.read_text(encoding="utf-8"))
    db["db_url"] = db_url
    files = db.setdefault("files", {})
    tag_dictionary = db.setdefault("tag_dictionary", {})

    for filename, terms in EXTRA_FILE_TAGS.items():
        if filename not in files:
            raise RuntimeError(f"Generated DB does not contain {filename}.")

        file_tags = files[filename].setdefault("tags", [])
        for term in terms:
            index = ensure_tag_index(tag_dictionary, term)
            if index not in file_tags:
                file_tags.append(index)
        file_tags.sort()

    db_json.write_text(json.dumps(db, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def build_payload(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = discover_sources()
    main_source = next(source for source in sources if source["key"] == "main")

    main_zip = download(main_source["asset"]["browser_download_url"])
    write_bytes(output_dir / "MiSTer_RA", zip_member(main_zip, ["MiSTer"]), executable=True)
    write_bytes(output_dir / "achievement.wav", zip_member(main_zip, ["achievement.wav"]))

    for source in sources:
        if source["key"] == "main":
            continue

        asset = source["asset"]
        data = download(asset["browser_download_url"])
        rbf = first_rbf_from_zip(data) if asset["name"].lower().endswith(".zip") else data

        title = source["title"]
        write_bytes(output_dir / "_RA_Cores" / "Cores" / f"{title}.rbf", rbf)
        write_mgl(output_dir / "_RA_Cores" / f"{title}.mgl", title)


def copy_tree_contents(source: Path, target: Path):
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destination)


def clear_worktree(root: Path):
    for item in root.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def unique_branch(prefix: str) -> str:
    suffix = os.environ.get("GITHUB_RUN_ID") or str(os.getpid())
    return f"{prefix}-{suffix}"


def prepare_generated_commit(root: Path, payload_dir: Path):
    license_path = root / "LICENSE"
    readme_path = root / "README.md"
    github_path = root / ".github"

    if not license_path.is_file():
        raise RuntimeError("LICENSE is required before publishing.")
    if not readme_path.is_file():
        raise RuntimeError("README.md is required before publishing.")
    if not github_path.is_dir():
        raise RuntimeError(".github is required before publishing.")

    with tempfile.TemporaryDirectory() as temp_dir:
        desired = Path(temp_dir) / "desired"
        desired.mkdir()
        shutil.copy2(license_path, desired / "LICENSE")
        shutil.copy2(readme_path, desired / "README.md")
        shutil.copytree(github_path, desired / ".github")
        copy_tree_contents(payload_dir, desired)

        run(["git", "config", "user.name", "github-actions[bot]"], cwd=root)
        run(
            ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
            cwd=root,
        )
        run(["git", "switch", "--orphan", unique_branch("generated-ra-cores")], cwd=root)
        clear_worktree(root)
        copy_tree_contents(desired, root)
        run(["git", "add", "-A"], cwd=root)
        run(["git", "commit", "-m", "Update RetroAchievements payload"], cwd=root)


def db_build_environment(force_save: bool = False) -> tuple[str, str, dict]:
    github_repo = os.environ.get("GITHUB_REPOSITORY", "theypsilon/test").strip()
    db_id = (os.environ.get("DB_ID") or github_repo).strip()
    db_url = (
        os.environ.get("DB_URL")
        or f"https://raw.githubusercontent.com/{github_repo}/db/db.json.zip"
    ).strip()
    base_files_url = (
        os.environ.get("BASE_FILES_URL")
        or f"https://raw.githubusercontent.com/{github_repo}/%s/"
    ).strip()
    finder_ignore = " ".join(
        part.strip()
        for part in [os.environ.get("FINDER_IGNORE", ""), "LICENSE", "README.md"]
        if part.strip()
    )

    env = os.environ.copy()
    env.update(
        {
            "DB_ID": db_id,
            "DB_URL": "" if force_save else db_url,
            "TEST_DB_URL": "" if force_save else os.environ.get("TEST_DB_URL", ""),
            "DB_JSON_NAME": "db.json",
            "BASE_FILES_URL": base_files_url,
            "FINDER_IGNORE": finder_ignore,
            "BROKEN_MRAS_IGNORE": os.environ.get("BROKEN_MRAS_IGNORE", "true"),
            "EXTERNAL_FILES": "",
        }
    )
    return db_id, db_url, env


def run_db_operator(root: Path) -> tuple[str, str, Path, Path]:
    db_id, db_url, env = db_build_environment(force_save=True)
    db_json = root / "db.json"
    if db_json.exists():
        db_json.unlink()

    temp_dir = Path(tempfile.mkdtemp(prefix="ra-db-operator-"))
    db_operator = temp_dir / "db_operator.py"
    write_bytes(db_operator, download(DB_OPERATOR_URL))
    run([sys.executable, "-m", "pip", "install", "Pillow"], cwd=root)
    run([sys.executable, db_operator, "build", "."], cwd=root, env=env)

    if not db_json.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("db_operator did not generate db.json.")

    add_extra_file_tags(db_json, db_url)
    return db_id, db_url, db_operator, temp_dir


def db_has_changes(root: Path, db_operator: Path, db_url: str) -> bool:
    compare_url = os.environ.get("TEST_DB_URL", "").strip() or db_url
    result = subprocess.run(
        [sys.executable, str(db_operator), "compare", compare_url, "db.json"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        if "Downloading db from db.json" not in result.stdout:
            print("Existing published DB could not be loaded. Treating generated DB as changed.")
            return True
        raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout)

    if "No changes." in result.stdout:
        print("No normalized DB changes detected after MiSTer_RA tag injection. Skipping all pushes.")
        return False
    if "Databases are different." in result.stdout:
        return True

    raise RuntimeError("Unable to determine DB comparison result.")


def run_downloader_tests(root: Path, db_id: str):
    with tempfile.TemporaryDirectory() as temp_dir:
        test_path = Path(temp_dir) / "downloader_test.py"
        write_bytes(test_path, download(DOWNLOADER_TEST_URL), executable=True)
        run([test_path, db_id, root / "db.json"], cwd=Path(temp_dir))


def write_zip_from_file(zip_path: Path, source_path: Path, arcname: str):
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source_path, arcname)


def sanitize_db_id_for_filename(db_id: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", db_id).strip("._-")
    if sanitized == "":
        raise ValueError(f'Unable to derive a drop-in filename from DB_ID "{db_id}"')
    return sanitized


def create_drop_in_database_files(root: Path, db_id: str, db_url: str) -> list[Path]:
    sanitized = sanitize_db_id_for_filename(db_id)
    ini_path = root / f"downloader_{sanitized}.ini"
    zip_path = root / f"downloader_{sanitized}.zip"
    contents = f"[{db_id}]\ndb_url = {db_url}\n"

    with ini_path.open("w", encoding="utf-8", newline="\n") as ini_file:
        ini_file.write(contents)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(ini_path.name, contents)

    return [ini_path, zip_path]


def publish_database_branch(root: Path, db_id: str, db_url: str) -> str:
    db_json = root / "db.json"
    db_zip = root / "db.json.zip"
    write_zip_from_file(db_zip, db_json, "db.json")
    db_files = [db_zip, *create_drop_in_database_files(root, db_id, db_url)]

    with tempfile.TemporaryDirectory() as temp_dir:
        stage = Path(temp_dir) / "db"
        stage.mkdir()
        for path in db_files:
            shutil.copy2(path, stage / path.name)

        run(["git", "switch", "--orphan", unique_branch("generated-db")], cwd=root)
        clear_worktree(root)
        copy_tree_contents(stage, root)
        run(["git", "add", "-A"], cwd=root)
        run(["git", "commit", "-m", "Creating database"], cwd=root)
        db_commit_hash = output(["git", "rev-parse", "HEAD"], cwd=root).strip()
        run(["git", "push", "--force", "origin", "HEAD:db"], cwd=root)

    return db_commit_hash


def track_release(root: Path, db_commit_hash: str):
    if os.environ.get("TRACK_RELEASE", "true").lower() == "false":
        return

    try:
        remote_heads = output(["git", "ls-remote", "--heads", "origin", "db-releases"], cwd=root)
        if "refs/heads/db-releases" in remote_heads:
            run(["git", "fetch", "origin", "db-releases"], cwd=root)
            run(["git", "switch", "--detach", "FETCH_HEAD"], cwd=root)
        else:
            run(["git", "switch", "--orphan", unique_branch("generated-db-releases")], cwd=root)
            clear_worktree(root)

        with (root / "commits.txt").open("a", encoding="utf-8", newline="\n") as commits:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            commits.write(f"{timestamp}: {db_commit_hash}\n")

        run(["git", "add", "commits.txt"], cwd=root)
        run(["git", "commit", "-m", f"Track release {db_commit_hash}"], cwd=root)
        run(["git", "push", "origin", "HEAD:db-releases"], cwd=root)
    except Exception as error:
        print(f"Warning: failed to track release: {error}", flush=True)
        traceback.print_exc()


def publish_payload(payload_dir: Path):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Publishing is only supported in GitHub Actions. Use --dry-run locally.")

    root = Path.cwd()
    prepare_generated_commit(root, payload_dir)

    db_operator_temp = None
    try:
        db_id, db_url, db_operator, db_operator_temp = run_db_operator(root)
        if not db_has_changes(root, db_operator, db_url):
            return

        run(["git", "push", "--force", "origin", "HEAD:main"], cwd=root)
        run_downloader_tests(root, db_id)
        db_commit_hash = publish_database_branch(root, db_id, db_url)
        track_release(root, db_commit_hash)
    finally:
        if db_operator_temp is not None:
            shutil.rmtree(db_operator_temp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="Build and publish the RetroAchievements MiSTer Downloader payload."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--output",
        type=Path,
        help="CI mode: write generated payload here, build the DB, and publish only on DB changes.",
    )
    target.add_argument(
        "--dry-run",
        type=Path,
        help="Fetch the payload into a local directory and stop; no git push is performed.",
    )
    args = parser.parse_args()

    output_dir = args.output or args.dry_run
    build_payload(output_dir)

    if args.dry_run:
        print(f"Dry run complete. Wrote payload to {output_dir}. No git push was performed.")
    else:
        publish_payload(output_dir)


if __name__ == "__main__":
    main()
