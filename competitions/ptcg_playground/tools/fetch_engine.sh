#!/usr/bin/env bash
# Fetch the CABT engine (cg/ package + native libs) from the public kaggle-environments wheel.
# The engine is NOT committed; it is copied into vendor/cg and bundled into submissions.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${KAGGLE_ENV_VERSION:-1.33.0}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
python3 -m pip download --no-deps --quiet "kaggle-environments==${VERSION}" -d "$TMP"
python3 - "$TMP" <<'PY'
import glob, sys, zipfile, os, shutil
whl = glob.glob(os.path.join(sys.argv[1], "kaggle_environments-*.whl"))[0]
dst = os.path.join("vendor", "cg")
shutil.rmtree(dst, ignore_errors=True)
os.makedirs(dst)
prefix = "kaggle_environments/envs/cabt/cg/"
with zipfile.ZipFile(whl) as z:
    for name in z.namelist():
        if name.startswith(prefix) and not name.endswith("/"):
            with z.open(name) as src, open(os.path.join(dst, name[len(prefix):]), "wb") as out:
                shutil.copyfileobj(src, out)
print("engine files:", sorted(os.listdir(dst)))
PY
echo "kaggle-environments ${VERSION}" > vendor/ENGINE_VERSION
