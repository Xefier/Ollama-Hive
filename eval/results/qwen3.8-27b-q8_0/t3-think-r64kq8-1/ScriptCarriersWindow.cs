// FILE: ScriptCarriersWindow.cs

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public class ScriptCarriersWindow : EditorWindow
{
    private MonoScript _script;
    private List<string> _matchingPaths;
    private Vector2 _scrollPos;
    private string _statusMessage;

    [MenuItem("Tools/Debug/Script Carriers")]
    private static void Open()
    {
        var window = GetWindow<ScriptCarriersWindow>("Script Carriers");
        window.minSize = new Vector2(420, 320);
    }

    private void OnGUI()
    {
        EditorGUILayout.Space();
        EditorGUILayout.LabelField("Script", EditorStyles.boldLabel);

        using (new EditorGUI.IndentedScope())
        {
            _script = (MonoScript)EditorGUILayout.ObjectField(_script, typeof(MonoScript), false);
        }

        EditorGUILayout.Space();

        if (GUILayout.Button("Count Carriers", GUILayout.Height(28)))
        {
            CountCarriers();
        }

        if (_matchingPaths != null)
        {
            EditorGUILayout.Space();
            EditorGUILayout.HelpBox(_statusMessage, MessageType.Info);

            if (_matchingPaths.Count > 20)
            {
                EditorGUILayout.HelpBox(
                    $"Adding a serialized field to this script reimports {_matchingPaths.Count} prefabs. " +
                    "Put the field on a settings ScriptableObject instead.",
                    MessageType.Warning);
            }

            EditorGUILayout.Space();
            EditorGUILayout.LabelField($"Matching prefabs ({_matchingPaths.Count}):", EditorStyles.boldLabel);

            _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos);
            for (int i = 0; i < _matchingPaths.Count; i++)
            {
                string path = _matchingPaths[i];
                if (GUILayout.Button(path, EditorStyles.linkLabel))
                {
                    var asset = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                    if (asset != null)
                    {
                        EditorGUIUtility.PingObject(asset);
                        Selection.activeObject = asset;
                    }
                }
            }
            EditorGUILayout.EndScrollView();
        }
    }

    private void CountCarriers()
    {
        if (_script == null)
        {
            _statusMessage = "Select a MonoScript first.";
            _matchingPaths = null;
            Repaint();
            return;
        }

        string assetPath = AssetDatabase.GetAssetPath(_script);
        string guid = AssetDatabase.AssetPathToGUID(assetPath);

        if (string.IsNullOrEmpty(guid))
        {
            _statusMessage = "Could not resolve a GUID for " + assetPath + ".";
            _matchingPaths = null;
            Repaint();
            return;
        }

        string searchToken = "guid: " + guid;
        _matchingPaths = new List<string>();

        // Directory.GetFiles on the whole Assets tree gives us every prefab path
        // without touching the AssetDatabase import pipeline.
        string[] prefabPaths = Directory.GetFiles("Assets", "*.prefab", SearchOption.AllDirectories);
        int total = prefabPaths.Length;

        try
        {
            for (int i = 0; i < total; i++)
            {
                if (i > 0 && i % 200 == 0)
                {
                    bool proceed = EditorUtility.DisplayCancelableProgressBar(
                        "Finding Script Carriers",
                        _script.name + ": " + i + " / " + total + " prefabs scanned",
                        (float)i / total);

                    if (!proceed)
                        return;
                }

                string text = File.ReadAllText(prefabPaths[i]);
                if (text.Contains(searchToken))
                    _matchingPaths.Add(prefabPaths[i]);
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }

        _statusMessage = _matchingPaths.Count + " prefabs carry " + _script.name;
        Repaint();
    }
}
