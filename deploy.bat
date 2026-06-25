@echo off
chcp 65001 >nul
cd /d %~dp0
echo === 대시보드 배포 시작 ===

REM 편집한 standalone 파일을 사이트가 띄우는 index.html 로 복사
copy /Y dashboard_standalone.html index.html >nul

git add -A
git commit -m "update dashboard"
git push

echo.
echo === 완료! 1~2분 뒤 사이트가 갱신됩니다 ===
echo https://andonggyu23.github.io/power/
pause
