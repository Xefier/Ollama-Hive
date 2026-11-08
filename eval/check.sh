#!/bin/bash
# check.sh <results/<model>> [folder...]  The mechanical half of grading: for every answer folder under the model's
# results (or only the ones named), extracts the code from answer.md and then
#   t1: runs tasks/t1/test on RollingStats.cs (ALL PASS or the failures),
#   t2, t5, t4: compiles against Assembly-CSharp (t4/t5 with the class renamed, since the project has it),
#   t3, w1: compiles against Assembly-CSharp-Editor,
#   t4, t5: prints the diff against the frozen input.
# Reading every answer is still the grading; this only saves typing. Run from anywhere.
HERE=$(cd "$(dirname "$0")" && pwd)
MODEL=$(cd "$1" && pwd); shift
TMP="$HERE/.build"; mkdir -p "$TMP"
dirs=("$@"); [ ${#dirs[@]} -gt 0 ] || dirs=($(ls "$MODEL"))
for d in "${dirs[@]}"; do
    dir="$MODEL/$d"; [ -f "$dir/answer.md" ] || continue
    task=${d%%-*}
    echo "=== $d"
    python "$HERE/extract.py" "$dir" >/dev/null
    case $task in
        t1) dotnet run --project "$HERE/tasks/t1/test" -c Release -p:Answer="$(cygpath -w "$dir/RollingStats.cs")" 2>&1 | tail -3 ;;
        t2) "$HERE/compile.sh" Assembly-CSharp "$dir/TileFindCommand.cs" ;;
        t3) "$HERE/compile.sh" Assembly-CSharp-Editor "$dir/ScriptCarriersWindow.cs" ;;
        t4) sed 's/class TailAnimator_AnimationAndIkHandler\b/class TailAnimator_AnimationAndIkHandler_Llm/' \
                "$dir/TailAnimator_AnimationAndIkHandler.cs" > "$TMP/$d.cs"
            "$HERE/compile.sh" Assembly-CSharp "$TMP/$d.cs"
            diff <(tr -d '\r' < "$HERE/tasks/t4/inputs/TailAnimator_AnimationAndIkHandler.orig.cs") \
                 <(tr -d '\r' < "$dir/TailAnimator_AnimationAndIkHandler.cs") ;;
        t5) sed 's/class NonLinearModifierManager : Singleton<NonLinearModifierManager>/class NonLinearModifierManager_Llm : Singleton<NonLinearModifierManager_Llm>/' \
                "$dir/NonLinearModifierManager.cs" > "$TMP/$d.cs"
            "$HERE/compile.sh" Assembly-CSharp "$TMP/$d.cs"
            diff <(tr -d '\r' < "$HERE/tasks/t5/inputs/NonLinearModifierManager.cs") \
                 <(tr -d '\r' < "$dir/NonLinearModifierManager.cs") ;;
        w1) "$HERE/compile.sh" Assembly-CSharp-Editor "$dir/ApparelEditorWindow.cs" ;;
    esac
    tail -c 300 "$dir/answer.md" | grep -o '\[[^]]*tokens/s\]'
done
