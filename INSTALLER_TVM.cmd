@echo off
setlocal EnableExtensions DisableDelayedExpansion
title TVM PowerCare - Installation
set "TVM_DIR_PUSHED=0"
set "TVM_EXIT_CODE=0"
pushd "%~dp0"
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto folder_failed
set "TVM_DIR_PUSHED=1"

echo.
echo TVM PowerCare - Installation sur ce PC
echo Docker Desktop doit etre ouvert en mode conteneurs Linux.
echo La premiere installation peut prendre plusieurs minutes.
echo.

if not exist "compose.yaml" goto files_missing
if not exist "scripts\init_env.py" goto files_missing
where docker >nul 2>&1
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto docker_missing
docker info >nul 2>&1
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto docker_not_ready
docker compose version >nul 2>&1
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto compose_missing
docker info --format "{{.OSType}}" | findstr /x /c:"linux" >nul
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto linux_required

echo [1/3] Preparation de la configuration locale...
echo Un fichier .env existant sera conserve sans modification.
docker run --rm --mount "type=bind,source=%CD%,target=/app" -w /app python:3.12-slim python scripts/init_env.py --demo
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto configuration_failed

echo.
echo [2/3] Construction de l'application et preparation de la base...
echo La demonstration sera ajoutee uniquement si le mode demo est deja actif.
docker compose --profile container run --rm --build web python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); from django.core.management import execute_from_command_line as run; run(['manage.py', 'migrate', '--noinput']); run(['manage.py', 'seed_demo']) if os.environ.get('TVM_DEMO_MODE') == '1' else print('Mode reel conserve : aucune donnee fictive ni aucun compte de demonstration ajoute.')"
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto initialization_failed

echo.
echo [3/3] Demarrage et verification de disponibilite...
docker compose --profile container up -d --wait --wait-timeout 180
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto startup_failed

echo.
echo Installation terminee. L'application est prete sur CE PC :
echo http://localhost:8000
echo Pour les prochains demarrages, utilisez DEMARRER_TVM.cmd.
echo Pour arreter sans effacer les donnees, utilisez ARRETER_TVM.cmd.
if exist ".local\demo-access.txt" echo Les acces de demonstration locaux vont s'ouvrir dans le Bloc-notes.
if exist ".local\demo-access.txt" start "" "%SystemRoot%\System32\notepad.exe" ".local\demo-access.txt"
start "" "http://localhost:8000"
echo.
echo Si la configuration est en mode reel et sans compte administrateur,
echo suivez la section correspondante dans docs\INSTALLATION_WINDOWS.md.
echo.
pause
goto finished

:folder_failed
echo Impossible d'ouvrir le dossier de l'application.
echo Extrayez toute l'archive dans un dossier local, puis reessayez.
goto failed

:files_missing
set "TVM_EXIT_CODE=2"
echo Fichiers du projet manquants.
echo Extrayez toute l'archive avant de lancer ce fichier, sans le deplacer seul.
goto failed

:docker_missing
echo Docker Desktop est introuvable.
echo Installez Docker Desktop pour Windows, puis ouvrez-le.
echo Guide : docs\INSTALLATION_WINDOWS.md
goto failed

:docker_not_ready
echo Docker est present, mais son moteur ne repond pas.
echo Ouvrez Docker Desktop et attendez que le moteur soit pret.
echo Verifiez aussi ses instructions concernant WSL 2 et le redemarrage du PC.
goto failed

:compose_missing
echo Docker Compose est indisponible.
echo Mettez Docker Desktop a jour, puis relancez cette installation.
goto failed

:linux_required
echo Docker Desktop doit utiliser les conteneurs Linux.
echo Choisissez ce mode dans Docker Desktop, puis reessayez.
goto failed

:configuration_failed
echo La preparation du fichier .env a echoue.
echo Verifiez Internet, le partage du dossier avec Docker et les messages ci-dessus.
goto failed

:initialization_failed
echo La construction ou l'initialisation de la base a echoue.
echo Verifiez les messages Docker ci-dessus et votre connexion Internet.
echo Une base existante n'est pas effacee. Ne supprimez aucun volume Docker.
goto failed

:startup_failed
echo L'application n'a pas confirme sa disponibilite dans le delai prevu.
echo Le port 8000 ou 55432 peut etre occupe, ou un service peut avoir echoue.
echo Diagnostic : docker compose --profile container logs --tail 80
echo Aucune suppression de donnees n'a ete demandee.
goto failed

:failed
echo.
echo Installation interrompue. Code d'erreur : %TVM_EXIT_CODE%
echo Corrigez le probleme indique, puis relancez INSTALLER_TVM.cmd.
echo La configuration existante et les donnees sont conservees.
echo.
pause

:finished
if "%TVM_DIR_PUSHED%"=="1" popd
endlocal & exit /b %TVM_EXIT_CODE%
