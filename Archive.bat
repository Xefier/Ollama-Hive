@echo off
REM Set the paths
set SOURCE_FOLDER=ollama-hive
set OUTPUT_FILE=ollama-hive.tar.gz
set SEVEN_ZIP_PATH="C:\Program Files\7-Zip\7z.exe"

REM Check if 7-Zip is installed
if not exist %SEVEN_ZIP_PATH% (
    echo 7-Zip not found at %SEVEN_ZIP_PATH%. Please install 7-Zip or update the path.
    exit /b 1
)

REM Create a tar archive
echo Creating TAR archive...
%SEVEN_ZIP_PATH% a -ttar %SOURCE_FOLDER%.tar %SOURCE_FOLDER%\*

REM Compress the tar archive to gzip
echo Compressing TAR to GZ...
%SEVEN_ZIP_PATH% a -tgzip %OUTPUT_FILE% %SOURCE_FOLDER%.tar

REM Clean up the intermediate .tar file
echo Cleaning up...
del %SOURCE_FOLDER%.tar

echo Compression complete: %OUTPUT_FILE%
