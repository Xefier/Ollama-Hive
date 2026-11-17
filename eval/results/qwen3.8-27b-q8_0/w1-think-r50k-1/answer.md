```csharp
// FILE: ApparelEditorWindow.cs
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    public class ApparelEditorWindow : EditorWindow
    {
        private enum StatusFilter
        {
            All,
            NotDone,
            Done,
            ManuallyHidden,
        }

        private List<ApparelObj> all;
        private Dictionary<string, ApparelObj> byAssetName;
        private ApparelObj selected;
        private string search = string.Empty;
        private StatusFilter filter = StatusFilter.All;
        private int slotFilterIndex;
        private string[] slotOptions;
        private Vector2 listScroll;
        private Vector2 detailScroll;
        private Editor cachedEditor;
        private bool needsReload;

        private GUIStyle notDoneStyle;
        private GUIStyle hiddenStyle;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        private static void Open()
        {
            GetWindow<ApparelEditorWindow>("Apparel Editor");
        }

        private void OnEnable()
        {
            BuildSlotOptions();
            LoadAll();
        }

        private void OnDisable()
        {
            if (cachedEditor != null)
            {
                DestroyImmediate(cachedEditor);
                cachedEditor = null;
            }
        }

        private void OnProjectChange()
        {
            needsReload = true;
            Repaint();
        }

        private void OnGUI()
        {
            if (needsReload)
            {
                LoadAll();
                needsReload = false;
            }

            var shown = GetShown();
            DrawToolbar(shown);

            EditorGUILayout.BeginHorizontal();
            DrawList(shown);
            DrawDetails();
            EditorGUILayout.EndHorizontal();
        }

        private void BuildSlotOptions()
        {
            var names = Enum.GetNames(typeof(ApparelSlot));
            slotOptions = new string[names.Length + 1];
            slotOptions[0] = "Any slot";
            for (int i = 0; i < names.Length; i++)
                slotOptions[i + 1] = names[i];
        }

        private void LoadAll()
        {
            // Editor tooling: FindAssets is fine here.
            var prevPath = selected != null ? AssetDatabase.GetAssetPath(selected) : string.Empty;

            all = new List<ApparelObj>();
            byAssetName = new Dictionary<string, ApparelObj>();

            var guids = AssetDatabase.FindAssets("t:ApparelObj");
            foreach (var guid in guids)
            {
                var assetPath = AssetDatabase.GUIDToAssetPath(guid);
                var obj = AssetDatabase.LoadAssetAtPath<ApparelObj>(assetPath);
                if (obj == null) continue;
                all.Add(obj);
                byAssetName[obj.name] = obj;
            }

            all.Sort((a, b) => string.CompareOrdinal(a.name, b.name));

            // Preserve selection across reload by asset path.
            if (!string.IsNullOrEmpty(prevPath))
                selected = all.Find(a => AssetDatabase.GetAssetPath(a) == prevPath);
        }

        private List<ApparelObj> GetShown()
        {
            if (all == null) return new List<ApparelObj>();

            return all.Where(a =>
            {
                if (search.Length > 0)
                {
                    var nameHit = a.name != null && a.name.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0;
                    var apparelName = a.Apparel?.Name;
                    var apparelNameHit = apparelName != null && apparelName.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0;
                    var displayName = a.Apparel?.DisplayName;
                    var displayNameHit = displayName != null && displayName.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0;
                    if (!nameHit && !apparelNameHit && !displayNameHit) return false;
                }

                switch (filter)
                {
                    case StatusFilter.NotDone:
                        if (!a.NotDone) return false;
                        break;
                    case StatusFilter.Done:
                        if (a.NotDone) return false;
                        break;
                    case StatusFilter.ManuallyHidden:
                        if (a.NotDone) return false;
                        if (a.UsableInCharacterCreator && (a.HiddenOnBodies == null || a.HiddenOnBodies.Length == 0))
                            return false;
                        break;
                }

                if (slotFilterIndex > 0)
                {
                    var slot = (ApparelSlot)Enum.Parse(typeof(ApparelSlot), slotOptions[slotFilterIndex]);
                    if (a.Slots == null || !a.Slots.Contains(slot)) return false;
                }

                return true;
            }).ToList();
        }

        private void DrawToolbar(List<ApparelObj> shown)
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);

            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));
            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));
            slotFilterIndex = EditorGUILayout.Popup(slotFilterIndex, slotOptions, EditorStyles.toolbarPopup, GUILayout.Width(90));

            GUILayout.FlexibleSpace();

            EditorGUILayout.Label($"{shown.Count} of {all.Count}", EditorStyles.miniLabel);

            var anyNotDoneShown = shown.Any(a => a.NotDone);
            using (new EditorGUI.DisabledScope(!anyNotDoneShown))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton))
                {
                    var notDoneShown = shown.Where(a => a.NotDone).ToList();
                    var n = notDoneShown.Count;
                    if (EditorUtility.DisplayDialog("Mark apparel done",
                        $"Mark {n} apparel done? They become visible to players.",
                        "Mark done", "Cancel"))
                    {
                        MarkDone(notDoneShown, byAssetName);
                    }
                }
            }

            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton))
            {
                LoadAll();
            }

            EditorGUILayout.EndHorizontal();
        }

        private void DrawList(List<ApparelObj> shown)
        {
            EditorGUILayout.BeginVertical(GUILayout.Width(320));

            listScroll = EditorGUILayout.BeginScrollView(listScroll);

            if (shown.Count == 0)
            {
                GUILayout.Label("No apparel matches.");
            }
            else
            {
                for (int i = 0; i < shown.Count; i++)
                {
                    var apparel = shown[i];
                    var row = EditorGUILayout.GetControlRect(false, 20);

                    if (apparel == selected)
                        EditorGUI.DrawRect(row, new Color(0.24f, 0.48f, 0.90f, 0.35f));

                    var nameRect = new Rect(row.x, row.y, row.width - 140, row.height);
                    EditorGUI.LabelField(nameRect, apparel.name);

                    var slotRect = new Rect(row.x + row.width - 140, row.y, 70, row.height);
                    var slotText = apparel.Slots != null && apparel.Slots.Length > 0 ? apparel.Slots[0].ToString() : "-";
                    EditorGUI.LabelField(slotRect, slotText);

                    var tagRect = new Rect(row.x + row.width - 70, row.y, 70, row.height);
                    if (apparel.NotDone)
                    {
                        EditorGUI.LabelField(tagRect, "Not done", GetNotDoneStyle());
                    }
                    else if (!apparel.UsableInCharacterCreator || (apparel.HiddenOnBodies != null && apparel.HiddenOnBodies.Length > 0))
                    {
                        EditorGUI.LabelField(tagRect, "Hidden", GetHiddenStyle());
                    }

                    if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
                    {
                        selected = apparel;
                        Event.current.Use();
                        GUI.FocusControl(null);
                        Repaint();
                    }
                }

                // Keyboard navigation through the shown list.
                if (Event.current.type == EventType.KeyDown)
                {
                    if (Event.current.keyCode == KeyCode.UpArrow || Event.current.keyCode == KeyCode.DownArrow)
                    {
                        var idx = shown.IndexOf(selected);
                        var next = Event.current.keyCode == KeyCode.UpArrow ? idx - 1 : idx + 1;
                        if (next < 0) next = shown.Count - 1;
                        if (next >= shown.Count) next = 0;
                        selected = shown[next];
                        Event.current.Use();
                        Repaint();
                    }
                }
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void DrawDetails()
        {
            EditorGUILayout.BeginVertical();

            detailScroll = EditorGUILayout.BeginScrollView(detailScroll);

            if (selected == null)
            {
                EditorGUILayout.HelpBox("Select an apparel on the left.", MessageType.Info);
            }
            else
            {
                using (new EditorGUI.DisabledScope(true))
                    EditorGUILayout.ObjectField("Asset", selected, typeof(ApparelObj), false);

                if (selected.NotDone)
                {
                    EditorGUILayout.HelpBox("Not done yet: hidden from players on every body and never sold. Mark it done to show it.", MessageType.Warning);
                    if (GUILayout.Button("Mark done", GUILayout.Height(24)))
                    {
                        MarkDone(new[] { selected }, byAssetName);
                    }
                }
                else
                {
                    var isManuallyHidden = !selected.UsableInCharacterCreator ||
                                           (selected.HiddenOnBodies != null && selected.HiddenOnBodies.Length > 0);
                    var msg = "Done: visible to players";
                    if (isManuallyHidden)
                        msg += " (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)";
                    EditorGUILayout.HelpBox(msg, MessageType.Info);
                }

                EditorGUILayout.BeginHorizontal();
                if (GUILayout.Button("Ping"))
                    EditorGUIUtility.PingObject(selected);
                if (GUILayout.Button("Select in Project"))
                    Selection.activeObject = selected;
                EditorGUILayout.EndHorizontal();

                Editor.CreateCachedEditor(selected, null, ref cachedEditor);
                if (cachedEditor != null)
                    cachedEditor.OnInspectorGUI();
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            // A garment may have one asset per body, all linked by name; marking one done
            // marks every body's version so the whole set becomes visible together.
            var toMark = new HashSet<ApparelObj>();

            foreach (var item in items)
            {
                toMark.Add(item);

                var versions = ApparelCatalog.BodyVersionsOf(item.Apparel.Name);
                if (versions != null)
                {
                    foreach (var entry in versions)
                    {
                        if (byAssetName.TryGetValue(entry.AssetName, out var versionObj))
                            toMark.Add(versionObj);
                    }
                }
            }

            var marked = new List<string>();

            foreach (var apparel in toMark)
            {
                if (!apparel.NotDone) continue;
                Undo.RecordObject(apparel, "Mark apparel done");
                apparel.NotDone = false;
                EditorUtility.SetDirty(apparel);
                AssetDatabase.SaveAssetIfDirty(apparel);
                marked.Add(apparel.name);
            }

            if (marked.Count > 0)
                Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", marked)}");
        }

        private GUIStyle GetNotDoneStyle()
        {
            if (notDoneStyle == null)
            {
                notDoneStyle = new GUIStyle(EditorStyles.miniLabel);
                notDoneStyle.normal.textColor = new Color(1f, 0.6f, 0.2f);
            }
            return notDoneStyle;
        }

        private GUIStyle GetHiddenStyle()
        {
            if (hiddenStyle == null)
            {
                hiddenStyle = new GUIStyle(EditorStyles.miniLabel);
                hiddenStyle.normal.textColor = Color.gray;
            }
            return hiddenStyle;
        }
    }
}
#endif
```

- Used `Debug.Log` in `MarkDone` exactly as the spec dictates ("editor tooling may use Debug.Log"), overriding the general project rule against `Debug.Log`.
- `ApparelCatalog.BodyVersionsOf` and `ApparelIndex.Entry.AssetName` are referenced as described in the task; I assumed they exist in the project with those exact signatures.
- `Apparel.Name` and `Apparel.DisplayName` are assumed to be string fields/properties on `CC.scrObj_Apparel.Apparel`, accessible via null-conditional on the `Apparel` struct field.
- Keyboard navigation wraps around (Up at index 0 goes to last, Down at last goes to 0) for convenience; the spec didn't specify wrap vs. clamp.
- The "Hidden" tag in the list is shown for any done item that is manually hidden (UsableInCharacterCreator off or HiddenOnBodies non-empty), matching the ManuallyHidden filter definition.

[qwen3.8:27b-q8_0 on http://192.168.1.232:11434: 3680 prompt tokens, 9381 answer tokens, 52 tokens/s]