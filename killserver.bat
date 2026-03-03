@echo off
setlocal

set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\resources\bin\docker.exe"

where docker >nul 2>nul
if not errorlevel 1 goto run_path_docker
if exist "%DOCKER_EXE%" goto run_fallback_docker

echo Docker CLI not found. Install Docker Desktop first. 1>&2
exit /b 1

:run_path_docker
docker compose down -v
exit /b %errorlevel%

:run_fallback_docker
"%DOCKER_EXE%" compose down -v
exit /b %errorlevel%
