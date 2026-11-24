@echo off
setlocal

rem ------------------------------------------------------------
rem  archimatemcp.bat - install and run the ArchiMate MCP server
rem
rem  Usage:
rem    archimatemcp.bat install                      create .venv, install packages, .env, check the API
rem    archimatemcp.bat deploy C:\Apps\ArchiMateMCP [start]
rem                                                     from an unzipped package: install into that folder,
rem                                                     or update the installation there (deploy.ps1)
rem    archimatemcp.bat start                        serve MCP clients over HTTP (HOST/PORT from .env)
rem    archimatemcp.bat stdio                        serve one MCP client over stdin/stdout (for trying it;
rem                                                     MCP clients start run_server.py themselves)
rem    archimatemcp.bat check                        does the ArchiMate API answer, and take the key?
rem    archimatemcp.bat config                       print how to add the server to Claude Desktop and
rem                                                     Claude Code
rem
rem  The script may sit in the project folder or next to it (in the folder
rem  that holds ArchiMateMCP\).
rem
rem  Settings come from .env (see .env.example): API_URL and API_KEY of the
rem  ArchiMate API, HOST, PORT and MCP_TOKEN of the HTTP transport.
rem ------------------------------------------------------------

set "ACTION=%~1"
set "FILE=%~f2"

rem Find the project folder: this folder, or ArchiMateMCP\ next to the script
set "ROOT=%~dp0"
if not exist "%ROOT%run_server.py" if exist "%~dp0ArchiMateMCP\run_server.py" set "ROOT=%~dp0ArchiMateMCP\"
if not exist "%ROOT%run_server.py" (
    echo ERROR: Could not find the ArchiMateMCP folder or run_server.py.
    exit /b 1
)
cd /d "%ROOT%"

if "%ACTION%"=="" goto :usage
if /i "%ACTION%"=="help" goto :usage
if /i "%ACTION%"=="install" goto :do_install
if /i "%ACTION%"=="deploy" goto :do_deploy
if /i "%ACTION%"=="start" goto :do_start
if /i "%ACTION%"=="stdio" goto :do_stdio
if /i "%ACTION%"=="check" goto :do_check
if /i "%ACTION%"=="config" goto :do_config
echo ERROR: Unknown command: %ACTION%
echo.
goto :usage

rem ============================================================
:do_install
if not exist ".venv\Scripts\activate.bat" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :install_failed
) else (
    echo [1/4] Virtual environment already exists, skipping.
)

echo [2/4] Installing dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :install_failed

rem Never overwrite an existing .env
if exist ".env" goto :install_env_kept
echo [3/4] Creating .env from .env.example...
copy .env.example .env >nul
if errorlevel 1 goto :install_failed
echo.
echo  IMPORTANT: set API_URL and API_KEY in .env: the address of the ArchiMate API
echo  and a key of it (the role reader is enough).
echo  Opening .env in Notepad - save and close it to continue.
echo.
notepad .env
goto :install_check
:install_env_kept
echo [3/4] .env already exists, leaving it untouched.

:install_check
echo [4/4] Checking the ArchiMate API...
.venv\Scripts\python.exe run_server.py check
if errorlevel 1 (
    echo.
    echo The server is installed, but cannot use the API yet: fix API_URL / API_KEY in .env,
    echo start the API, and run "%~nx0 check" again.
)
echo.
echo Installation complete. To add the server to Claude Desktop or Claude Code:
echo.
.venv\Scripts\python.exe run_server.py config
exit /b 0

:install_failed
echo.
echo Installation failed. See the messages above.
pause
exit /b 1

rem ============================================================
:do_deploy
rem Install into a fixed folder, or update the installation there, from this
rem package: backup, files, packages. See deploy.ps1.
if "%~2"=="" goto :usage
set "TARGET=%FILE%"
if "%TARGET:~-1%"=="\" set "TARGET=%TARGET:~0,-1%"
set "DEPLOY_START="
if /i "%~3"=="start" set "DEPLOY_START=-Start"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%deploy.ps1" -Target "%TARGET%" %DEPLOY_START%
exit /b %errorlevel%

rem ============================================================
:do_start
rem HTTP: http://HOST:PORT/mcp; for a loopback HOST on 127.0.0.1 and ::1.
call :python || exit /b 1
"%PY%" run_server.py http
exit /b %errorlevel%

rem ============================================================
:do_stdio
call :python || exit /b 1
"%PY%" run_server.py stdio
exit /b %errorlevel%

rem ============================================================
:do_check
call :python || exit /b 1
"%PY%" run_server.py check
exit /b %errorlevel%

rem ============================================================
:do_config
call :python || exit /b 1
"%PY%" run_server.py config
exit /b %errorlevel%

rem ============================================================
rem  Helpers
rem ============================================================

:python
rem The project's .venv; without one, the Python on the PATH if it has the packages
if exist ".venv\Scripts\python.exe" (
    set "PY=%ROOT%.venv\Scripts\python.exe"
    exit /b 0
)
python -c "import mcp, pydantic_settings, uvicorn" 2>nul
if errorlevel 1 (
    echo ERROR: Virtual environment not found. Run "%~nx0 install" first.
    exit /b 1
)
set "PY=python"
exit /b 0

:usage
echo Usage:
echo   %~nx0 install                       create .venv, install packages, create .env, check the API
echo   %~nx0 deploy folder [start]         from an unzipped package: install into that folder, or update
echo                                       the installation there ^(backup, files, packages^)
echo   %~nx0 start                         serve MCP clients over HTTP, at http://HOST:PORT/mcp
echo   %~nx0 stdio                         serve one MCP client over stdin/stdout
echo   %~nx0 check                         check that the ArchiMate API answers and takes the key
echo   %~nx0 config                        print how to add the server to Claude Desktop and Claude Code
echo.
echo   Settings come from .env: API_URL and API_KEY of the ArchiMate API;
echo   HOST, PORT and MCP_TOKEN of the HTTP transport.
exit /b 1
