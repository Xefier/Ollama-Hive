```csharp
// FILE: Editor/ScriptCarriersWindow.cs

using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

#if !UNITY_EDITOR
#error This file should only be compiled in the Editor assembly
#endif

public class ScriptCarriersWindow : EditorWindow
{
    private MonoScript selectedScript;
    private List<string> carrierPaths = new List<string>();
    private Vector2 scrollPosition;
    private int carrierCount = 0;

    [MenuItem("Tools/Debug/Script Carriers")]
    private static void ShowWindow()
    {
        var window = GetWindow<ScriptCarriersWindow>("Script Carriers");
        window.minSize = new Vector2(400, 300);
    }

    private void OnGUI()
    {
        EditorGUILayout.BeginVertical();

        // Script selection
        EditorGUILayout.LabelField("Select a MonoScript", EditorStyles.boldLabel);
        selectedScript = (MonoScript)EditorGUILayout.ObjectField(selectedScript, typeof(MonoScript), false);
        
        EditorGUILayout.Space();

        if (GUILayout.Button("Count Carriers"))
        {
            CountCarriers();
        }

        // Results display
        if (carrierCount > 0 || selectedScript != null)
        {
            EditorGUILayout.Space();
            var scriptName = selectedScript != null ? selectedScript.GetClass() : "unknown";
            EditorGUILayout.LabelField($"{carrierCount} prefabs carry '{scriptName}'", EditorStyles.wordWrappedLabel);

            // Warning when too many carriers
            if (carrierCount > 20)
            {
                EditorGUILayout.HelpBox($"Adding a serialized field to this script reimports {carrierCount} prefabs. Put the field on a settings ScriptableObject instead.", MessageType.Warning);
            }

            EditorGUILayout.Space();

            // Scrollable list of carriers
            if (carrierPaths.Count > 0)
            {
                scrollPosition = EditorGUILayout.BeginScrollView(scrollPosition, GUILayout.Height(EditorGUIUtility.currentViewWidth < 400 ? 200 : EditorGUIUtility.currentViewWidth));

                foreach (var path in carrierPaths)
                {
                    var buttonStyle = GUI.skin.box;
                    var rect = GUILayoutUtility.GetRect(0f, 20f, GUILayout.ExpandWidth(true), GUILayout.Height(18f));

                    if (GUI.Button(rect, path))
                    {
                        var prefabObject = AssetDatabase.LoadMainAssetAtPath(path);
                        Selection.activeObject = prefabObject;
                        EditorGUIUtility.PingObject(prefabObject);
                    }
                }

                EditorGUILayout.EndScrollView();
            }
        }

        EditorGUILayout.EndVertical();
    }

    private void CountCarriers()
    {
        if (selectedScript == null)
        {
            EditorUtility.DisplayDialog("No Script Selected", "Please select a MonoScript first.", "OK");
            return;
        }

        // Get the script's GUID
        var guid = string.Empty;
        var path = AssetDatabase.GetAssetPath(selectedScript);
        
        if (!string.IsNullOrEmpty(path))
        {
            var localId = default(long);
            if (AssetDatabase.TryGetGUIDAndLocalFileIdentifier(path, out guid, out localId))
            {
                // GUID obtained successfully
            }
        }

        if (string.IsNullOrEmpty(guid))
        {
            DebugX.LogError("Failed to get GUID for script: " + selectedScript.name);
            EditorUtility.DisplayDialog("Error", "Could not determine the script's GUID. Make sure the script is in Assets folder.", "OK");
            return;
        }

        carrierPaths.Clear();
        
        // Search all prefab files under Assets
        var allFiles = Directory.GetFiles("Assets", "*.prefab", SearchOption.AllDirectories);
        var targetString = "guid: " + guid;
        int processedCount = 0;

        try
        {
            for (int i = 0; i < allFiles.Length; i++)
            {
                // Check for cancellation every 200 files
                if ((processedCount % 200) == 0 && EditorUtility.DisplayCancelableProgressBar("Scanning Prefabs", $"Searching '{selectedScript.GetClass()}'... ({i}/{allFiles.Length})", (float)i / allFiles.Length))
                {
                    carrierPaths.Clear();
                    carrierCount = 0;
                    return;
                }

                var fullPath = Path.Combine(Application.dataPath, "..", allFiles[i]);
                
                try
                {
                    using (var reader = new StreamReader(fullPath))
                    {
                        // Read file in chunks to avoid loading entire file into memory if large
                        while (!reader.EndOfStream)
                        {
                            var line = reader.ReadLine();
                            if (line != null && line.Contains(targetString))
                            {
                                carrierPaths.Add(allFiles[i]);
                                break;
                            }
                        }
                    }
                }
                catch (IOException ex)
                {
                    // Skip files we can't read (might be locked or corrupted)
                    DebugX.LogWarning($"Could not read prefab file: {allFiles[i]} - {ex.Message}");
                }

                processedCount++;
            }

            carrierCount = carrierPaths.Count;
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }
    }
}
```

- Assumed DebugX exists in global namespace and is available in editor assembly (per project rules); may need to verify this compiles in Assembly-CSharp-Editor.
- Used `selectedScript.GetClass()` for display name instead of `name` property since the type name is more informative; adjusted per Unity's MonoScript API.
- Files are read via `StreamReader` with line-by-line reading rather than full content load to keep memory usage low for ~15k prefabs.

[qwen3.5:27b on http://192.168.1.189:11434: 886 prompt tokens, 2157 answer tokens, 48 tokens/s]