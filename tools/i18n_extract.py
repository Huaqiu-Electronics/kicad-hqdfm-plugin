import os
import subprocess
import sys


DOMAIN = "kicad_hqdfm_plugin"


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pot_path = os.path.join(root, "kicad_dfm", "language", "locale", DOMAIN + ".pot")
    sources = []
    for current, _, files in os.walk(os.path.join(root, "kicad_dfm")):
        for filename in files:
            if filename.endswith(".py"):
                sources.append(os.path.join(current, filename))
    if not sources:
        return 0
    return subprocess.call(["pygettext.py", "-d", DOMAIN, "-o", pot_path] + sources)


if __name__ == "__main__":
    sys.exit(main())
