// FILE: ScriptCarriersWindow.cs
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

// Editor-only: lists the prefabs that carry a MonoBehaviour, so a serialized field change can be judged
// before it reimports them all. Searches the prefab text on disk, not through AssetDatabase, because
// loading ~15,000 prefabs would be far slower.
public class ScriptCarriersWindow : EditorWindow
{
    const int ProgressInterval = 200;
    const int WarnThreshold = 20;

    MonoScript script;
    readonly List<string> carrierPaths = new List<string>();
    Vector2 scroll;
    string scriptName;
    bool counted;

    [MenuItem("Tools/Debug/Script Carriers")]
    static void Open()
    {
        GetWindow<ScriptCarriersWindow>("Script Carriers");
    }

    void OnGUI()
    {
        EditorGUI.BeginChangeCheck();
        script = (MonoScript)EditorGUILayout.ObjectField("Script", script, typeof(MonoScript), false);
        if (EditorGUI.EndChangeCheck())
            counted = false;

        using (new EditorGUI.DisabledScope(script == null))
        {
            if (GUILayout.Button("Count carriers"))
                CountCarriers();
        }

        if (!counted)
            return;

        EditorGUILayout.LabelField($"{carrierPaths.Count} prefabs carry {scriptName}");

        if (carrierPaths.Count > WarnThreshold)
        {
            EditorGUILayout.HelpBox(
                $"Adding a serialized field to this script reimports {carrierPaths.Count} prefabs. " +
                "Put the field on a settings ScriptableObject instead.",
                MessageType.Warning);
        }

        scroll = EditorGUILayout.BeginScrollView(scroll);
        foreach (string path in carrierPaths)
        {
            if (GUILayout.Button(path, EditorStyles.linkLabel))
            {
                Object asset = AssetDatabase.LoadMainAssetAtPath(path);
                EditorGUIUtility.PingObject(asset);
                Selection.activeObject = asset;
            }
        }
        EditorGUILayout.EndScrollView();
    }

    void CountCarriers()
    {
        carrierPaths.Clear();
        scriptName = script.name;

        string scriptPath = AssetDatabase.GetAssetPath(script);
        string guid = AssetDatabase.AssetPathToGUID(scriptPath);
        string needle = "guid: " + guid;

        string[] prefabs = Directory.GetFiles(Application.dataPath, "*.prefab", SearchOption.AllDirectories);
        string assetsRoot = "Assets" + Application.dataPath.Length.ToString();

        try
        {
            for (int i = 0; i < prefabs.Length; i++)
            {
                if (i % ProgressInterval == 0 &&
                    EditorUtility.DisplayCancelableProgressBar(
                        "Script Carriers",
                        $"Searching prefabs ({i} / {prefabs.Length})",
                        (float)i / prefabs.Length))
                {
                    break;
                }

                string text = File.ReadAllText(prefabs[i]);
                if (text.Contains(needle))
                    carrierPaths.Add(ToAssetPath(prefabs[i]));
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }

        counted = true;
    }

    // Turns an absolute path under Application.dataPath into a project-relative "Assets/..." path.
    static string ToAssetPath(string fullPath)
    {
        string relative = fullPath.Substring(Application.dataPath.Length);
        return ("Assets" + relative).Replace('\\', '/');
    }
}
