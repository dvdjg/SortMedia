@echo off
cd /d F:\scripts
C:\Python313\pythonw.exe 06_vision.py --workers 6 --escribir-exif > F:\scripts\salida\vision_run.log 2>&1
