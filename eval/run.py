"""run.py <task> [--think] [--rules <file>] [--run <n>]: sends eval/tasks/<task>/prompt.txt, with the files listed in
its files.txt (relative to eval/) and rules.txt as the system prompt, to the local model through this repo's local-llm
client (client/local_llm_mcp.py), so the call is logged in its stats like any other. Run it from anywhere: it works
from eval/, where the client may read the task inputs.

The answer goes to results/<model>/<task>[-think][-r<n>]/answer.md (no suffix for run 1), named after the model that
answered (the footer), and extract.py writes its C# files next to it. Prints only what was written and the footer.

OLLAMA_URLS and LOCAL_LLM_ROOTS default to the local-llm server's settings in ~/.claude.json."""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.join(os.path.dirname(HERE), "client")


def client_env():
    """The env block of the local-llm MCP server in ~/.claude.json, wherever it is nested."""
    try:
        config = json.load(open(os.path.expanduser("~/.claude.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    stack = [config]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if isinstance(node.get("local-llm"), dict):
                return node["local-llm"].get("env", {})
            stack.extend(node.values())
    return {}


for key, value in client_env().items():
    os.environ.setdefault(key, value)
sys.path.insert(0, CLIENT)
import local_llm_mcp as llm  # noqa: E402
sys.path.insert(0, HERE)
import extract  # noqa: E402

os.chdir(HERE)  # the client reads files under the working directory; inputs are listed relative to eval/
args = sys.argv[1:]
task = args[0]
think = "--think" in args
rules = args[args.index("--rules") + 1] if "--rules" in args else os.path.join(HERE, "rules.txt")
task_dir = os.path.join(HERE, "tasks", task)
read = lambda p: open(p, encoding="utf-8").read()
files_txt = os.path.join(task_dir, "files.txt")
files = [l.strip() for l in read(files_txt).splitlines() if l.strip()] if os.path.exists(files_txt) else []

answer = llm.ask({"prompt": read(os.path.join(task_dir, "prompt.txt")), "files": files, "system": read(rules),
                  "think": think})
footer = answer[answer.rfind("\n\n["):].strip()
model = re.match(r"\[(\S+) on", footer).group(1) if re.match(r"\[(\S+) on", footer) else "unknown"
run = args[args.index("--run") + 1] if "--run" in args else "1"
out = os.path.join(HERE, "results", model.replace(":", "-"),
                   task + ("-think" if think else "") + ("" if run == "1" else "-r" + run))
os.makedirs(out, exist_ok=True)
open(os.path.join(out, "answer.md"), "w", encoding="utf-8").write(answer)
for line in extract.extract(out):
    print(line)
print(out)
print(footer)
