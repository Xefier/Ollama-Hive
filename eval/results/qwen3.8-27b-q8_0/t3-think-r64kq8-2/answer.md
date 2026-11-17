```csharp
// FILE: ScriptCarriersWindow.cs

#if UNITY_EDITOR
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public class ScriptCarriersWindow : EditorWindow
{
    private const int ProgressBatchSize = 200;
    private const int WarningThreshold = 20;

    private MonoScript _targetScript;
    private readonly List<string> _matchingPaths = new List<string>();
    private int _resultCount;
    private Vector2 _scrollPos;

    [MenuItem("Tools/Debug/Script Carriers")]
    private static void Open()
    {
        GetWindow<ScriptCarriersWindow>("Script Carriers").MinSize = new Vector2(420, 300);
    }

    private void OnGUI()
    {
        GUILayout.Space(4);

        _targetScript = (MonoScript)EditorGUILayout.ObjectField(
            "Script", _targetScript, typeof(MonoScript), false);

        EditorGUILayout.Space();

        if (GUILayout.Button("Count carriers", GUILayout.MinHeight(28)))
        {
            CountCarriers();
        }

        if (_resultCount > 0 || _matchingPaths.Count > 0)
        {
            EditorGUILayout.Space();

            string scriptName = _targetScript != null ? _targetScript.name : "(unknown)";
            EditorGUILayout.LabelField(
                new GUIContent($"{_resultCount} prefabs carry {scriptName}"),
                EditorStyles.boldLabel);

            if (_resultCount > WarningThreshold)
            {
                EditorGUILayout.HelpBox(
                    $"Adding a serialized field to this script reimports {_resultCount} prefabs. " +
                    $"Put the field on a settings ScriptableObject instead.",
                    MessageType.Warning);
            }

            EditorGUILayout.Space();
            _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos);

            for (int i = 0; i < _matchingPaths.Count; i++)
            {
                if (GUILayout.Button(_matchingPaths[i], EditorStyles.miniButton))
                {
                    PingAndSelect(_matchingPaths[i]);
                }
            }

            EditorGUILayout.EndScrollView();
        }
    }

    private void CountCarriers()
    {
        _matchingPaths.Clear();
        _resultCount = 0;

        if (_targetScript == null)
        {
            DebugX.LogWarning("Script Carriers: no MonoScript selected.");
            return;
        }

        string assetPath = AssetDatabase.GetAssetPath(_targetScript);
        string guid = AssetDatabase.AssetPathToGUID(assetPath);
        if (string.IsNullOrEmpty(guid))
        {
            DebugX.LogError($"Script Carriers: could not resolve GUID for '{assetPath}'.");
            return;
        }

        string searchToken = $"guid: {guid}";
        string[] prefabFiles = Directory.GetFiles("Assets", "*.prefab", SearchOption.AllDirectories);
        int total = prefabFiles.Length;

        try
        {
            for (int i = 0; i < total; i++)
            {
                if (i % ProgressBatchSize == 0)
                {
                    if (!EditorUtility.DisplayCancelableProgressBar(
                        "Counting script carriers",
                        $"{i} / {total}",
                        total > 0 ? (float)i / total : 1f))
                    {
                        if (DebugX.Enabled)
                            DebugX.Log($"Script Carriers: search cancelled at file {i} / {total}.");
                        break;
                    }
                }

                string content = File.ReadAllText(prefabFiles[i]);
                if (content.Contains(searchToken))
                {
                    _matchingPaths.Add(prefabFiles[i]);
                }
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }

        _resultCount = _matchingPaths.Count;
    }

    private static void PingAndSelect(string assetPath)
    {
        GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
        if (prefab == null)
        {
            DebugX.LogWarning($"Script Carriers: could not load prefab at '{assetPath}'.");
            return;
        }

        EditorGUIUtility.PingObject(prefab);
        Selection.activeObject = prefab;
    }
}
#endif
```

- `AssetPathToGUID` is used for the GUID lookup; `TryGetGUIDAndLocalFileIdentifier` would also work but the local file ID isn't needed here.
- The search is a synchronous loop on the main thread; for ~15 000 small YAML files this typically finishes in a few seconds, but on a cold cache or slow disk it may take longer. A coroutine + `EditorApplication.update` could be added later if it becomes painful.
- `Directory.GetFiles("Assets", …)` relies on the editor's working directory being the project root, which is guaranteed in the Unity Editor.
- The cancel check only fires every 200 files (the progress-bar tick), so up to 199 extra files may be read after the user hits Cancel.
- `LoadAssetAtPath<GameObject>` is used only on user click (for ping/select), not during the search, per the "do not load prefabs to search them" rule.

[qwen3.8:27b-q8_0 on http://192.168.1.232:11434: 895 prompt tokens, 3225 answer tokens, 52 tokens/s]