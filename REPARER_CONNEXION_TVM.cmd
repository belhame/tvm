@echo off
setlocal EnableExtensions DisableDelayedExpansion
title TVM PowerCare - Reparation de la connexion
set "TVM_DIR_PUSHED=0"
set "TVM_EXIT_CODE=0"
set "TVM_WRITERS_PAUSED=0"
set "TVM_CONNECTION_SAFE=1"
set "TVM_RESUME_SERVICES="
pushd "%~dp0"
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto folder_failed
set "TVM_DIR_PUSHED=1"

echo.
echo TVM PowerCare - Reparation de la connexion PostgreSQL
echo Une sauvegarde sera copiee sur ce PC avant tout changement de connexion.
echo Les dossiers, les comptes TVM et leurs mots de passe sont conserves.
echo.
if not exist "compose.yaml" goto files_missing
if not exist "scripts\check_database_connection.py" goto files_missing
if not exist "scripts\repair_database.sh" goto files_missing
if not exist ".env" goto configuration_missing
where docker >nul 2>&1
if errorlevel 1 goto docker_not_ready
docker info >nul 2>&1
if errorlevel 1 goto docker_not_ready
docker compose version >nul 2>&1
if errorlevel 1 goto docker_not_ready
set "TVM_DOCKER_OS="
for /f "tokens=1" %%O in ('docker info --format "{{.OSType}}" 2^>nul') do set "TVM_DOCKER_OS=%%O"
if /i not "%TVM_DOCKER_OS%"=="linux" goto docker_not_ready

echo [1/4] Verification de la connexion avec la configuration de ce dossier...
docker compose up -d --wait --wait-timeout 90 db
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto database_not_ready
docker compose --profile container run --rm --no-deps --pull never --user "0:0" --entrypoint python --volume "%CD%\scripts:/tvm-repair:ro" web /tvm-repair/check_database_connection.py
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if "%TVM_EXIT_CODE%"=="0" goto already_connected
if not "%TVM_EXIT_CODE%"=="10" goto diagnostic_failed

echo.
echo [2/4] Sauvegarde de la base et de la configuration avant reparation...
call :pause_writers
if errorlevel 1 goto backup_failed
if not exist ".local\backups" mkdir ".local\backups"
if not exist ".local\backups" goto backup_failed
:choose_backup_name
set "TVM_REPAIR_FOLDER=.local\backups\avant-connexion-%RANDOM%-%RANDOM%"
if exist "%TVM_REPAIR_FOLDER%" goto choose_backup_name
mkdir "%TVM_REPAIR_FOLDER%"
if errorlevel 1 goto backup_failed
copy /b ".env" "%TVM_REPAIR_FOLDER%\configuration.env" >nul
if errorlevel 1 goto backup_failed
docker compose cp "scripts/repair_database.sh" db:/tmp/tvm-repair-database.sh
if errorlevel 1 goto backup_failed
docker compose exec -T db sh /tmp/tvm-repair-database.sh backup
if errorlevel 1 goto backup_failed
docker compose cp db:/tmp/tvm-connection-repair/database.dump "%TVM_REPAIR_FOLDER%\database.dump"
if errorlevel 1 goto backup_failed
docker compose cp db:/tmp/tvm-connection-repair/database.dump.sha256 "%TVM_REPAIR_FOLDER%\database.dump.sha256"
if errorlevel 1 goto backup_failed
if not exist "%TVM_REPAIR_FOLDER%\database.dump" goto backup_failed
for %%F in ("%TVM_REPAIR_FOLDER%\database.dump") do if %%~zF LSS 1 goto backup_failed
docker run --rm --volume "%CD%\%TVM_REPAIR_FOLDER%:/backups:ro" --workdir /backups postgres:16-alpine sha256sum -c database.dump.sha256 >nul 2>&1
if errorlevel 1 goto backup_failed
docker run --rm --volume "%CD%\%TVM_REPAIR_FOLDER%:/backups:ro" postgres:16-alpine pg_restore --list /backups/database.dump >nul 2>&1
if errorlevel 1 goto backup_failed

echo.
echo [3/4] Alignement de la connexion avec la configuration locale...
set "TVM_CONNECTION_SAFE=0"
docker compose exec -T db sh /tmp/tvm-repair-database.sh apply
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto repair_failed

echo.
echo [4/4] Verification du mot de passe de connexion sur le reseau Docker...
docker compose --profile container run --rm --no-deps --pull never --user "0:0" --entrypoint python --volume "%CD%\scripts:/tvm-repair:ro" web /tvm-repair/check_database_connection.py
set "TVM_EXIT_CODE=%ERRORLEVEL%"
if not "%TVM_EXIT_CODE%"=="0" goto verification_failed
echo.
set "TVM_CONNECTION_SAFE=1"
echo Reparation terminee. La connexion PostgreSQL fonctionne.
echo Sauvegarde conservee sur ce PC : %TVM_REPAIR_FOLDER%\database.dump
echo Fermez cette fenetre, puis relancez INSTALLER_TVM.cmd dans CE dossier.
echo Les acces aux comptes TVM restent ceux de votre installation precedente.
goto success

:already_connected
echo.
echo La connexion PostgreSQL fonctionne deja. Aucun mot de passe n'a ete change.
echo Relancez INSTALLER_TVM.cmd dans CE dossier.
goto success

:folder_failed
echo Impossible d'ouvrir le dossier TVM.
goto failed

:files_missing
set "TVM_EXIT_CODE=2"
echo Fichiers de reparation manquants.
echo Copiez REPARER_CONNEXION_TVM.cmd et le dossier scripts de la version corrigee
echo dans le dossier TVM qui contient votre configuration .env.
goto failed

:configuration_missing
set "TVM_EXIT_CODE=2"
echo Le fichier .env manque dans ce dossier. Aucune configuration n'est generee.
echo Utilisez le dossier TVM ou INSTALLER_TVM.cmd a affiche le refus de connexion.
goto failed

:docker_not_ready
set "TVM_EXIT_CODE=1"
echo Ouvrez Docker Desktop et attendez que son moteur Linux soit pret.
goto failed

:database_not_ready
echo PostgreSQL n'est pas disponible. Aucune reparation de mot de passe effectuee.
goto failed

:diagnostic_failed
echo Le diagnostic ne confirme pas un simple refus de mot de passe.
echo Aucune reparation de mot de passe effectuee. Conservez le message ci-dessus.
echo Si l'image web manque, relancez INSTALLER_TVM.cmd avant ce reparateur.
goto failed

:backup_failed
set "TVM_EXIT_CODE=5"
echo La sauvegarde n'a pas pu etre copiee et verifiee sur ce PC.
echo Le mot de passe de PostgreSQL n'a pas ete change par le reparateur.
goto failed

:repair_failed
echo La reparation ne peut pas etre confirmee. Conservez les messages ci-dessus.
echo La sauvegarde est conservee dans .local\backups. Ne supprimez aucun volume.
goto failed

:verification_failed
echo La verification de connexion n'a pas abouti. Ne relancez pas au hasard.
echo La sauvegarde est conservee dans .local\backups. Conservez les messages ci-dessus.
goto failed

:success
call :resume_writers
set "TVM_EXIT_CODE=0"
echo.
pause
goto finished

:failed
call :resume_writers
if "%TVM_EXIT_CODE%"=="0" set "TVM_EXIT_CODE=1"
echo.
echo Reparation interrompue. Code : %TVM_EXIT_CODE%
echo Aucun volume ni dossier TVM n'a ete supprime.
echo.
pause
goto finished

:pause_writers
docker compose --profile container ps --status running --services >nul
if errorlevel 1 exit /b 1
for /f "delims=" %%S in ('docker compose --profile container ps --status running --services') do call :remember_writer "%%S"
if not defined TVM_RESUME_SERVICES exit /b 0
set "TVM_WRITERS_PAUSED=1"
docker compose --profile container stop %TVM_RESUME_SERVICES%
exit /b %ERRORLEVEL%

:remember_writer
if "%~1"=="reminders" set "TVM_RESUME_SERVICES=reminders %TVM_RESUME_SERVICES%"
if "%~1"=="web" set "TVM_RESUME_SERVICES=%TVM_RESUME_SERVICES% web"
exit /b 0

:resume_writers
if not "%TVM_WRITERS_PAUSED%"=="1" exit /b 0
if not "%TVM_CONNECTION_SAFE%"=="1" goto writers_stay_paused
docker compose --profile container start --wait --wait-timeout 90 %TVM_RESUME_SERVICES%
if errorlevel 1 echo Relancez DEMARRER_TVM.cmd pour redemarrer les services arretes.
set "TVM_WRITERS_PAUSED=0"
exit /b 0

:writers_stay_paused
echo Le site et les rappels restent en pause car la connexion n'est pas verifiee.
echo Relancez INSTALLER_TVM.cmd apres correction de la connexion.
exit /b 0

:finished
if "%TVM_DIR_PUSHED%"=="1" popd
endlocal & exit /b %TVM_EXIT_CODE%
