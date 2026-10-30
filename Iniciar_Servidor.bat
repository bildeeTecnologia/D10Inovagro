@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERRO: O Python do ambiente virtual nao foi encontrado.
    echo Verifique se a pasta .venv existe nesta pasta do projeto.
    echo.
    pause
    exit /b 1
)

if not exist "manage.py" (
    echo ERRO: manage.py nao foi encontrado nesta pasta.
    echo Coloque este arquivo .bat na pasta principal do projeto.
    echo.
    pause
    exit /b 1
)

echo Iniciando o servidor Django...
echo Quando estiver pronto, acesse: http://127.0.0.1:8000/
echo Mantenha esta janela aberta enquanto estiver usando o sistema.
echo Para encerrar o servidor, pressione Ctrl+C.
echo.

".venv\Scripts\python.exe" manage.py runserver
set "exit_code=%ERRORLEVEL%"

echo.
echo O servidor foi encerrado. Codigo de saida: %exit_code%
pause
exit /b %exit_code%
