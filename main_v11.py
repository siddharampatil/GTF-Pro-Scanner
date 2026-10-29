import os
import sys

print("GTF PRO SCANNER V11")
print("Python version:", sys.version)
print("Current folder:", os.getcwd())
print("Files available:", os.listdir("."))

required_files = [
    "strategy_v11.py",
    "stock_list.py",
]

for filename in required_files:
    if os.path.exists(filename):
        print(f"FOUND: {filename}")
    else:
        print(f"MISSING: {filename}")

print("Diagnostic completed.")