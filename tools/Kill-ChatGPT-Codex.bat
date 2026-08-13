@echo off
title Vastgelopen ChatGPT of Codex afsluiten
color 0B

echo.
echo  ==============================================
echo   Vastgelopen ChatGPT of Codex afsluiten
echo  ==============================================
echo.
echo   1. Alleen ChatGPT afsluiten
echo   2. Alleen Codex afsluiten
echo   3. ChatGPT en Codex afsluiten
echo   4. Annuleren
echo.
choice /C 1234 /N /M "Maak een keuze [1-4]: "

if errorlevel 4 goto :cancel
if errorlevel 3 goto :both
if errorlevel 2 goto :codex
if errorlevel 1 goto :chatgpt

:chatgpt
taskkill /F /IM ChatGPT.exe /T >nul 2>&1
if errorlevel 1 (
  echo.
  echo ChatGPT draaide niet of kon niet worden afgesloten.
) else (
  echo.
  echo ChatGPT is afgesloten.
)
goto :done

:codex
echo.
echo Let op: Codex wordt nu direct afgesloten.
timeout /t 2 /nobreak >nul
taskkill /F /IM Codex.exe /T >nul 2>&1
goto :eof

:both
taskkill /F /IM ChatGPT.exe /T >nul 2>&1
echo.
echo ChatGPT is afgesloten of draaide niet.
echo Codex wordt over 2 seconden afgesloten.
timeout /t 2 /nobreak >nul
taskkill /F /IM Codex.exe /T >nul 2>&1
goto :eof

:cancel
echo.
echo Geannuleerd. Er is niets afgesloten.

:done
echo.
pause
