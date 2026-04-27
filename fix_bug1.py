import re

path = r'd:\antigravity\content brief\modules\markdown_exporter.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find and fix the join line
old_pattern = r'full_content = "\\\\n"\.join\(lines\)'
new_text = 'full_content = "\\n".join(lines)'

content_new = re.sub(old_pattern, new_text, content)

if content_new != content:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content_new)
    print("BUG-1 FIXED: literal backslash-n replaced with real newline")
else:
    # Try another pattern
    lines_list = content.split('\n')
    for i, line in enumerate(lines_list):
        if 'join(lines)' in line and 'full_content' in line:
            print(f"Line {i+1}: {repr(line)}")
            # Replace directly
            lines_list[i] = '    full_content = "\\n".join(lines)'
            print(f"Fixed to: {repr(lines_list[i])}")
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines_list))
            print("BUG-1 FIXED via line replacement")
            break
