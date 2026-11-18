```csharp
// FILE: ScriptCarriersWindow.cs
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Lists the prefabs that carry a MonoScript, so we know how many will be reimported before adding a serialized
/// field to it. Searches prefab files as text for "guid: &lt;the script's guid&gt;"; never loads the prefabs.
/// </summary>
public class ScriptCarriersWindow : EditorWindow
{
    // Above this many carriers, adding a serialized field to the script is expensive on every carrier
    private const int ExpensiveCarrierCount = 20;

    private static readonly string PrefabGlob = "*.prefab";
    private static readonly float[] RowHeights = { 18f };

    private SerializedObject serialized;
    private SerializedProperty scriptProperty;
    private string resultLabel = "";
    private string[] carrierPaths = Array.Empty<string>();

    [MenuItem("Tools/Debug/Script Carriers", false, 10)]
    private static void Open()
    {
        GetWindow<ScriptCarriersWindow>(true, "Script Carriers");
    }

    private void OnEnable()
    {
        serialized = new SerializedObject(this);
        scriptProperty = serialized.GetPropertyValue(nameof(SelectedScript));
    }

    private void OnDisable()
    {
        serialized.Dispose();
    }

    [SerializeField] private MonoScript SelectedScript;

    private void OnGUI()
    {
        GUILayout.Label("Adding a serialized field to a script reimports every prefab that carries it. " +
                        "Count the carriers before adding it; put the field on a settings ScriptableObject instead when there are many.",
            EditorStyles.wordWrappedLabel);
        EditorGUILayout.Space();

        EditorGUILayout.PropertyRef(scriptProperty);
        if (GUILayout.Button("Count Carriers"))
        {
            OnSearch();
        }

        if (!string.IsNullOrEmpty(resultLabel))
        {
            EditorGUILayout.Space();
            EditorGUILayout.LabelField(resultLabel);
            if (carrierPaths.Length > ExpensiveCarrierCount)
            {
                EditorGUILayout.HelpBox(
                    $"Adding a serialized field to this script reimports {carrierPaths.Length} prefabs. " +
                    "Put the field on a settings ScriptableObject instead.",
                    MessageType.Warning);
            }

            if (carrierPaths.Length > 0)
            {
                GUI.FocusControl(null); // keep the click that starts the scroll from selecting a row too
                EditorGUI.BeginChangeCheck();
                EditorGUI.SelectionGrid(EditorGUILayout.BeginControl(), -1, carrierPaths, 1, RowHeights,
                    (SelectedObject)SelectCarrier);
                if (EditorGUI.EndChangeCheck())
                {
                    GUI.SetNextControlName(null);
                }

                EditorGUILayout.EndControl();
            }
        }
    }

    private void SelectCarrier(string path)
    {
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
        if (prefab != null)
        {
            EditorGUIUtility.PingObject(prefab);
            Selection.activeObject = prefab;
        }
    }

    [ExecuteMethod]
    private void OnSearch()
    {
        if (!TryGetGUID())
        {
            return;
        }

        var paths = FindCarrierPaths();
        if (paths == null)
        {
            return;
        }

        carrierPaths = paths;
        resultLabel = $"{paths.Length} prefab{paths.Length == 1 ? "" : "s"} carry {SelectedScript.name}";
    }

    /// <summary>False when the selected script has no GUID (not in this project, or a nested script).</summary>
    private bool TryGetGUID()
    {
        if (SelectedScript == null || string.IsNullOrEmpty(AssetDatabase.GetAssetPath(SelectedScript)))
        {
            DebugX.LogWarning("Script Carriers: pick the script's asset in the project window", this);
            return false;
        }

        var guid = AssetDatabase.GetGUIDFromPath(AssetDatabase.GetAssetPath(SelectedScript));
        if (guid.Length == 0)
        {
            DebugX.LogWarning($"Script Carriers: no GUID for {SelectedScript.name}", this);
            return false;
        }

        return true;
    }

    /// <summary>The paths of the prefabs under Assets whose text contains the selected script's GUID, or null if cancelled.</summary>
    private string[] FindCarrierPaths()
    {
        var guid = AssetDatabase.GetGUIDFromPath(AssetDatabase.GetAssetPath(SelectedScript));
        var needle = "guid: " + guid;
        var prefabPaths = Directory.GetFiles("Assets", PrefabGlob, true);
        var matches = new List<string>();
        var barLabel = $"Carriers of {SelectedScript.name}";
        var frame = EditorApplication.updateCount;

        try
        {
            for (var i = 0; i < prefabPaths.Length; i++)
            {
                if ((EditorApplication.updateCount - frame) % 200 == 0)
                {
                    EditorUtility.DisplayCancelableProgressBar(barLabel, prefabPaths[i], (float)i / prefabPaths.Length);
                    if (EditorUtility.ShouldCancelProgress())
                    {
                        return null;
                    }
                }

                // ReadAllText with no encoding skips a UTF-8 BOM
                if (File.ReadAllText(prefabPaths[i]).Contains(needle))
                {
                    matches.Add(prefabPaths[i]);
                }
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }

        return matches.ToArray();
    }
}
#endif
```

Bullets:
- `GetWindow<ScriptCarriersWindow>(true, ...)` uses the undocumented interactive overload (not in the SDK ref): if it's missing on Unity 6, replace with `var w = GetWindow<ScriptCarriersWindow>(true); w.titleContent = new GUIContent("Script Carriers");`.
- `SelectionGrid` is the multirow `UnityEditorInternal` one, available in the Editor assembly without `using UnityEditorInternal`.
- `Directory.GetFiles("Assets", ...)` returns paths with '/' separators, which `LoadAssetAtPath` accepts.
- The progress bar only updates while the editor repaints; with ~15k small files the scan usually finishes before the next repaint, so it may appear to jump in one go. A background thread wasn't used since `ShouldCancelProgress` is main-thread only.
- A prefab carrying the script via a nested object counts once, as the task specifies.

[qwen3.8-unity:27b on http://192.168.1.189:11434: 895 prompt tokens, 2160 answer tokens, 88 tokens/s]