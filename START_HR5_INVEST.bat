@echo off
title HR5 INVEST — Plateforme IA
color 0B
cls

echo.
echo  ██╗  ██╗██████╗ ███████╗    ██╗███╗   ██╗██╗   ██╗███████╗███████╗████████╗
echo  ██║  ██║██╔══██╗██╔════╝    ██║████╗  ██║██║   ██║██╔════╝██╔════╝╚══██╔══╝
echo  ███████║██████╔╝███████╗    ██║██╔██╗ ██║██║   ██║█████╗  ███████╗   ██║
echo  ██╔══██║██╔══██╗╚════██║    ██║██║╚██╗██║╚██╗ ██╔╝██╔══╝  ╚════██║   ██║
echo  ██║  ██║██║  ██║███████║    ██║██║ ╚████║ ╚████╔╝ ███████╗███████║   ██║
echo  ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝╚═╝  ╚═══╝  ╚═══╝  ╚══════╝╚══════╝   ╚═╝
echo.
echo  Plateforme d'investissement IA — hr5invest.com
echo  ================================================
echo.

cd /d "%~dp0"

:: ── Vérifier Python ───────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python introuvable. Installe Python 3.11+
    pause
    exit /b 1
)

:: ── Installer les dépendances si besoin ───────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo [INSTALL] Création de l'environnement virtuel...
    python -m venv venv
    echo [INSTALL] Installation des packages...
    call venv\Scripts\activate.bat
    pip install -r requirements.txt --quiet
    echo [OK] Installation terminée.
) else (
    call venv\Scripts\activate.bat
)

:: ── Créer les dossiers ────────────────────────────────────────
if not exist "data" mkdir data
if not exist "logs" mkdir logs

:: ── Lancer le serveur ─────────────────────────────────────────
echo [START] Démarrage de HR5 Invest API...
echo.
echo  URL : http://localhost:8000
echo  APP : http://localhost:8000
echo.
echo  Comptes demo:
echo    Admin : admin@hr5invest.com / Admin1234!
echo    Demo  : demo@hr5invest.com  / Demo1234!
echo.
echo  [Ctrl+C pour arreter]
echo  ================================================
echo.

:: Ouvrir le navigateur après 3 secondes
start /min cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

:: Lancer FastAPI
python backend\main.py

pause
