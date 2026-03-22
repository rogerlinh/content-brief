import sys
lines = open('test_results.txt', 'r', encoding='utf-8').readlines()
for i, line in enumerate(lines):
    sys.stdout.buffer.write((f"{i:3d}| {line}").encode('utf-8'))
