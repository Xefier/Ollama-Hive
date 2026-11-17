// FILE: ScriptCarriersWindow.cs
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public class ScriptCarriersWindow : EditorWindow
{
    private MonoScript _script;
    private string[] _carrierPaths;
    private string _summary;
    private Vector2 _scrollPos;

    [MenuItem("Tools/Debug/Script Carriers")]
    private static void Open()
    {
        GetWindow<ScriptCarriersWindow>("Script Carriers");
    }

    private void OnGUI()
    {
        _script = (MonoScript)EditorGUILayout.ObjectField("Script", _script, typeof(MonoScript), false);

        if (GUILayout.Button("Count carriers"))
        {
            CountCarriers();
        }

        if (_carrierPaths == null)
            return;

        EditorGUILayout.Space();
        EditorGUILayout.LabelField(_summary, EditorStyles.boldLabel);

        if (_carrierPaths.Length > 20)
        {
            EditorGUILayout.HelpBox(
                $"Adding a serialized field to this script reimports {_carrierPaths.Length} prefabs. " +
                "Put the field on a settings ScriptableObject instead.",
                MessageType.Warning);
        }

        _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos);
        foreach (string path in _carrierPaths)
        {
            if (GUILayout.Button(path, EditorStyles.linkLabel))
            {
                GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab != null)
                {
                    Selection.activeObject = prefab;
                    EditorGUIUtility.PingObject(prefab);
                }
            }
        }
        EditorGUILayout.EndScrollView();
    }

    private void CountCarriers()
    {
        if (_script == null)
        {
            DebugX.LogWarning("Script Carriers: no script selected.");
            return;
        }

        string scriptAssetPath = AssetDatabase.GetAssetPath(_script);
        string guid = AssetDatabase.AssetPathToGUID(scriptAssetPath);
        if (string.IsNullOrEmpty(guid))
        {
            DebugX.LogError($"Script Carriers: could not resolve GUID for '{scriptAssetPath}'.");
            return;
        }

        string token = "guid: " + guid;
        string[] prefabGuids = AssetDatabase.FindAssets("t:Prefab", new[] { "Assets" });
        string projectRoot = Path.GetDirectoryName(Application.dataPath);

        var matches = new List<string>(256);

        try
        {
            int total = prefabGuids.Length;
            for (int i = 0; i < total; i++)
            {
                if (i % 200 == 0)
                {
                    bool cancelled = EditorUtility.DisplayCancelableProgressBar(
                        "Counting script carriers",
                        $"{_script.name}: {i:N0} / {total:N0} prefabs scanned",
                        total > 0 ? (float)i / total : 0f);
                    if (cancelled)
                        break;
                }

                string assetPath = AssetDatabase.GUIDToAssetPath(prefabGuids[i]);
                if (!assetPath.EndsWith(".prefab", System.StringComparison.Ordinal))
                    continue;

                string fullPath = Path.Combine(projectRoot, assetPath);
                if (!File.Exists(fullPath))
                    continue;

                string text = File.ReadAllText(fullPath);
                if (text.Contains(token, System.StringComparison.Ordinal))
                    matches.Add(assetPath);
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }

        _carrierPaths = matches.ToArray();
        _summary = $"{_carrierPaths.Length} prefab{_carrierPaths.Length == 1 ? "" : "s"} carry {_script.name}";
        _scrollPos = Vector2.zero;
    }
}
