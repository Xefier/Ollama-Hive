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
        enum StatusFilter { All, NotDone, Done, ManuallyHidden }

        static readonly Color SelectedRowColor = new Color(0.24f, 0.48f, 0.90f, 0.35f);

        readonly List<ApparelObj> all = new List<ApparelObj>();
        readonly List<ApparelObj> shown = new List<ApparelObj>();
        readonly List<ApparelObj> pending = new List<ApparelObj>();
        readonly Dictionary<string, ApparelObj> byAssetName = new Dictionary<string, ApparelObj>();
        ApparelSlot[] slotValues;
        string[] slotOptions;

        string search = "";
        StatusFilter statusFilter;
        int slotIndex;
        ApparelObj selected;
        string selectedPath;
        Vector2 listScroll;
        Vector2 detailScroll;
        Editor cachedEditor;
        bool reloadPending;
        GUIStyle notDoneStyle;
        GUIStyle hiddenStyle;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        static void Open()
        {
            GetWindow<ApparelEditorWindow>("Apparel Editor");
        }

        void OnEnable()
        {
            slotValues = (ApparelSlot[])Enum.GetValues(typeof(ApparelSlot));
            string[] names = Enum.GetNames(typeof(ApparelSlot));
            slotOptions = new string[names.Length + 1];
            slotOptions[0] = "Any slot";
            names.CopyTo(slotOptions, 1);
            Reload();
        }

        void OnDisable()
        {
            if (cachedEditor != null) DestroyImmediate(cachedEditor);
            cachedEditor = null;
        }

        void OnProjectChange()
        {
            reloadPending = true;
            Repaint();
        }

        void OnGUI()
        {
            if (reloadPending)
            {
                reloadPending = false;
                Reload();
            }
            EnsureStyles();
            RebuildShown();
            HandleArrowKeys();

            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);
            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));
            statusFilter = (StatusFilter)EditorGUILayout.EnumPopup(statusFilter, EditorStyles.toolbarPopup, GUILayout.Width(110));
            slotIndex = EditorGUILayout.Popup(slotIndex, slotOptions, EditorStyles.toolbarPopup, GUILayout.Width(90));
            GUILayout.FlexibleSpace();
            GUILayout.Label(shown.Count + " of " + all.Count, EditorStyles.miniLabel);
            using (new EditorGUI.DisabledScope(pending.Count == 0))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton) &&
                    EditorUtility.DisplayDialog("Mark apparel done",
                        "Mark " + pending.Count + " apparel done? They become visible to players.", "Mark done", "Cancel"))
                {
                    MarkDone(pending, byAssetName);
                }
            }
            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton)) reloadPending = true;
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.BeginVertical(GUILayout.Width(320));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);
            DrawList();
            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
            EditorGUILayout.BeginVertical();
            DrawDetails();
            EditorGUILayout.EndVertical();
            EditorGUILayout.EndHorizontal();
        }

        void EnsureStyles()
        {
            if (notDoneStyle != null) return;
            notDoneStyle = new GUIStyle(EditorStyles.miniLabel);
            notDoneStyle.normal.textColor = new Color(1f, 0.6f, 0.2f);
            hiddenStyle = new GUIStyle(EditorStyles.miniLabel);
            hiddenStyle.normal.textColor = Color.gray;
        }

        void Reload()
        {
            all.Clear();
            byAssetName.Clear();
            // Editor tooling: scanning the project for assets is fine here, it never runs in gameplay.
            string[] guids = AssetDatabase.FindAssets("t:ApparelObj");
            foreach (string guid in guids)
            {
                ApparelObj apparel = AssetDatabase.LoadAssetAtPath<ApparelObj>(AssetDatabase.GUIDToAssetPath(guid));
                if (apparel == null) continue;
                all.Add(apparel);
                byAssetName[apparel.name] = apparel;
            }
            all.Sort((a, b) => string.CompareOrdinal(a.name, b.name));

            // Keyed by path, so the selection survives a reload.
            string path = selectedPath;
            Select(string.IsNullOrEmpty(path) ? null : all.Find(a => AssetDatabase.GetAssetPath(a) == path));
            Repaint();
        }

        void Select(ApparelObj apparel)
        {
            selected = apparel;
            selectedPath = apparel != null ? AssetDatabase.GetAssetPath(apparel) : null;
        }

        void RebuildShown()
        {
            shown.Clear();
            pending.Clear();
            foreach (ApparelObj apparel in all)
            {
                if (!PassesStatus(apparel) || !PassesSlot(apparel) || !PassesSearch(apparel)) continue;
                shown.Add(apparel);
                if (apparel.NotDone) pending.Add(apparel);
            }
        }

        bool PassesStatus(ApparelObj apparel)
        {
            switch (statusFilter)
            {
                case StatusFilter.NotDone: return apparel.NotDone;
                case StatusFilter.Done: return !apparel.NotDone;
                case StatusFilter.ManuallyHidden: return IsManuallyHidden(apparel);
                default: return true;
            }
        }

        bool PassesSlot(ApparelObj apparel)
        {
            if (slotIndex == 0) return true;
            return apparel.Slots != null && Array.IndexOf(apparel.Slots, slotValues[slotIndex - 1]) >= 0;
        }

        bool PassesSearch(ApparelObj apparel)
        {
            if (string.IsNullOrEmpty(search)) return true;
            return ContainsText(apparel.name, search) ||
                   ContainsText(apparel.Apparel.Name, search) ||
                   ContainsText(apparel.Apparel.DisplayName, search);
        }

        static bool ContainsText(string text, string term)
        {
            return text != null && text.IndexOf(term, StringComparison.OrdinalIgnoreCase) >= 0;
        }

        static bool IsManuallyHidden(ApparelObj apparel)
        {
            return !apparel.NotDone &&
                   (!apparel.UsableInCharacterCreator || (apparel.HiddenOnBodies != null && apparel.HiddenOnBodies.Length > 0));
        }

        void HandleArrowKeys()
        {
            // Left to the text field while it has focus, so the arrows still move its caret.
            if (Event.current.type != EventType.KeyDown || GUIUtility.keyboardControl != 0 || shown.Count == 0) return;
            if (Event.current.keyCode != KeyCode.UpArrow && Event.current.keyCode != KeyCode.DownArrow) return;

            int step = Event.current.keyCode == KeyCode.DownArrow ? 1 : -1;
            int index = shown.IndexOf(selected);
            if (index < 0) index = step > 0 ? 0 : shown.Count - 1;
            else index = Mathf.Clamp(index + step, 0, shown.Count - 1);
            Select(shown[index]);
            Event.current.Use();
            Repaint();
        }

        void DrawList()
        {
            if (shown.Count == 0)
            {
                GUILayout.Label("No apparel matches.");
                return;
            }
            foreach (ApparelObj apparel in shown)
            {
                Rect row = EditorGUILayout.GetControlRect(false, 20);
                if (apparel == selected) EditorGUI.DrawRect(row, SelectedRowColor);

                EditorGUI.LabelField(new Rect(row.x, row.y, row.width - 140, row.height), apparel.name);
                string slot = apparel.PrimarySlot >= 0 ? ((ApparelSlot)apparel.PrimarySlot).ToString() : "-";
                EditorGUI.LabelField(new Rect(row.xMax - 140, row.y, 70, row.height), slot);
                Rect tagRect = new Rect(row.xMax - 70, row.y, 70, row.height);
                if (apparel.NotDone) EditorGUI.LabelField(tagRect, "Not done", notDoneStyle);
                else if (IsManuallyHidden(apparel)) EditorGUI.LabelField(tagRect, "Hidden", hiddenStyle);

                if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
                {
                    Select(apparel);
                    Event.current.Use();
                    GUI.FocusControl(null);
                }
            }
        }

        void DrawDetails()
        {
            detailScroll = EditorGUILayout.BeginScrollView(detailScroll);
            if (selected == null)
            {
                EditorGUILayout.HelpBox("Select an apparel on the left.", MessageType.Info);
            }
            else
            {
                using (new EditorGUI.DisabledScope(true))
                {
                    EditorGUILayout.ObjectField("Asset", selected, typeof(ApparelObj), false);
                }

                if (selected.NotDone)
                {
                    EditorGUILayout.HelpBox("Not done yet: hidden from players on every body and never sold. " +
                                            "Mark it done to show it.", MessageType.Warning);
                    if (GUILayout.Button("Mark done", GUILayout.Height(24))) MarkDone(new[] { selected }, byAssetName);
                }
                else
                {
                    string text = "Done: visible to players";
                    if (IsManuallyHidden(selected))
                        text += " (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)";
                    EditorGUILayout.HelpBox(text, MessageType.Info);
                }

                EditorGUILayout.BeginHorizontal();
                if (GUILayout.Button("Ping")) EditorGUIUtility.PingObject(selected);
                if (GUILayout.Button("Select in Project")) Selection.activeObject = selected;
                EditorGUILayout.EndHorizontal();

                // The inspector records its own undo and dirties the asset, so edits there need nothing extra.
                Editor.CreateCachedEditor(selected, null, ref cachedEditor);
                cachedEditor.OnInspectorGUI();
            }
            EditorGUILayout.EndScrollView();
        }

        // One place for marking: a garment's body versions share one status, so they are marked together.
        static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            var group = new HashSet<ApparelObj>();
            foreach (ApparelObj item in items)
            {
                group.Add(item);
                foreach (ApparelIndex.Entry version in ApparelCatalog.BodyVersionsOf(item.Apparel.Name))
                {
                    if (byAssetName.TryGetValue(version.AssetName, out ApparelObj other)) group.Add(other);
                }
            }

            var names = new List<string>();
            foreach (ApparelObj apparel in group)
            {
                if (!apparel.NotDone) continue;
                Undo.RecordObject(apparel, "Mark apparel done");
                apparel.NotDone = false;
                EditorUtility.SetDirty(apparel);
                // Saved one asset at a time: the editor is shared, so never AssetDatabase.SaveAssets().
                AssetDatabase.SaveAssetIfDirty(apparel);
                names.Add(apparel.name);
            }
            Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", names)}");
        }
    }
}
#endif
```

- `ApparelCatalog.BodyVersionsOf`, `ApparelIndex.Entry.AssetName` and `ApparelSlot` are used as the task describes; I assumed they are in namespace `LiminalLabs.CharacterCustomizer`, `BodyVersionsOf` is static and returns a non-null list.
- I assumed `CC.scrObj_Apparel.Apparel` has string members `Name` and `DisplayName` and is never null on an `ApparelObj` (no null check on it, unlike the string fields).
- The selection is kept by asset path across reloads, so renaming the selected asset drops the selection.
- Up/Down arrows are ignored while a text field has keyboard focus (`GUIUtility.keyboardControl != 0`), so they still move the search caret; the task did not say this.
- "Mark all shown done" marks the Not-done versions of the shown items even when those versions are filtered out, as the task's MARKING DONE rule requires; the dialog counts only the shown items.
