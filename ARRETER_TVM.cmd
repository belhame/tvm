@echo off
setlocal EnableExtensions DisableDelayedExpansion
title TVM PowerCare - Arret
set "TVM_DIR_PUSHED=0"
set "TVM_EXIT_CODE=0"
pushd "%~dp0"
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto folder_failed
set "TVM_DIR_PUSHED=1"

echo.
echo TVM PowerCare - Arret sans effacer les donnees
echo.
if not exist "compose.yaml" goto files_missing
if not exist ".env" goto not_installed
where docker >nul 2>&1
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto docker_missing
docker info >nul 2>&1
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto docker_not_ready
docker compose version >nul 2>&1
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto compose_missing
set "TVM_DOCKER_OS="
for /f "tokens=1" %%O in ('docker info --format "{{.OSType}}" 2^>nul') do set "TVM_DOCKER_OS=%%O"
if not defined TVM_DOCKER_OS goto docker_mode_unknown
echo Moteur Docker detecte : "%TVM_DOCKER_OS%"
if /i "%TVM_DOCKER_OS%"=="linux" goto docker_linux_ready
if /i "%TVM_DOCKER_OS%"=="windows" goto linux_required
goto docker_mode_unknown

:docker_linux_ready
set "TVM_EXIT_CODE=0"

docker compose --profile container stop
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto stop_failed

echo.
echo Application et base arretees. Les donnees et les comptes sont conserves.
echo Pour reprendre, ouvrez Docker Desktop puis DEMARRER_TVM.cmd.
echo.
pause
goto finished

:folder_failed
echo Impossible d'ouvrir le dossier de l'application.
goto failed

:files_missing
set "TVM_EXIT_CODE=2"
echo Le fichier compose.yaml manque. Ne deplacez pas ce script seul.
goto failed

:not_installed
set "TVM_EXIT_CODE=2"
echo Aucune configuration .env dans ce dossier.
echo Utilisez le dossier dans lequel TVM a ete installe.
goto failed

:docker_missing
echo Docker Desktop est introuvable.
goto failed

:docker_not_ready
echo Docker ne repond pas. Ouvrez Docker Desktop pour arreter ses services.
echo Si Docker Desktop est ferme, l'application est deja inaccessible.
goto failed

:compose_missing
echo Docker Compose est indisponible. Mettez Docker Desktop a jour.
goto failed

:linux_required
set "TVM_EXIT_CODE=1"
echo Le moteur Docker a indique le mode Windows.
echo Dans la zone de notification Windows, clic droit sur l'icone baleine Docker.
echo Choisissez "Switch to Linux containers..." si cette option est proposee.
echo Attendez que le moteur soit pret, puis relancez ce script.
echo Aucun changement de moteur n'est effectue automatiquement.
goto failed

:docker_mode_unknown
set "TVM_EXIT_CODE=1"
echo Impossible d'identifier le mode du moteur Docker.
echo Une sortie absente ou inconnue ne signifie pas que le moteur est en mode Windows.
echo Dans un terminal, executez cette commande et conservez son resultat :
echo docker info --format "{{.OSType}}"
echo Resultat attendu : linux. Si une erreur s'affiche, conservez aussi son message.
echo Ne changez pas le mode du moteur sans avoir verifie ce resultat.
goto failed

:stop_failed
echo L'arret des services n'a pas pu etre confirme.
echo Diagnostic : docker compose --profile container ps
goto failed

:failed
echo.
echo Arret non confirme. Code d'erreur : %TVM_EXIT_CODE%
echo Aucune suppression de donnees n'a ete demandee.
echo.
pause

:finished
if "%TVM_DIR_PUSHED%"=="1" popd
endlocal & exit /b %TVM_EXIT_CODE%
