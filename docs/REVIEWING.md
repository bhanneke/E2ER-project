# Reviewing a study with e2er

This guide is for reviewers and readers who want to check a study that its authors published with e2er. You need no account and no API key. e2er runs the same way on Linux, macOS and Windows; the automated tests run every command below on all three.

## What you need for each task

| Task | What you need |
| --- | --- |
| Read the study, its dossier and its checks on e2er.org | A web browser |
| Download the study package, see what it holds, check every file (`fetch`, `inspect`, `unpack`, `verify`) | Python 3.11 or newer and e2er |
| Compare the files with what e2er.org published (`verify --against`) | The same, and an internet connection |
| Run the study's code again and compare the results (`reproduce`) | The same, and Docker with Linux containers |

A study package is one `.e2er` file: the paper, the code, the data whose source allows passing them on, the results and the list of packages the code needs, each file with its SHA-256 hash. e2er.org keeps no copy. The authors keep the file on GitHub or Zenodo, and e2er.org records its address, size and hash.

## Install e2er

The installer uv brings its own Python, so you do not need to install Python first.

On macOS and Linux, in a terminal:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.12 e2er
uv tool update-shell        # then open a new terminal window
e2er --version
```

On Windows, in PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv tool install --python 3.12 e2er
uv tool update-shell        # then open a new PowerShell window
e2er --version
```

With pipx, if you use it already: `pipx install e2er`. With your own Python, install e2er into a virtual environment:

```bash
python3 -m venv e2er-env                 # Windows: py -3.12 -m venv e2er-env
source e2er-env/bin/activate             # Windows: e2er-env\Scripts\Activate.ps1
pip install e2er
```

If PowerShell refuses to run `Activate.ps1`, allow scripts for your account once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## The commands

Each command below prints what it checked and ends with a one-line verdict. Nothing runs the authors' code except `e2er reproduce`, and that command asks you first.

### Download the package

```bash
e2er fetch https://e2er.org/<owner>/<project>
```

`fetch` takes the address of a study (it downloads the latest version; `--version 2` picks another) or of a dossier (`https://e2er.org/d/<id>`). It reads the package's record from e2er.org, downloads the file from GitHub or Zenodo and keeps it only when its size and SHA-256 match the record. It then prints the next three commands with the file's name filled in. `-o <folder>` saves the file in another folder.

For a double-blind review the journal gives you the file itself (the authors made it with `e2er pack --blind`), and the address has the form `https://e2er.org/r/<code>`. Skip `fetch` and start with `inspect`.

### See what the package holds

```bash
e2er inspect <project>-v1.e2er
```

`inspect` reads the package's list of files without unpacking anything. It shows the title, the authors, the e2er version, which data the package includes and which it leaves out (and how a rerun loads them again), the Python version, the pinned packages, the size, the fingerprint, and the exact commands `reproduce` would run.

### Check every file

```bash
e2er verify <project>-v1.e2er
e2er verify <project>-v1.e2er --against https://e2er.org/<owner>/<project>
```

`verify` unpacks the package into a temporary folder, checks every file against the package's list, and then checks the study itself: every file against `provenance.json`, the numbers in the paper against the results, the tables against the estimates, and the citations against the bibliography. It works offline and reads no key.

`--against` also compares the files with what e2er.org published for this study: the package must be the one e2er.org records for that version, and its content must be a version the authors published. It reads e2er.org with GET requests only. A dossier address (`https://e2er.org/d/<id>`) and a double-blind address (`https://e2er.org/r/<code>`) work as well.

`e2er unpack <file> [folder]` writes the files into a folder of your choice and checks each one as it writes it. `e2er verify <folder>` checks an unpacked folder the same way.

### Run the code again

```bash
e2er reproduce <project>-v1.e2er
```

Before anything runs, `reproduce` prints every command the study's `reproduce.json` lists, in order, with the packages it will install, and says where they will run. It asks once (`Run them? [y/N]`). A step that loads data from the web asks again. In a script, `--yes` answers both questions.

The authors' code runs in a Docker container: without network access, with a read-only system, with no folder of yours except a new run folder, and without any API key or token. e2er first builds an environment with the study's pinned packages, then runs each step in its own container, compares every result value with the published one, and renders the paper's tables again. The report lists each value that differs. The exit code is 0 when the study reproduces, 1 when values or tables differ, and 2 when the code could not run. `--keep` keeps the run folder for a closer look, and `--json report.json` writes the report as JSON.

The first run of a study takes longest, because e2er downloads the Python image once and installs the study's packages. On GitHub's Linux machines a study that needs no packages beyond Python takes a little over a minute; installing pandas, SciPy, statsmodels and matplotlib adds about a minute on a fast connection. The study's own scripts then take as long as they took for the authors; `inspect` lists them. A second run with the same packages reuses the environment.

### Without Docker

Without Docker, `reproduce` runs nothing and says so:

```
error: nothing was run. Docker is not installed.
e2er reproduce runs the study's code in a Docker sandbox: start Docker (or install it: https://docs.docker.com/get-docker/) and run the command again. --no-sandbox runs the code on this computer as you instead: only for a study whose code you trust.
```

`e2er reproduce --no-sandbox <file>` runs the steps on your computer in a new virtual environment. e2er then points the home folder at an empty folder and passes no API key or token, but the code can read every file you can. Use it only for a study whose code you have read or whose authors you trust. Without Docker, e2er installs packages only from wheels, because building a package from source runs its code.

## Notes for Windows

Docker Desktop on Windows has to run Linux containers, its default with the WSL 2 backend. In Windows-containers mode `reproduce` refuses and names the switch ("Switch to Linux containers" in Docker Desktop's menu).

Download the `.e2er` package with `fetch` when you can. Git for Windows usually converts line endings when it checks files out (`core.autocrlf`), which changes the bytes of text files and makes `verify` fail. `verify` then names the files that differ only in their line endings. To check a study from its Git repository, clone it with `git clone -c core.autocrlf=false <address>`.

Windows opens paths of at most 259 characters unless you turn on long paths. If `unpack` or `reproduce` reports a path that is too long, unpack into a short folder such as `C:\e2er\study`, or turn on long paths: in PowerShell as administrator, `New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force`, then sign out and in again.

e2er prints in UTF-8, so file names and titles with characters such as `ü` or `文` reach a file or another program unchanged (`e2er verify study.e2er > report.txt`). Commands e2er prints for you to paste quote paths with spaces in double quotes, which both PowerShell and the Command Prompt accept.

A package refuses to unpack on Windows when a file name contains a character Windows does not allow (`<>:"|?*`), ends with a dot or a space, or uses a device name such as `NUL` or `CON`. `e2er pack` warns authors about such names.

If you sign in to e2er.org from the command line (reviewers do not need to), e2er keeps the token in the Windows Credential Manager. Where no credential store answers, it writes the token to `%USERPROFILE%\.e2er\credentials.json`. Windows has no POSIX file modes; your profile folder's access list keeps that file to your account, the administrators and the system.
