import subprocess
with open('ruff_output.txt', 'w', encoding='utf-8') as f:
    subprocess.run(['ruff', 'check', '.'], stdout=f, stderr=subprocess.STDOUT)
