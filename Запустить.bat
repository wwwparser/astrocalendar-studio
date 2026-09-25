@echo off
rem Запуск AstroCalendar Studio из исходников двойным щелчком.
rem Окно консоли остаётся открытым, если что-то пошло не так, — иначе
rem сообщение об ошибке исчезает вместе с окном и человек видит только
rem мигнувший чёрный прямоугольник.
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo На компьютере не найден Python.
    echo Установите его с https://www.python.org/downloads/
    echo При установке отметьте галочку "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

python run.py
if errorlevel 1 (
    echo.
    pause
)
