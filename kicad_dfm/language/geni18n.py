# -*- coding: utf-8 -*-
"""
This will generate the .pot and .mo files for the application domain and
languages defined below.

The .po and .mo files are placed as per convention in

"appfolder/locale/lang/LC_MESSAGES"

The .pot file is placed in the locale folder.

This script or something similar should be added to your build process.

The actual translation work is normally done using a tool like poEdit or
similar, it allows you to generate a particular language catalog from the .pot
file or to use the .pot to merge new translations into an existing language
catalog.

"""
import platform
import subprocess
import sys
import os
from constraint import CODE_TO_NAME, LANG_DOMAIN, DEFAULT_LANG

# we remove English as source code strings are in English
supportedLang = []
for code in CODE_TO_NAME:
    if CODE_TO_NAME[code] != DEFAULT_LANG:
        supportedLang.append(code)


appFolder = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

m, s, _ = platform.python_version_tuple()

if os.name == "nt" and m == "3" and s == "8":
    # setup some stuff to get at Python I18N tools/utilities
    pyExe = sys.executable
    pyFolder = os.path.split(pyExe)[0]
    pyToolsFolder = os.path.join(pyFolder, "Tools")
    pyI18nFolder = os.path.join(pyToolsFolder, "i18n")
    pyGettext = os.path.join(pyI18nFolder, "pygettext.py")
    pyMsgfmt = os.path.join(pyI18nFolder, "msgfmt.py")
    outFolder = os.path.join(appFolder, "language", "locale")
    # build command for pygettext
    gtOptions = "-a -d %s -o %s.pot -p %s %s"

    tCmd = (
        pyExe
        + " "
        + pyGettext
        + " "
        + (gtOptions % (LANG_DOMAIN, LANG_DOMAIN, outFolder, appFolder))
    )
    print("Generating the .pot file")
    print("cmd: %s" % tCmd)
    rCode = subprocess.call(tCmd)
    print("return code: %s\n\n" % rCode)

    for tLang in supportedLang:
        # build command for msgfmt
        langDir = os.path.join(appFolder, (f"language/locale/{tLang}/LC_MESSAGES"))
        if not os.path.exists(langDir):
            os.mkdir(langDir)
        poFile = os.path.join(langDir, LANG_DOMAIN + ".po")
        tCmd = pyExe + " " + pyMsgfmt + " " + poFile

        print("Generating the .mo file")
        print("cmd: %s" % tCmd)
        rCode = subprocess.call(tCmd)
        print("return code: %s\n\n" % rCode)
else:
    from pythongettext.msgfmt import Msgfmt

    # Simply run the msg format cmd to update the .mo on the Ubuntu ci server
    for tLang in supportedLang:
        # build command for msgfmt
        langDir = os.path.join(appFolder, (f"language/locale/{tLang}/LC_MESSAGES"))
        if not os.path.exists(langDir):
            os.mkdir(langDir)
        poFile = os.path.join(langDir, LANG_DOMAIN + ".po")
        moFile = os.path.join(langDir, LANG_DOMAIN + ".mo")
        generator = Msgfmt(poFile).get()
        with open(moFile, "wb") as f:
            f.write(generator)
