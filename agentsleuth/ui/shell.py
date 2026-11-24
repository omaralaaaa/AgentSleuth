"""Prepare recorded shell inputs for display."""

import re

from .powershell import command_parts, is_powershell


SHELL_TOOLS = {'bash', 'shell', 'powershell', 'pwsh', 'run_command', 'exec_command', 'shell_command'}
BASH_KEYWORDS = frozenset('if then elif else fi for while until do done case esac in function'.split())
BASH_SEPARATORS = frozenset(('&&', '||', '|', ';', '&', '(', '{'))
BASH_TOKENS = re.compile(r"""
    (?P<comment>(?<!\S)\#[^\n]*)
  | (?P<string>'[^']*(?:'|\Z)|"(?:\\[\s\S]|[^"\\])*(?:"|\\?\Z))
  | (?P<variable>\$(?:\{[^}\n]*\}|[a-zA-Z_][\w]*|[\d?@#*$!]))
  | (?P<parameter>--?[a-zA-Z][\w-]*)
  | (?P<number>\b\d+(?:\.\d+)?\b)
  | (?P<word>[\w./~+:-]+)
  | (?P<operator>&&|\|\||[<>]&?|[|;&(){}])
  | (?P<newline>\n)
  | (?P<escaped>\\[\s\S])
""", re.VERBOSE)


def shell_arguments(entry):
    execution = entry.get('execution') or {}
    tool = execution.get('tool') or entry.get('tool_name')
    arguments = execution.get('arguments') if execution else entry.get('tool_arguments')
    if isinstance(tool, str) and tool.casefold().removesuffix('.exe') in SHELL_TOOLS and isinstance(arguments, dict):
        for key in ('command', 'CommandLine'):
            if isinstance(command := arguments.get(key), str) and command.strip():
                return dict(arguments, command=command)
    return None


def shell_command_parts(tool, command):
    if is_powershell([tool], command):
        return command_parts(command)
    return command_parts(command, tokens=BASH_TOKENS, keywords=BASH_KEYWORDS, separators=BASH_SEPARATORS)
