import zipfile
import xml.etree.ElementTree as ET

def read_docx(path):
    with zipfile.ZipFile(path) as docx:
        content = docx.read('word/document.xml')
    tree = ET.fromstring(content)
    namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    text = []
    for paragraph in tree.iterfind('.//w:p', namespaces):
        para_text = "".join(node.text for node in paragraph.iterfind('.//w:t', namespaces) if node.text)
        text.append(para_text)
    return "\n".join(text)

with open('Audit_V15_SemanticSEO.md', 'w', encoding='utf-8') as f:
    f.write(read_docx(r'd:\antigravity\content brief\Audit_V11_SemanticSEO_KorayFramework.docx'))
