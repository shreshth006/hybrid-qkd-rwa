"""report.md -> styled .docx (A4, page border, numbered headings, boxed algorithms, numbered equations)."""
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PANDOC = os.environ.get("PANDOC") or shutil.which("pandoc") or "pandoc"
WORK = os.path.join(HERE, "build")
OUT = sys.argv[1]

BLUE = "2F5496"


def rezip(src_dir, dst):
    if os.path.exists(dst):
        os.remove(dst)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(src_dir):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, src_dir))


# ---------------------------------------------------------------- reference.docx with our styles
ref = os.path.join(WORK, "ref.docx")
subprocess.run([PANDOC, "-o", ref, "--print-default-data-file", "reference.docx"], check=True)
rdir = os.path.join(WORK, "ref_x")
shutil.rmtree(rdir, ignore_errors=True)
zipfile.ZipFile(ref).extractall(rdir)
sp = os.path.join(rdir, "word", "styles.xml")
st = open(sp, encoding="utf-8").read()

FONT = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="Times New Roman" w:cs="Times New Roman"/>'


def restyle(xml, style_id, ppr="", rpr=""):
    """Replace pPr/rPr of an existing paragraph style, or append a new style."""
    pat = re.compile(r'(<w:style [^>]*w:styleId="%s"[^>]*>)(.*?)(</w:style>)' % style_id, re.S)
    m = pat.search(xml)
    if not m:
        raise KeyError(style_id)
    inner = m.group(2)
    inner = re.sub(r"<w:pPr>.*?</w:pPr>|<w:pPr/>", "", inner, flags=re.S)
    inner = re.sub(r"<w:rPr>.*?</w:rPr>|<w:rPr/>", "", inner, flags=re.S)
    inner += (f"<w:pPr>{ppr}</w:pPr>" if ppr else "") + (f"<w:rPr>{rpr}</w:rPr>" if rpr else "")
    return xml[:m.start()] + m.group(1) + inner + m.group(3) + xml[m.end():]


# document defaults: Times New Roman 11 pt
st = re.sub(r"<w:rPrDefault>.*?</w:rPrDefault>",
            f'<w:rPrDefault><w:rPr>{FONT}<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault>',
            st, flags=re.S)
body = '<w:spacing w:before="0" w:after="120" w:line="264" w:lineRule="auto"/><w:jc w:val="both"/>'
st = restyle(st, "BodyText", body, f'{FONT}<w:sz w:val="22"/>')
st = restyle(st, "FirstParagraph", body, f'{FONT}<w:sz w:val="22"/>')
st = restyle(st, "Compact", '<w:spacing w:before="10" w:after="10"/>', f'{FONT}<w:sz w:val="16"/><w:szCs w:val="16"/>')
st = restyle(st, "Title", '<w:spacing w:before="240" w:after="240"/><w:jc w:val="center"/>',
             f'{FONT}<w:b/><w:color w:val="{BLUE}"/><w:sz w:val="34"/><w:szCs w:val="34"/>')
st = restyle(st, "Heading1",
             f'<w:keepNext/><w:spacing w:before="320" w:after="120"/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="2" w:color="{BLUE}"/></w:pBdr><w:outlineLvl w:val="0"/>',
             f'{FONT}<w:b/><w:color w:val="{BLUE}"/><w:sz w:val="30"/><w:szCs w:val="30"/>')
st = restyle(st, "Heading2", '<w:keepNext/><w:spacing w:before="220" w:after="100"/><w:outlineLvl w:val="1"/>',
             f'{FONT}<w:b/><w:u w:val="single"/><w:color w:val="000000"/><w:sz w:val="24"/><w:szCs w:val="24"/>')
st = restyle(st, "ImageCaption", '<w:spacing w:before="60" w:after="200"/><w:jc w:val="center"/>',
             f'{FONT}<w:i/><w:sz w:val="20"/>')
st = restyle(st, "TableCaption", '<w:keepNext/><w:spacing w:before="200" w:after="80"/><w:jc w:val="center"/>',
             f'{FONT}<w:i/><w:sz w:val="20"/>')
st = st.replace("</w:styles>", f'''<w:style w:type="paragraph" w:customStyle="1" w:styleId="Algorithm"><w:name w:val="Algorithm"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:pBdr><w:top w:val="single" w:sz="6" w:space="4" w:color="{BLUE}"/><w:left w:val="single" w:sz="6" w:space="4" w:color="{BLUE}"/><w:bottom w:val="single" w:sz="6" w:space="4" w:color="{BLUE}"/><w:right w:val="single" w:sz="6" w:space="4" w:color="{BLUE}"/></w:pBdr>
<w:keepNext/><w:keepLines/><w:shd w:val="clear" w:color="auto" w:fill="EEF2F8"/><w:spacing w:before="0" w:after="40" w:line="252" w:lineRule="auto"/><w:ind w:left="113" w:right="113"/></w:pPr>
<w:rPr>{FONT}<w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style></w:styles>''')
open(sp, "w", encoding="utf-8").write(st)
rezip(rdir, ref)

# ---------------------------------------------------------------- pandoc
raw = os.path.join(WORK, "raw.docx")
subprocess.run([PANDOC, "report.md", "-f", "markdown", "-t", "docx", "--number-sections",
                "--reference-doc", ref, "--resource-path", WORK, "-o", raw], cwd=WORK, check=True)

# ---------------------------------------------------------------- post-processing
ddir = os.path.join(WORK, "doc_x")
shutil.rmtree(ddir, ignore_errors=True)
zipfile.ZipFile(raw).extractall(ddir)
dp = os.path.join(ddir, "word", "document.xml")
d = open(dp, encoding="utf-8").read()

# 1. Numbered display equations: wrap each display-math paragraph in an invisible 3-column table.
TEXTW = 9638      # A4 minus 2 cm margins, in twips
SIDE = 900
paras = list(re.finditer(r"<w:p>(?:(?!</w:p>).)*?<m:oMathPara>.*?</w:p>", d, re.S))
nob = "".join(f'<w:{b} w:val="nil"/>' for b in ("top", "left", "bottom", "right", "insideH", "insideV"))


def cell(w, inner):
    return f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>{inner}</w:tc>'


out, last = [], 0
for i, mm in enumerate(paras, 1):
    tbl = (f'<w:tbl><w:tblPr><w:tblW w:w="{TEXTW}" w:type="dxa"/><w:jc w:val="center"/><w:tblBorders>{nob}</w:tblBorders>'
           f'<w:tblLayout w:type="fixed"/><w:tblCellMar><w:left w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar></w:tblPr>'
           f'<w:tblGrid><w:gridCol w:w="{SIDE}"/><w:gridCol w:w="{TEXTW - 2 * SIDE}"/><w:gridCol w:w="{SIDE}"/></w:tblGrid><w:tr>'
           + cell(SIDE, "<w:p/>") + cell(TEXTW - 2 * SIDE, mm.group(0))
           + cell(SIDE, f'<w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:t>({i})</w:t></w:r></w:p>')
           + "</w:tr></w:tbl>")
    out += [d[last:mm.start()], tbl]
    last = mm.end()
out.append(d[last:])
d = "".join(out)
n_eq = len(paras)

# 2. Borders on data tables (pandoc tables carry the "Table" style; equation tables have tblBorders already).
border = "".join(f'<w:{b} w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
                 for b in ("top", "left", "bottom", "right", "insideH", "insideV"))
d = re.sub(r'(<w:tblPr><w:tblStyle w:val="Table"/>)', r'\1<w:tblBorders>' + border + '</w:tblBorders>', d)

# 3. A4 page, 2 cm margins, double-line page border.
sect = ('<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
        'w:header="567" w:footer="567" w:gutter="0"/>'
        '<w:pgBorders w:offsetFrom="page">' + "".join(
            f'<w:{s} w:val="double" w:sz="6" w:space="24" w:color="{BLUE}"/>' for s in ("top", "left", "bottom", "right"))
        + '</w:pgBorders>')
i = d.rindex("<w:sectPr")
j = d.index(">", i) + 1
k = d.find("</w:footnotePr>", j)
pos = k + len("</w:footnotePr>") if k != -1 and k < d.index("</w:sectPr>", j) else j
d = d[:pos] + sect + d[pos:]

open(dp, "w", encoding="utf-8").write(d)
rezip(ddir, OUT)
print(f"wrote {OUT} ({n_eq} numbered equations)")
