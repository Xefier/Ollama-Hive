"""extract.py <answer-dir>: writes the C# code in <answer-dir>/answer.md to files next to it. Fenced ```csharp blocks
if there are any; otherwise bare code split at '// FILE:' lines (the models often skip the fences), each cut after its
last line that is '}' or '#endif', since the model's notes follow that."""
import os, re, sys


def extract(folder):
    """Writes the code files and returns what it did, one line each (written files, then the model's notes)."""
    answer = open(os.path.join(folder, "answer.md"), encoding="utf-8").read()
    if "\n\n[" in answer:
        answer = answer[:answer.rfind("\n\n[")]
    report, blocks = [], re.findall(r"```(?:csharp|cs|c#)\s*\n(.*?)```", answer, re.S | re.I)
    if not blocks:
        for chunk in re.split(r"(?m)^(?=// FILE:)", answer):
            if not chunk.startswith("// FILE:"):
                continue
            lines = chunk.splitlines()
            ends = [i for i, l in enumerate(lines) if l.strip() in ("}", "#endif")]
            last = ends[-1] if ends else len(lines) - 1
            blocks.append("\n".join(lines[:last + 1]) + "\n")
            report += ["note: " + l.strip() for l in lines[last + 1:] if l.strip()]
    for i, code in enumerate(blocks):
        m = re.match(r"\s*//\s*FILE:\s*(\S+)", code)
        name = os.path.basename(m.group(1)) if m else "code{}.cs".format(i)
        open(os.path.join(folder, name), "w", encoding="utf-8").write(code)
        report.insert(0, "wrote {} ({} lines)".format(name, len(code.splitlines())))
    if not blocks:
        report.insert(0, "no code found in answer.md")
    return report


if __name__ == "__main__":
    for line in extract(sys.argv[1]):
        print(line)
