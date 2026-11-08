// FILE: Editor/ScriptCarriersWindow.cs
#if UNITY_EDITOR

using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace TheClassrooms.Editor
{
    /// <summary>
    /// Editor window to scan prefab files for references to a specific script's GUID.
    /// This helps estimate reimport costs before adding serialized fields to MonoBehaviours.
    /// </summary>
    public class ScriptCarriersWindow : EditorWindow
    {
        private SerializedObject _serialized;
        private ObjectField _scriptField = new();
        private List<string> _carriers = new();
        private int _carrierCount = 0;
        private Vector2 _scrollPos;
        private bool _isScanning = false;

        [MenuItem("Tools/Debug/Script Carriers")]
        public static void ShowWindow()
        {
            var window = GetWindow<ScriptCarriersWindow>("Script Carriers");
            window.minSize = new Vector2(400, 300);
        }

        private void OnEnable()
        {
            _serialized = new SerializedObject(this);
            _scriptField.objectType = typeof(MonoScript);
            _carriers.Clear();
        }

        private void OnGUI()
        {
            EditorGUI.BeginChangeCheck();

            EditorGUILayout.LabelField("Select Script to Analyze", EditorStyles.boldLabel);
            
            _scriptField.Draw("Selected MonoScript");
            var script = (MonoScript)_scriptField.value;

            GUILayout.Space(10);

            using (new EditorGUILayout.HorizontalScope())
            {
                if (!string.IsNullOrEmpty(script?.GetPath()))
                {
                    if (GUILayout.Button("Count Carriers", GUILayout.Width(120)))
                    {
                        StartScan(script);
                    }
                }
                else
                {
                    EditorGUI.BeginDisabledGroup(true);
                    GUILayout.Button("Count Carriers", GUILayout.Width(120));
                    EditorGUI.EndDisabledGroup();
                }
            }

            if (_isScanning)
            {
                EditorGUILayout.HelpBox("Scanning assets...", MessageType.Info);
                GUIUtility.ExitGUI(); // Ensure UI doesn't paint while we wait for the async thread to finish in Update or yield
                return;
            }

            GUILayout.Space(10);

            EditorGUILayout.LabelField($"Found {_carrierCount} prefabs carrying {script?.name ?? "unknown"}", EditorStyles.boldLabel);

            if (_carrierCount > 20)
            {
                EditorGUILayout.HelpBox(
                    $"Adding a serialized field to this script will reimport {_carrierCount} prefabs. Consider moving the field to a settings ScriptableObject instead.", 
                    MessageType.Warning);
            }

            _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos, GUILayout.Height(Mathf.Min(_carriers.Count * 16, 200)));
            
            foreach (var path in _carriers)
            {
                if (EditorGUILayout.SelectableLabel(path, EditorStyles.label, GUIStyle.none, EditorGUIUtility.singleVScrollbarStyle))
                {
                    var asset = AssetDatabase.LoadMainAssetAtPath(path);
                    Selection.activeObject = asset;
                    EditorGUIUtility.PingObject(asset);
                }
            }
            
            EditorGUILayout.EndScrollView();

            if (EditorGUI.EndChangeCheck())
            {
                // No specific action needed for change check on the serialized object in this context 
                // as we are not saving, but standard practice to keep track.
            }
        }

        private void StartScan(MonoScript script)
        {
            _carriers.Clear();
            _carrierCount = 0;
            
            if (string.IsNullOrEmpty(script.GetPath())) return;

            string pathGuid = AssetDatabase.AssetPathToGUID(script.GetPath());
            if (string.IsNullOrEmpty(pathGuid))
            {
                Debug.LogError("Could not find GUID for script: " + script.name);
                return;
            }

            string targetPattern = $"guid: {pathGuid}";

            // Get all prefabs in Assets
            string[] allPaths = AssetDatabase.FindAssets("t:Prefab", new[] { "Assets" });
            int total = allPaths.Count(g => !string.IsNullOrEmpty(g)); // Basic check, though FindAssets usually returns non-null GUIDs
            
            // Convert GUIDs to paths for iteration
            List<string> prefabPaths = new();
            foreach (var guid in allPaths)
            {
                string fullPath = AssetDatabase.GUIDToAssetPath(guid);
                if (!string.IsNullOrEmpty(fullPath) && fullPath.StartsWith("Assets/"))
                {
                    prefabPaths.Add(fullPath);
                }
            }

            // We use a coroutine-like pattern with EditorApplication.update to keep the UI responsive
            _isScanning = true;
            
            // Capture closure variables for the scanner loop
            int currentIndex = 0;
            
            EditorApplication.update += () =>
            {
                if (currentIndex >= prefabPaths.Count)
                {
                    _isScanning = false;
                    EditorApplication.update -= EditorApplication.currentUpdate;
                    Repaint();
                    return;
                }

                // Process a batch to avoid freezing too long between updates
                const int batchSize = 50; 
                int end = Mathf.Min(currentIndex + batchSize, prefabPaths.Count);

                for (int i = currentIndex; i < end; i++)
                {
                    if (EditorUtility.DisplayCancelableProgressBar(
                        "Scanning Prefabs", 
                        $"Checking {(i * 100) / prefabPaths.Count}% - {prefabPaths[i]}", 
                        (float)i / prefabPaths.Count))
                    {
                        _isScanning = false;
                        EditorUtility.ClearProgressBar();
                        EditorApplication.update -= EditorApplication.currentUpdate;
                        Repaint();
                        return; // Stop scanning
                    }

                    string filePath = System.IO.Path.Combine(Application.dataPath, prefabPaths[i].Replace("Assets/", ""));
                    
                    // Read file content as text to search for GUID
                    // Note: We are not loading the asset with Unity, just reading the disk file.
                    try 
                    {
                        if (File.ReadAllText(filePath).Contains(targetPattern))
                        {
                            _carriers.Add(prefabPaths[i]);
                        }
                    }
                    catch (IOException)
                    {
                        // Skip files that cannot be read (rare for prefabs, but possible in networked drives)
                        Debug.LogWarning($"Could not read file: {prefabPaths[i]}");
                    }
                }

                currentIndex = end;
            };
        }
    }
}

#endif

[qwen3.5:27b on http://192.168.1.189:11434: 888 prompt tokens, 1442 answer tokens, 49 tokens/s]