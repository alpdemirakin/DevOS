@echo off
echo Starting DevOS Build Process...
if not exist output mkdir output
docker build -t devos-builder .
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Docker build failed. Ensure Docker Desktop is running.
    pause
    exit /b %ERRORLEVEL%
)

echo Running DevOS Builder...
docker run --rm -v "%cd%":/build devos-builder /build/build_scripts/generate_iso.sh
if %ERRORLEVEL% neq 0 (
    echo [ERROR] ISO Generation failed inside container. check build_scripts/generate_iso.sh
    pause
    exit /b %ERRORLEVEL%
)

echo Build Complete! Check output/devos.iso
dir output\devos.iso
pause
