@echo off
setlocal

set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\resources\bin\docker.exe"
set "DOCKER_CMD=docker"

where docker >nul 2>nul
if not errorlevel 1 goto docker_found
if exist "%DOCKER_EXE%" (
  set "DOCKER_CMD=%DOCKER_EXE%"
  goto docker_found
)

echo Docker CLI not found. Install Docker Desktop first. 1>&2
exit /b 1

:docker_found
%DOCKER_CMD% info >nul 2>nul
if errorlevel 1 (
  echo Docker daemon is not running. Start Docker Desktop first. 1>&2
  exit /b 1
)

set "NGINX_RUNNING="
for /f "usebackq delims=" %%s in (`%DOCKER_CMD% compose ps --services --filter status=running 2^>nul`) do (
  if /i "%%s"=="nginx" set "NGINX_RUNNING=1"
)

if defined NGINX_RUNNING (
  echo Docker Compose app is already running.
  exit /b 0
)

echo Starting Docker Compose services...
%DOCKER_CMD% compose up -d --build
exit /b %errorlevel%
