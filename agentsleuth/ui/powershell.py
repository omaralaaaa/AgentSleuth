"""Display-only PowerShell token colors, adapted for the dark transcript."""

import ntpath
import re


COLORS = {
    'command': '#f0d88a', 'parameter': '#b2b6bf', 'string': '#78c7cb',
    'variable': '#91cf91', 'comment': '#82a87a', 'keyword': '#94b8ed',
    'number': '#c6a5dc', 'operator': '#aeb6c3',
}
KEYWORDS = frozenset('if elseif else foreach for while do switch function param '
                     'return try catch finally throw break continue in begin process end'.split())
TOKENS = re.compile(r"""
    (?P<comment>\#[^\n]*|<\#[\s\S]*?(?:\#>|\Z))
  | (?P<string>'(?:''|[^'])*(?:'|\Z)|"(?:`[\s\S]|[^"`])*(?:"|`?\Z))
  | (?P<variable>\$(?:\{[^}\n]*\}|[\w:]+|[?^$]))
  | (?P<parameter>-(?:[A-Za-z][\w-]*))
  | (?P<number>\b(?:0x[\da-fA-F]+|\d+(?:\.\d+)?)\b)
  | (?P<word>[\w.\\/:~-]+)
  | (?P<operator>[|;&={}()])
  | (?P<newline>\n)
  | (?P<escaped>`[\s\S])
""", re.VERBOSE)


def is_powershell(argv, text):
    if isinstance(argv, list) and argv:
        executable = ntpath.basename(str(argv[0]).strip('"')).lower()
        if executable.removesuffix('.exe') in {'pwsh', 'powershell'}:
            return True
        if len(argv) > 1:
            return False
    if re.match(r'\s*(?:&\s*)?(?:"[^"\r\n]*[\\/])?(?:powershell|pwsh)(?:\.exe)?(?=["\s]|$)', text, re.I):
        return True
    return bool(re.search(
        r'(?:^|[|;\n({=])\s*(?:(?:Get|Set|New|Remove|Copy|Move|Rename|Select|Where|ForEach|'
        r'Write|Read|Test|Invoke|Import|Export|ConvertTo|ConvertFrom|Start|Stop|Out|Sort|'
        r'Format|Join|Split|Resolve|Measure|Add|Clear|Push|Pop)-[A-Za-z]\w*\b|\$[\w:]+\s*=)'
        r'|\$env:[a-z_]\w*', text, re.I))


def command_parts(text, *, tokens=TOKENS, keywords=KEYWORDS, separators='|;&({='):
    # Insert tagged spans directly so offsets work for Unicode on every Tk build.
    parts = []
    pos = 0
    command_position = True
    for token in tokens.finditer(text):
        kind, value = token.lastgroup, token.group()
        if token.start() > pos:
            parts.extend((text[pos:token.start()], ()))
        if kind == 'word':
            kind = 'keyword' if value.lower() in keywords else 'command' if command_position else None
        parts.extend((value, (kind,) if kind in COLORS else ()))
        command_position = kind == 'newline' or (kind == 'operator' and value in separators)
        pos = token.end()
    if pos < len(text):
        parts.extend((text[pos:], ()))
    return parts


def insert_command(widget, text, parts=None):
    for name, color in COLORS.items():
        widget.tag_configure(name, foreground=color)
    if parts is None:
        parts = command_parts(text)
    if parts:
        widget.insert('1.0', *parts)
