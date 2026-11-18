#!/bin/bash
# compile.sh <assembly> <file.cs>...  Compiles the files offline with a Unity project's own compiler arguments for
# <assembly> (Assembly-CSharp or Assembly-CSharp-Editor), referencing that project's already-built <assembly>.dll so
# they can use its public types (not its internal ones). About a second; no editor needed. Run from anywhere.
#
# The project is $UNITY_PROJECT, default the TheSneedRooms master checkout. It needs Library/Bee and
# Library/ScriptAssemblies from an editor that has compiled at least once; the editor itself may be closed or open.
# Output goes to $UNITY_PROJECT/Library/LocalModelEval.
#
# A file that redefines a type the assembly already has (a modified copy of an existing class) needs that class renamed
# first, e.g. sed 's/class Foo\b/class Foo_Llm/'. check.sh does that for t4 and t5.
UNITY_PROJECT=${UNITY_PROJECT:-D:/Dev/TheSneedRooms/master/TheSneedRooms}
ASM=$1; shift
FILES=(); for f in "$@"; do FILES+=("$(cd "$(dirname "$f")" && pwd -W)/$(basename "$f")"); done
cd "$UNITY_PROJECT" || { echo "UNITY_PROJECT not found: $UNITY_PROJECT"; exit 2; }
OUT=Library/LocalModelEval; mkdir -p "$OUT"
VER=$(sed -n 's/^m_EditorVersion: //p' ProjectSettings/ProjectVersion.txt | tr -d '\r')
E="C:/Program Files/Unity/$VER/Editor/Data"
[ -d "$E" ] || E="C:/Program Files/Unity/Hub/Editor/$VER/Editor/Data"
[ -d "$E" ] || E="D:/Unity/Hub/Editor/$VER/Editor/Data"
[ -d "$E" ] || E=$UNITY_EDITOR_DATA
[ -d "$E" ] || { echo "Unity $VER not found: set UNITY_EDITOR_DATA to its Editor/Data folder"; exit 2; }
SRC=$(ls -t Library/Bee/artifacts/*.dag/"$ASM.rsp" 2>/dev/null | head -1)
[ -n "$SRC" ] || { echo "no $ASM.rsp under $UNITY_PROJECT/Library/Bee/artifacts: let the editor compile once"; exit 2; }
RSP="$OUT/$ASM.test.rsp"
grep -v -E '\.cs"?$|^-out:|^-refout:' "$SRC" > "$RSP"
echo "-out:\"$OUT/$ASM.Test.dll\"" >> "$RSP"
echo "-r:\"Library/ScriptAssemblies/$ASM.dll\"" >> "$RSP"
for f in "${FILES[@]}"; do echo "\"$f\"" >> "$RSP"; done
"$E/NetCoreRuntime/dotnet.exe" exec "$E/DotNetSdkRoslyn/csc.dll" -nologo -noconfig "@$RSP" 2>&1 | grep -E 'error|warning CS0(162|168|219|414)' | grep -v 'Library/' | head -40
echo "exit=${PIPESTATUS[0]}"
