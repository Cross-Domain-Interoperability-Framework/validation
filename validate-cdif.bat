@echo off
REM CDIF JSON-LD Validation Script for oXygen XML Editor
REM
REM Usage: validate-cdif.bat <input-file.jsonld> [options]
REM
REM Options:
REM   --framed     Save framed output alongside input file
REM   --legacy     Use legacy schema (pre-2026)
REM   --help       Show help
REM
REM In oXygen External Tools:
REM   Command: C:\Users\smrTu\OneDrive\Documents\GithubC\CDIF\validation\validate-cdif.bat
REM   Arguments: "${cf}"
REM   Working directory: (leave empty)

setlocal enabledelayedexpansion

REM Get the directory where this script is located
set "SCRIPT_DIR=%~dp0"

REM Use miniconda Python which has pyld installed
REM Change this path if your Python with pyld is elsewhere
set "PYTHON=C:\Users\smrTu\miniconda3\python.exe"

REM Fallback to system python if miniconda not found
if not exist "%PYTHON%" (
    set "PYTHON=python"
)

REM Default settings
set "INPUT_FILE="
set "SAVE_FRAMED=0"
set "USE_LEGACY=0"
set "SCHEMA=%SCRIPT_DIR%CDIFCompleteSchema.json"
set "FRAME=%SCRIPT_DIR%CDIF-frame-2026.jsonld"

REM Parse arguments
:parse_args
if "%~1"=="" goto :done_parsing
if /i "%~1"=="--framed" (
    set "SAVE_FRAMED=1"
    shift
    goto :parse_args
)
if /i "%~1"=="--legacy" (
    set "USE_LEGACY=1"
    set "SCHEMA=%SCRIPT_DIR%CDIF-JSONLD-schema-schemaprefix.json"
    set "FRAME=%SCRIPT_DIR%archive\CDIF-frame.jsonld"
    shift
    goto :parse_args
)
if /i "%~1"=="--help" (
    goto :show_help
)
if "%INPUT_FILE%"=="" (
    set "INPUT_FILE=%~1"
    shift
    goto :parse_args
)
shift
goto :parse_args

:done_parsing

REM Check if input file was provided
if "%INPUT_FILE%"=="" (
    echo Error: No input file specified
    echo.
    goto :show_help
)

REM Check if input file exists
if not exist "%INPUT_FILE%" (
    echo Error: Input file not found: %INPUT_FILE%
    exit /b 1
)

REM Get input file directory and name for framed output
for %%F in ("%INPUT_FILE%") do (
    set "INPUT_DIR=%%~dpF"
    set "INPUT_NAME=%%~nF"
)

echo ========================================
echo CDIF JSON-LD Validation
echo ========================================
echo Input:  %INPUT_FILE%
echo Schema: %SCHEMA%
echo Frame:  %FRAME%
echo ========================================
echo.

REM Build the command
set "CMD="%PYTHON%" "%SCRIPT_DIR%FrameAndValidate.py" "%INPUT_FILE%" --schema "%SCHEMA%" --frame "%FRAME%" -v"

if "%SAVE_FRAMED%"=="1" (
    set "FRAMED_OUTPUT=%INPUT_DIR%%INPUT_NAME%-framed.json"
    set "CMD=!CMD! -o "!FRAMED_OUTPUT!""
    echo Framed output will be saved to: !FRAMED_OUTPUT!
    echo.
)

REM Run validation
%CMD%

REM Capture exit code
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if %EXIT_CODE%==0 (
    echo ========================================
    echo VALIDATION SUCCESSFUL
    echo ========================================
) else (
    echo ========================================
    echo VALIDATION FAILED
    echo ========================================
)

exit /b %EXIT_CODE%

:show_help
echo CDIF JSON-LD Validation Script
echo.
echo Usage: validate-cdif.bat ^<input-file.jsonld^> [options]
echo.
echo Options:
echo   --framed     Save framed output alongside input file
echo   --legacy     Use legacy schema (pre-2026)
echo   --help       Show this help message
echo.
echo Examples:
echo   validate-cdif.bat my-metadata.jsonld
echo   validate-cdif.bat my-metadata.jsonld --framed
echo   validate-cdif.bat my-metadata.jsonld --legacy
echo.
echo oXygen External Tool Configuration:
echo   Command:   %~f0
echo   Arguments: "${currentFileURL}"
echo   Or:        "${currentFileURL}" --framed
echo.
exit /b 0
