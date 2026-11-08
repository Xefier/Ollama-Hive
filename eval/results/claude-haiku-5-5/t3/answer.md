```csharp
// FILE: ScriptCarriersWindow.cs
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

// Editor-only window. It reads the prefab files as text instead of loading them through AssetDatabase,
// because loading ~15,000 prefabs just to search them would take far longer.
public class ScriptCarriersWindow : EditorWindow
{
    const int ProgressInterval = 200;
    const int WarnAbove = 20;

    MonoScript script;
    readonly List<string> carriers = new List<string>();
    string scriptName = "";
    bool hasResult;
    bool cancelled;
    Vector2 scroll;

    [MenuItem("Tools/Debug/Script Carriers")]
    static void Open()
    {
        GetWindow<ScriptCarriersWindow>("Script Carriers");
    }

    void OnGUI()
    {
        script = (MonoScript)EditorGUILayout.ObjectField("Script", script, typeof(MonoScript), false);

        using (new EditorGUI.DisabledScope(script == null))
        {
            if (GUILayout.Button("Count carriers"))
                CountCarriers();
        }

        if (!hasResult)
            return;

        EditorGUILayout.Space();
        string suffix = cancelled ? " (search cancelled, list is partial)" : "";
        EditorGUILayout.LabelField($"{carriers.Count} prefabs carry {scriptName}{suffix}", EditorStyles.boldLabel);

        if (carriers.Count > WarnAbove)
        {
            EditorGUILayout.HelpBox(
                $"Adding a serialized field to this script reimports {carriers.Count} prefabs. " +
                "Put the field on a settings ScriptableObject instead.",
                MessageType.Warning);
        }

        scroll = EditorGUILayout.BeginScrollView(scroll);
        for (int i = 0; i < carriers.Count; i++)
        {
            if (GUILayout.Button(carriers[i], EditorStyles.linkLabel))
                PingPrefab(carriers[i]);
        }
        EditorGUILayout.EndScrollView();
    }

    void CountCarriers()
    {
        carriers.Clear();
        hasResult = false;
        cancelled = false;

        if (!AssetDatabase.TryGetGUIDAndLocalFileIdentifier(script, out string guid, out long _))
        {
            DebugX.LogWarning($"Script Carriers: no GUID for {script.name}");
            return;
        }

        string needle = "guid: " + guid;
        scriptName = script.name;
        string[] files = Directory.GetFiles("Assets", "*.prefab", SearchOption.AllDirectories);

        try
        {
            for (int i = 0; i < files.Length; i++)
            {
                if (i % ProgressInterval == 0 &&
                    EditorUtility.DisplayCancelableProgressBar("Script Carriers",
                        $"Searching prefabs for {scriptName} ({i}/{files.Length})", (float)i / files.Length))
                {
                    cancelled = true;
                    break;
                }

                if (File.ReadAllText(files[i]).Contains(needle))
                    carriers.Add(files[i].Replace('\\', '/'));
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }

        carriers.Sort();
        hasResult = true;
        Repaint();
    }

    static void PingPrefab(string path)
    {
        Object asset = AssetDatabase.LoadAssetAtPath<Object>(path);
        if (asset == null)
            return;

        EditorGUIUtility.PingObject(asset);
        Selection.activeObject = asset;
    }
}
```

- Assumes the Editor runs with the project root as its working directory, so `Directory.GetFiles("Assets", ...)` returns project-relative paths. Not checked.
- `DebugX.LogWarning` is used for the no-GUID case as the rules require; I did not see DebugX's signature or confirm it is visible from Assembly-CSharp-Editor.
- The search matches `guid: <32 hex>` as plain text, which is exact because GUIDs are a fixed length. Not tested against a real project.
- I did not check whether the Editor folder's assembly definition references the game assembly that holds `MonoScript` objects; `MonoScript` is part of UnityEditor/UnityEngine, so this should be fine.
- No files were read beyond rules.txt and tasks/t3/prompt.txt, because tasks/t3/files.txt does not exist.
