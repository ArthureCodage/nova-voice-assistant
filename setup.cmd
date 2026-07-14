@echo off
setlocal
cd /d "%~dp0"
echo Creation de l'environnement Python local...
python -m venv .venv
if errorlevel 1 goto error
echo Installation de la reconnaissance vocale locale...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
if not exist "models\fr_FR-siwis-medium.onnx" (
  ".venv\Scripts\python.exe" -m piper.download_voices --data-dir models fr_FR-siwis-medium
  if errorlevel 1 goto error
)
echo.
echo Installation terminee. Lance maintenant start.cmd.
pause
exit /b 0

:error
echo.
echo Echec de l'installation. Verifie la connexion Internet puis recommence.
pause
exit /b 1
