// FILE: ScriptCarriersWindow.cs
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

// Editor-only: this file lives in an Editor folder (Assembly-CSharp-Editor), so it is only compiled for the editor.
public class ScriptCarriersWindow : EditorWindow
{
    private const string MenuPath = "Tools/Debug/Script Carriers";
    private const string WindowTitle = "Script Carriers";
    private const int ProgressBarInterval = 200; // refresh the bar (and offer cancel) this often
    private const int WarnThreshold = 20;

    [SerializeField] private MonoScript targetScript;
    [SerializeField] private Vector2 scrollPos;

    private string resultText = string.Empty;
    private readonly List<string> carriers = new List<string>();

    [MenuItem(MenuPath)]
    private static void Open()
    {
        var window = GetWindow<ScriptCarriersWindow>(WindowTitle);
        window.minSize = new Vector2(400f, 320f);
    }

    private void OnGUI()
    {
        EditorGUILayout.HelpBox("Pick a MonoBehaviour script, then count how many prefabs in Assets reference it. " +
            "Each one is reimported when a serialized field is added to that script.", MessageType.Info);

        targetScript = EditorGUILayout.ObjectField<MonoScript>("Script", targetScript, true);

        using (new EditorGUILayout.HorizontalScope())
        {
            if (GUILayout.Button("Count carriers") && targetScript != null)
                CountCarriers();
        }

        EditorGUILayout.Space();

        if (carriers.Count > WarnThreshold)
        {
            EditorGUILayout.HelpBox("Adding a serialized field to this script reimports " + carriers.Count +
                " prefabs. Put the field on a settings ScriptableObject instead.", MessageType.Warning);
            EditorGUILayout.Space();
        }

        EditorGUILayout.LabelField(resultText, EditorStyles.boldLabel);

        if (carriers.Count > 0)
        {
            scrollPos = EditorGUILayout.BeginScrollView(scrollPos);
            foreach (string path in carriers)
            {
                if (GUILayout.Button(path, EditorStyles.linkLabel))
                    SelectAndPing(path);
            }
            EditorGUILayout.EndScrollView();
        }
    }

    private void CountCarriers()
    {
        string guid = AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(targetScript));
        if (string.IsNullOrEmpty(guid))
        {
            carriers.Clear();
            resultText = "Could not resolve a GUID for " + targetScript.name + ".";
            return;
        }

        string needle = "guid: " + guid;
        string[] files;
        try
        {
            files = Directory.GetFiles("Assets", "*.prefab", SearchOption.AllDirectories);
        }
        catch (IOException e)
        {
            carriers.Clear();
            resultText = "Could not list prefabs under Assets: " + e.Message;
            return;
        }

        string scriptName = targetScript.name;
        carriers.Clear();
        int readErrors = 0;
        try
        {
            for (int i = 0; i < files.Length; i++)
            {
                // Refresh the bar every few files and let the user cancel a scan that can take minutes.
                if (i % ProgressBarInterval == 0 &&
                    !EditorUtility.DisplayCancelableProgressBar("Counting carriers of " + scriptName,
                        "Prefab " + (i + 1) + " of " + files.Length, (float)i / files.Length))
                    break;

                string text;
                try
                {
                    text = File.ReadAllText(files[i]);
                }
                catch (IOException)
                {
                    readErrors++;
                    continue;
                }

                if (text.Contains(needle))
                    carriers.Add(files[i]);
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }

        resultText = carriers.Count + " prefabs carry " + scriptName;
        if (readErrors > 0)
            resultText += " (" + readErrors + " unreadable)";
    }

    private static void SelectAndPing(string assetPath)
    {
        var asset = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(assetPath);
        if (asset == null)
            return;

        Selection.activeObject = asset;
        EditorGUIUtility.PingObject(asset);
    }
}
