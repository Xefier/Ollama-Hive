```csharp
// FILE: ApparelEditorWindow.cs
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    public class ApparelEditorWindow : EditorWindow
    {
        private enum StatusFilter { All, NotDone, Done, ManuallyHidden }

        private List<ApparelObj> allApparel = new List<ApparelObj>();
        private List<ApparelObj> shownApparel = new List<ApparelObj>();
        private Dictionary<string, ApparelObj> byAssetName = new Dictionary<string, ApparelObj>();

        private ApparelObj selected;
        private string search = "";
        private StatusFilter filter = StatusFilter.All;
        private int slotFilterIndex;

        private Vector2 listScroll;
        private Vector2 detailScroll;

        private Editor cachedEditor;
        private bool needsReload;

        // Built once, cached on first use
        private GUIStyle notDoneStyle;
        private GUIStyle hiddenStyle;
        private string[] slotOptions;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        private static void Open()
        {
            GetWindow<ApparelEditorWindow>("Apparel Editor");
        }

        private void OnEnable()
        {
            LoadApparel();
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
                needsReload = true;
                needsReload = false;
                LoadApparel();
            }

            DrawToolbar();
            ApplyFilters();

            EditorGUILayout.BeginHorizontal();
            DrawList();
            DrawDetails();
            EditorGUILayout.EndHorizontal();
        }

        // ── Loading ──────────────────────────────────────────────────────────

        private void LoadApparel()
        {
            var prevSelected = selected;
            allApparel.Clear();
            byAssetName.Clear();

            // Editor tooling: FindAssets is appropriate here.
            var guids = AssetDatabase.FindAssets("t:ApparelObj");
            foreach (var guid in guids)
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                var asset = AssetDatabase.LoadAssetAtPath<ApparelObj>(path);
                if (asset == null) continue;
                allApparel.Add(asset);
                byAssetName[asset.name] = asset;
            }

            allApparel.Sort((a, b) => string.CompareOrdinal(a.name, b.name));

            // Preserve selection across reloads when the asset is still present
            selected = (prevSelected != null && allApparel.Contains(prevSelected)) ? prevSelected : null;
        }

        // ── Filtering ────────────────────────────────────────────────────────

        private void ApplyFilters()
        {
            shownApparel.Clear();
            foreach (var a in allApparel)
            {
                if (MatchesSearch(a) && MatchesStatus(a) && MatchesSlot(a))
                    shownApparel.Add(a);
            }
        }

        private bool MatchesSearch(ApparelObj a)
        {
            if (string.IsNullOrEmpty(search)) return true;
            if (a.name.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (a.Apparel.Name != null && a.Apparel.Name.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (a.Apparel.DisplayName != null && a.Apparel.DisplayName.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0) return true;
            return false;
        }

        private bool MatchesStatus(ApparelObj a)
        {
            switch (filter)
            {
                case StatusFilter.NotDone:
                    return a.NotDone;
                case StatusFilter.Done:
                    return !a.NotDone;
                case StatusFilter.ManuallyHidden:
                    return !a.NotDone && IsManuallyHidden(a);
                default:
                    return true;
            }
        }

        private bool MatchesSlot(ApparelObj a)
        {
            if (slotFilterIndex == 0) return true;
            if (a.Slots == null) return false;
            var slot = (ApparelSlot)(slotFilterIndex - 1);
            return Array.Contains(a.Slots, slot);
        }

        private static bool IsManuallyHidden(ApparelObj a)
        {
            return !a.UsableInCharacterCreator
                || (a.HiddenOnBodies != null && a.HiddenOnBodies.Length > 0);
        }

        // ── Toolbar ──────────────────────────────────────────────────────────

        private void DrawToolbar()
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);

            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));

            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));

            slotFilterIndex = EditorGUILayout.Popup(
                slotFilterIndex, GetSlotOptions(), EditorStyles.toolbarPopup, GUILayout.Width(90));

            GUILayout.FlexibleSpace();

            var shown = shownApparel.Count;
            var total = allApparel.Count;
            EditorGUILayout.LabelField($"{shown} of {total}", EditorStyles.miniLabel);

            var anyNotDoneShown = false;
            var notDoneCount = 0;
            foreach (var a in allApparel)
            {
                if (a.NotDone)
                {
                    anyNotDoneShown = true;
                    notDoneCount++;
                }
            }
            // Recount only shown items for the dialog
            notDoneCount = 0;
            foreach (var a in shownApparel)
                if (a.NotDone) notDoneCount++;

            using (new EditorGUI.DisabledScope(notDoneCount == 0))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton))
                {
                    if (EditorUtility.DisplayDialog(
                        "Mark apparel done",
                        $"Mark {notDoneCount} apparel done? They become visible to players.",
                        "Mark done", "Cancel"))
                    {
                        var toMark = new List<ApparelObj>();
                        foreach (var a in shownApparel)
                            if (a.NotDone) toMark.Add(a);
                        MarkDone(toMark, byAssetName);
                        ApplyFilters();
                        Repaint();
                    }
                }
            }

            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton))
            {
                LoadApparel();
                ApplyFilters();
                Repaint();
            }

            EditorGUILayout.EndHorizontal();
        }

        private string[] GetSlotOptions()
        {
            if (slotOptions == null)
            {
                var names = System.Enum.GetNames(typeof(ApparelSlot));
                slotOptions = new string[names.Length + 1];
                slotOptions[0] = "Any slot";
                for (int i = 0; i < names.Length; i++)
                    slotOptions[i + 1] = names[i];
            }
            return slotOptions;
        }

        // ── List (left pane) ─────────────────────────────────────────────────

        private void DrawList()
        {
            EditorGUILayout.BeginVertical(GUILayout.Width(320));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);

            if (shownApparel.Count == 0)
            {
                EditorGUILayout.LabelField("No apparel matches.");
            }
            else
            {
                HandleKeyboardNav();

                for (int i = 0; i < shownApparel.Count; i++)
                {
                    var apparel = shownApparel[i];
                    var row = EditorGUILayout.GetControlRect(false, 20);

                    if (apparel == selected)
                        EditorGUI.DrawRect(row, new Color(0.24f, 0.48f, 0.90f, 0.35f));

                    // Name (left portion)
                    var nameRect = new Rect(row.x, row.y, row.width - 140, row.height);
                    EditorGUI.LabelField(nameRect, apparel.name);

                    // Primary slot (70 px)
                    var slotRect = new Rect(row.x + row.width - 140, row.y, 70, row.height);
                    var slotText = (apparel.Slots != null && apparel.Slots.Length > 0)
                        ? apparel.Slots[0].ToString() : "-";
                    EditorGUI.LabelField(slotRect, slotText);

                    // Status tag (70 px)
                    var tagRect = new Rect(row.x + row.width - 70, row.y, 70, row.height);
                    if (apparel.NotDone)
                        EditorGUI.LabelField(tagRect, "Not done", GetNotDoneStyle());
                    else if (IsManuallyHidden(apparel))
                        EditorGUI.LabelField(tagRect, "Hidden", GetHiddenStyle());

                    // Selection
                    if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
                    {
                        selected = apparel;
                        Event.current.Use();
                        GUI.FocusControl(null);
                    }
                }
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void HandleKeyboardNav()
        {
            if (Event.current.type != EventType.KeyDown || shownApparel.Count == 0) return;

            var idx = shownApparel.IndexOf(selected);
            if (idx < 0) idx = -1;

            if (Event.current.keyCode == KeyCode.UpArrow)
            {
                idx = (idx <= 0) ? shownApparel.Count - 1 : idx - 1;
                selected = shownApparel[idx];
                Event.current.Use();
            }
            else if (Event.current.keyCode == KeyCode.DownArrow)
            {
                idx = (idx >= shownApparel.Count - 1) ? 0 : idx + 1;
                selected = shownApparel[idx];
                Event.current.Use();
            }
        }

        // ── Details (right pane) ─────────────────────────────────────────────

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
                    EditorGUILayout.HelpBox(
                        "Not done yet: hidden from players on every body and never sold. Mark it done to show it.",
                        MessageType.Warning);
                    if (GUILayout.Button("Mark done", GUILayout.Height(24)))
                    {
                        MarkDone(new[] { selected }, byAssetName);
                        ApplyFilters();
                        Repaint();
                    }
                }
                else
                {
                    var msg = "Done: visible to players";
                    if (IsManuallyHidden(selected))
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

        // ── Mark done ────────────────────────────────────────────────────────

        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            var set = new HashSet<ApparelObj>();
            foreach (var item in items)
            {
                set.Add(item);
                var versions = ApparelCatalog.BodyVersionsOf(item.Apparel.Name);
                if (versions != null)
                {
                    foreach (var entry in versions)
                    {
                        if (entry.AssetName != null && byAssetName.TryGetValue(entry.AssetName, out var version))
                            set.Add(version);
                    }
                }
            }

            var markedNames = new List<string>();
            foreach (var apparel in set)
            {
                if (apparel.NotDone)
                {
                    Undo.RecordObject(apparel, "Mark apparel done");
                    apparel.NotDone = false;
                    EditorUtility.SetDirty(apparel);
                    AssetDatabase.SaveAssetIfDirty(apparel);
                    markedNames.Add(apparel.name);
                }
            }

            if (markedNames.Count > 0)
                Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", markedNames)}");
        }

        // ── Lazy styles ──────────────────────────────────────────────────────

        private GUIStyle GetNotDoneStyle()
        {
            if (notDoneStyle == null)
                notDoneStyle = CreateTagStyle(new Color(1f, 0.6f, 0.2f));
            return notDoneStyle;
        }

        private GUIStyle GetHiddenStyle()
        {
            if (hiddenStyle == null)
                hiddenStyle = CreateTagStyle(new Color(0.6f, 0.6f, 0.6f));
            return hiddenStyle;
        }

        private static GUIStyle CreateTagStyle(Color color)
        {
            var style = new GUIStyle(EditorStyles.miniLabel);
            style.normal.textColor = color;
            return style;
        }
    }
}
#endif
```

- `ApparelCatalog.BodyVersionsOf` and `ApparelIndex.Entry.AssetName` are referenced as described in the prompt; I assumed they are accessible in the same namespace (or via a using already present in the assembly).
- `Apparel.Name` and `Apparel.DisplayName` are assumed to be `string` fields/properties on the `CC.scrObj_Apparel.Apparel` type (consistent with the `LookIndexIn` method in the given source).
- `Editor.CreateCachedEditor(Object, Type, ref Editor)` overload is used as specified; if your Unity version only exposes the `SerializedObject` overload, the call site would need a one-line change.
- The "Mark all shown done" toolbar button counts **shown** (filtered) Not-done items for the dialog; the `IsManuallyHidden` check inside `MarkDone` is not needed because the method itself only touches items with `NotDone == true`.
- `ApplyFilters` is called every `OnGUI` after the toolbar is drawn; with the small asset counts expected in an editor window this avoids stale-filter bugs at negligible cost.

[qwen3.8:27b on http://192.168.1.189:11434: 3685 prompt tokens, 11538 answer tokens, 127 tokens/s]