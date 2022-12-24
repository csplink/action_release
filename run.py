#!/usr/bin/env python3

from github import Github, GithubException
import os
import subprocess
import json


def main():
    ref = os.environ.get("GITHUB_REF", None)
    if not ref:
        raise SystemExit("Not an event based on a push. Workflow configuration is wrong?")
    REF_PREFIX = "refs/tags/"
    if not ref.startswith(REF_PREFIX):
        raise SystemExit("Ref {} is not a tag. Workflow configuration is wrong?".format(ref))
    tag = ref[len(REF_PREFIX):]

    github_actor = os.environ["GITHUB_ACTOR"]
    github_token = os.environ["INPUT_TOKEN"]
    github_repo = os.environ["GITHUB_REPOSITORY"]

    print("Connecting to GitHub...")
    github = Github(github_token)
    repo = github.get_repo(github_repo)

    if repo.private:
        # For private repos, git needs authentication (but set so that the
        # remote URL doesn't embed the temporary credentials in the zip file or
        # even store the temporary credential token in the filesystem.)
        subprocess.run(["git", "config", "--global", "credential.https://github.com.username", github_actor],
                       check=True)
        helper_cmd = "!f() { test \"$1\" = get && echo \"password=$INPUT_TOKEN\"; }; f"  # shell command
        subprocess.run(["git", "config", "--global", "credential.https://github.com.helper", helper_cmd], check=True)

    git_url = "https://github.com/{}.git".format(github_repo)
    repo_name = github_repo.split("/")[1]
    directory = "{}-{}".format(repo_name, tag)

    print("Doing a full recursive clone of {} ({}) into {}...".format(git_url, tag, directory))
    # note: it may be easier to use github's "checkout" action here, with the correct args
    subprocess.run(
        ["git", "clone", "--shallow-submodules", "--depth=1", "--recursive", "--branch=" + tag, git_url, directory],
        check=True)

    git_tag_p = subprocess.run("git describe --tags", shell=True, stdout=subprocess.PIPE, check=True, cwd=directory)
    git_tag_long_p = subprocess.run("git describe --tags --long", shell=True, stdout=subprocess.PIPE, check=True, cwd=directory)
    git_branch_p = subprocess.run("git rev-parse --abbrev-ref HEAD", shell=True, stdout=subprocess.PIPE, check=True, cwd=directory)
    git_commit_p = subprocess.run("git rev-parse --short HEAD", shell=True, stdout=subprocess.PIPE, check=True, cwd=directory)
    git_commit_long_p = subprocess.run("git rev-parse HEAD", shell=True, stdout=subprocess.PIPE, check=True, cwd=directory)
    git_commit_date_p = subprocess.run("git log -1 --date=format:%Y%m%d%H%M%S --format=%ad", shell=True, stdout=subprocess.PIPE, check=True, cwd=directory)

    info = {}
    info["git_tag"] = git_tag_p.stdout.decode("utf-8").strip() if git_tag_p.stdout else "none"
    info["git_tag_long"] = git_tag_long_p.stdout.decode("utf-8").strip() if git_tag_long_p.stdout else "none"
    info["git_branch"] = git_branch_p.stdout.decode("utf-8").strip() if git_branch_p.stdout else "none"
    info["git_commit"] = git_commit_p.stdout.decode("utf-8").strip() if git_commit_p.stdout else "none"
    info["git_commit_long"] = git_commit_long_p.stdout.decode("utf-8").strip() if git_commit_long_p.stdout else "none"
    info["git_commit_date"] = git_commit_date_p.stdout.decode("utf-8").strip() if git_commit_date_p.stdout else "none"

    with open(directory + "/version.json", 'w') as fp:
        json.dump(info, fp, indent=4)

    subprocess.run("find . -name '.git' | xargs rm -rf", shell=True, check=True)

    zipfile = "{}.zip".format(repo_name)
    print("Zipping {}...".format(zipfile))
    subprocess.run(["/usr/bin/7z", "a", "-mx=9", "-tzip", zipfile, directory], check=True)

    tarfile = "{}.tar.gz".format(repo_name)
    print("tar {}...".format(tarfile))
    subprocess.run(["tar", "czf", tarfile, directory], check=True)

    try:
        release = repo.get_release(tag)
        print("Existing release found...")
        if any((asset.name == zipfile or asset.name == tarfile) for asset in release.get_assets()):
            raise SystemExit("A release for tag {} already exists and has a file {}. Workflow configured wrong?".format(
                tag, directory))
    except GithubException:
        print("Creating release...")
        is_prerelease = "-" in tag  # tags like vX.Y-something are pre-releases
        release_repo_name = os.environ.get('INPUT_NAME', repo_name)
        name = ""
        if is_prerelease:
            name = f"{release_repo_name} Pre-release {tag}"
        else:
            name = f"{release_repo_name} {tag}"
        release = repo.create_git_release(tag, name, "(Draft created by Action)", draft=True, prerelease=is_prerelease)

    print("Attaching zipfile...")
    release.upload_asset(zipfile)

    print("Attaching tar...")
    release.upload_asset(tarfile)

    print("Release URL is {}".format(release.html_url))


if __name__ == "__main__":
    main()
