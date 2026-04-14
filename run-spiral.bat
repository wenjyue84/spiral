@echo off
cd /d "C:\Users\Jyue\Documents\1-projects\Software Projects\Spiral"
set SPIRAL_MEMORY_WATCHDOG=0
"C:\Program Files\Git\bin\bash.exe" --login -c "cd '/c/Users/Jyue/Documents/1-projects/Software Projects/Spiral' && SPIRAL_MEMORY_WATCHDOG=0 bash spiral.sh 9999 --gate proceed >> spiral-run.log 2>&1"
