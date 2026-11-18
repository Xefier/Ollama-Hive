```csharp
// FILE: ScriptCarriersWindow.cs
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Shows how many prefabs carry a given MonoScript, before adding a serialized field to it. Each carrier is
/// reimported when the field is added, so a script on many prefabs is better turned into a settings
/// ScriptableObject instead.
/// </summary>
public class ScriptCarriersWindow : EditorWindow
{
    private static readonly string NeedlePrefix = "guid: ";
    private const int WarningThreshold = 20;

    private MonoScript target;
    private int count;
    private string scriptName = "";
    private readonly List<string> carriers = new List<string>();
    private bool searched;
    private Vector2 scroll;

    [MenuItem("Tools/Debug/Script Carriers")]
    private static void Open()
    {
        GetWindow<ScriptCarriersWindow>("Script Carriers");
    }

    private void OnGUI()
    {
        target = (MonoScript)EditorGUILayout.ObjectField("Script", target, typeof(MonoScript), false);

        if (GUILayout.Button("Count carriers"))
            Search();

        if (!searched)
        {
            EditorGUILayout.HelpBox("Pick a script and click Count carriers to see how many prefabs reference it.", MessageType.Info);
            return;
        }

        if (count > 0 && count > WarningThreshold)
            EditorGUILayout.HelpBox($"Adding a serialized field to this script reimports {count} prefabs. Put the field on a settings ScriptableObject instead.", MessageType.Warning);

        EditorGUILayout.LabelField($"{count} prefab{Plural(count)} carr{count == 1 ? "ies" : "y"} {scriptName}", EditorStyles.boldLabel);

        scroll = EditorGUILayout.BeginScrollView(scroll);
        foreach (string path in carriers)
        {
            if (GUILayout.Button(path, GUILayout.ExpandWidth(true)))
                Select(path);
        }
        EditorGUILayout.EndScrollView();
    }

    private void Search()
    {
        carriers.Clear();
        count = 0;
        if (target == null)
            return;

        string guid = AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(target));
        if (string.IsNullOrEmpty(guid))
        {
            DebugX.LogWarning("Script Carriers: could not get the GUID of " + target.name + ".");
            return;
        }

        string needle = NeedlePrefix + guid;
        string[] prefabPaths = Directory.GetFiles("Assets", "*.prefab", SearchOption.AllDirectories);
        int shown = 0;
        try
        {
            foreach (string path in prefabPaths)
            {
                if (EditorUtility.DisplayCancelableProgressBar("Script Carriers", path, (float)shown / prefabPaths.Length))
                    break;
                if ((shown++) % 200 == 0)
                    Repaint();

                if (ContainsGuidReference(File.ReadAllText(path), needle))
                    carriers.Add(path);
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }

        count = carriers.Count;
        scriptName = target.name;
        searched = true;
    }

    // The meta file's guid is 32 hex chars, so a reference is the needle not followed by another hex char.
    private static bool ContainsGuidReference(string text, string needle)
    {
        int index = text.IndexOf(needle, StringComparison.Ordinal);
        while (index >= 0)
        {
            int after = index + needle.Length;
            if (after >= text.Length || !IsHex(text[after]))
                return true;
            index = text.IndexOf(needle, index + 1, StringComparison.Ordinal);
        }
        return false;
    }

    private static bool IsHex(char c)
    {
        return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
    }

    private void Select(string path)
    {
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
        if (prefab != null)
        {
            EditorGUIUtility.PingObject(prefab);
            Selection.activeObject = prefab;
        }
    }

    private static string Plural(int n) => n == 1 ? "" : "s";
}
```

- I enumerated prefab files with `Directory.GetFiles("Assets", "*.prefab", AllDirectories)` rather than `AssetDatabase.FindAssets`, so nothing is loaded during the search; the clicked prefab is loaded once to ping/select it.
- I treat a match as `guid: <guid>` not followed by another hex char, so a shorter guid that prefixes another can't match.
- I used `DebugX.LogWarning` per the project logging rule; it's the global `DebugX` static class, so no new using is needed.
- I did not see any existing EditorWindow in the project to copy its exact style from, so I followed standard Unity editor conventions.

[qwen3.8-unity:27b on http://192.168.1.189:11434: 895 prompt tokens, 2215 answer tokens, 64 tokens/s]