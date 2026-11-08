// FILE: ScriptCarriersWindow.cs
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public class ScriptCarriersWindow : EditorWindow
{
    private MonoScript _targetScript;
    private string _summary;
    private List<string> _matchingPaths = new List<string>();
    private Vector2 _scrollPos;
    private bool _searchDone;

    [MenuItem("Tools/Debug/Script Carriers")]
    private static void ShowWindow()
    {
        var window = GetWindow<ScriptCarriersWindow>("Script Carriers");
        window._targetScript = null;
        window._matchingPaths.Clear();
        window._summary = null;
        window._searchDone = false;
        window.Repaint();
    }

    private void OnGUI()
    {
        EditorGUILayout.Space();
        EditorGUILayout.LabelField("Target script", EditorStyles.boldLabel);
        _targetScript = (MonoScript)EditorGUILayout.ObjectField(_targetScript, typeof(MonoScript), false);

        EditorGUILayout.Space();

        using (new EditorGUI.DisabledScope(_targetScript == null))
        {
            if (GUILayout.Button("Count carriers", GUILayout.MinHeight(28)))
                RunSearch();
        }

        if (!_searchDone)
            return;

        EditorGUILayout.Space();
        EditorGUILayout.LabelField(_summary);

        if (_matchingPaths.Count > 20)
        {
            EditorGUILayout.Space();
            EditorGUILayout.HelpBox(
                $"Adding a serialized field to this script reimports {_matchingPaths.Count} prefabs. " +
                "Put the field on a settings ScriptableObject instead.",
                MessageType.Warning);
        }

        if (_matchingPaths.Count == 0)
        {
            EditorGUILayout.Space();
            EditorGUILayout.HelpBox("No prefabs carry this script.", MessageType.Info);
            return;
        }

        EditorGUILayout.Space();
        _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos, GUILayout.MaxHeight(300f));

        for (int i = 0; i < _matchingPaths.Count; i++)
        {
            if (GUILayout.Button(_matchingPaths[i], GUILayout.ExpandWidth(true)))
            {
                var obj = AssetDatabase.LoadMainAssetAtPath(_matchingPaths[i]);
                if (obj != null)
                {
                    Selection.activeObject = obj;
                    EditorGUIUtility.PingObject(obj);
                }
            }
        }

        EditorGUILayout.EndScrollView();
    }

    private void RunSearch()
    {
        _matchingPaths.Clear();
        _summary = null;
        _searchDone = false;

        if (!AssetDatabase.TryGetGUIDAndLocalFileIdentifier(_targetScript, out string guid, out _))
        {
            DebugX.LogWarning("Could not resolve a GUID for " + _targetScript.name);
            _searchDone = true;
            _summary = "Failed to resolve GUID.";
            return;
        }

        string needle = "guid: " + guid;
        int total = 0;

        try
        {
            var files = new List<string>(Directory.EnumerateFiles("Assets", "*.prefab", SearchOption.AllDirectories));
            total = files.Count;

            for (int i = 0; i < files.Count; i++)
            {
                if (EditorUtility.DisplayCancelableProgressBar(
                        "Finding script carriers",
                        $"Reading {i + 1} / {total} …",
                        (float)i / total))
                    break;

                if ((i + 1) % 200 == 0)
                {
                    // Already shown above; this branch is the "every 200" cadence guard.
                }

                try
                {
                    string text = File.ReadAllText(files[i]);
                    if (text.Contains(needle))
                        _matchingPaths.Add(files[i]);
                }
                catch (IOException)
                {
                    // File locked or transiently unavailable; skip.
                }
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }

        _searchDone = true;
        _summary = $"{_matchingPaths.Count} prefab(s) carry {_targetScript.name}";

        if (DebugX.Verbose)
            DebugX.Log($"ScriptCarriersWindow: found {_matchingPaths.Count} carrier(s) for {_targetScript.name}");
    }
}
