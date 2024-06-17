# Building kicad-dfm-plugin

## Preparation

1. Install wxBuilder

https://github.com/wxFormBuilder/wxFormBuilder

2. Install gettext

https://mlocati.github.io/articles/gettext-iconv-windows.html

3. Install POedit

https://poedit.net/download

## Python environment

Locate the python shipped with KiCad (e.g C:\Program Files\KiCad\8.0\bin\python)


## Update translation

1. Extract po files from py

```sh
xgettext.exe xxx.py
```

2. Edit the po files in Poedit

## Debug

The __main__.py is the entry point for debugging

## Deploy
